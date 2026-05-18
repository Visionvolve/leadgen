/**
 * Content script for LinkedIn profile and company page validation.
 *
 * When the user visits a LinkedIn profile (/in/*) or company page (/company/*),
 * this script extracts key data from the DOM, sends it to the service worker
 * for CRM matching, and displays a floating validation overlay with match status.
 *
 * Design decisions:
 * - No extra LinkedIn API calls — only parse the DOM of the page the user is viewing
 * - Debounce validation requests (1s) to handle SPA navigation
 * - Cache results in chrome.storage.local (1h TTL)
 * - Only send data to user's own leadgen instance
 */

// ============== BUILD-TIME GLOBALS ==============
declare const __EXT_ENV__: 'prod' | 'staging';

// ============== LOGGING ==============
const LOG_PREFIX = '[VV LinkedIn Validator]';

const log = {
  info: (msg: string, ...args: unknown[]) => console.log(`${LOG_PREFIX} ${msg}`, ...args),
  success: (msg: string, ...args: unknown[]) => console.log(`${LOG_PREFIX} ${msg}`, ...args),
  warn: (msg: string, ...args: unknown[]) => console.warn(`${LOG_PREFIX} ${msg}`, ...args),
  error: (msg: string, ...args: unknown[]) => console.error(`${LOG_PREFIX} ${msg}`, ...args),
  debug: (msg: string, ...args: unknown[]) => console.debug(`${LOG_PREFIX} ${msg}`, ...args),
};

// ============== TYPES ==============

interface ProfileData {
  fullName: string;
  headline: string;
  companyName: string;
  location: string;
  profilePhotoUrl: string;
  about: string;
  linkedinUrl: string;
}

interface CompanyPageData {
  companyName: string;
  industry: string;
  employeeCount: string;
  website: string;
  headquarters: string;
  description: string;
  linkedinUrl: string;
}

interface ValidationResult {
  match: boolean;
  contact?: Record<string, unknown>;
  company?: Record<string, unknown>;
  enrichment_quality?: Record<string, unknown>;
  mismatches?: Array<{ field: string; linkedin_value: string; crm_value: string }>;
}

interface CachedValidation {
  result: ValidationResult;
  cachedAt: number;
  url: string;
}

// ============== CONSTANTS ==============
const CACHE_TTL_MS = 60 * 60 * 1000; // 1 hour
const DEBOUNCE_MS = 1000;
// Namespace the DOM id per env so prod and staging extension builds can
// coexist on the same LinkedIn page without one overlay stomping the other.
const OVERLAY_ID = `vv-linkedin-validator-overlay-${__EXT_ENV__}`;

// ============== STATE ==============
let debounceTimer: ReturnType<typeof setTimeout> | null = null;
let currentOverlay: HTMLElement | null = null;
let isExpanded = false;

// ============== PAGE DETECTION ==============

function getPageType(): 'profile' | 'company' | null {
  const path = window.location.pathname;
  if (path.match(/^\/in\/[^/]+/)) return 'profile';
  if (path.match(/^\/company\/[^/]+/)) return 'company';
  return null;
}

function getLinkedInUrl(): string {
  const path = window.location.pathname;
  // Normalize: remove trailing slash and query params
  const cleanPath = path.replace(/\/+$/, '');
  return `https://www.linkedin.com${cleanPath}`;
}

// ============== DOM EXTRACTION: PROFILE ==============

function extractProfileData(): ProfileData | null {
  try {
    // Full name — primary heading on profile
    const nameEl =
      document.querySelector('h1.text-heading-xlarge') ||
      document.querySelector('h1.inline.t-24') ||
      document.querySelector('.pv-top-card--list h1') ||
      document.querySelector('[data-anonymize="person-name"]');
    const fullName = nameEl?.textContent?.trim() || '';

    if (!fullName) {
      log.warn('Could not extract profile name from DOM');
      return null;
    }

    // Headline/title
    const headlineEl =
      document.querySelector('.text-body-medium.break-words') ||
      document.querySelector('.pv-top-card--list .text-body-medium') ||
      document.querySelector('[data-anonymize="headline"]');
    const headline = headlineEl?.textContent?.trim() || '';

    // Company name — from experience section or headline
    let companyName = '';
    const experienceCompany =
      document.querySelector('.pv-top-card--experience-list-item') ||
      document.querySelector('.experience-item .pv-entity__secondary-title');
    if (experienceCompany) {
      companyName = experienceCompany.textContent?.trim() || '';
    }

    // Location
    const locationEl =
      document.querySelector('.text-body-small.inline.t-black--light.break-words') ||
      document.querySelector('.pv-top-card--list-bullet .text-body-small') ||
      document.querySelector('[data-anonymize="location"]');
    const location = locationEl?.textContent?.trim() || '';

    // Profile photo
    const photoEl =
      document.querySelector('.pv-top-card-profile-picture__image') ||
      document.querySelector('img.profile-photo-edit__preview') ||
      document.querySelector('.pv-top-card__photo img');
    const profilePhotoUrl = (photoEl as HTMLImageElement)?.src || '';

    // About section
    const aboutEl =
      document.querySelector('#about ~ .display-flex .inline-show-more-text') ||
      document.querySelector('.pv-about__summary-text') ||
      document.querySelector('[data-anonymize="about-description"]');
    const about = aboutEl?.textContent?.trim() || '';

    return {
      fullName,
      headline,
      companyName,
      location,
      profilePhotoUrl,
      about,
      linkedinUrl: getLinkedInUrl(),
    };
  } catch (e) {
    log.error('Error extracting profile data:', e);
    return null;
  }
}

// ============== DOM EXTRACTION: COMPANY ==============

function extractCompanyData(): CompanyPageData | null {
  try {
    // Company name
    const nameEl =
      document.querySelector('h1.org-top-card-summary__title') ||
      document.querySelector('h1.top-card-layout__title') ||
      document.querySelector('.org-top-card__primary-content h1');
    const companyName = nameEl?.textContent?.trim() || '';

    if (!companyName) {
      log.warn('Could not extract company name from DOM');
      return null;
    }

    // Industry — from the company details section
    const industryEl =
      document.querySelector('.org-top-card-summary-info-list__info-item') ||
      document.querySelector('.org-top-card__primary-content .org-top-card-summary-info-list .t-normal');
    const industry = industryEl?.textContent?.trim() || '';

    // Employee count
    let employeeCount = '';
    const allInfoItems = document.querySelectorAll('.org-top-card-summary-info-list__info-item');
    for (const item of allInfoItems) {
      const text = item.textContent?.trim() || '';
      if (text.match(/\d+.*employees?/i) || text.match(/\d[\d,]+\s/)) {
        employeeCount = text;
        break;
      }
    }

    // Website — from about section or sidebar
    const websiteEl =
      document.querySelector('.org-about-company-module__company-page-url a') ||
      document.querySelector('a[data-control-name="top_card_website"]') ||
      document.querySelector('.org-top-card-primary-actions__inner a[href*="http"]');
    const website = (websiteEl as HTMLAnchorElement)?.href || '';

    // Headquarters
    let headquarters = '';
    const detailItems = document.querySelectorAll('.org-about-company-module__company-info-item');
    for (const item of detailItems) {
      const dt = item.querySelector('dt');
      const dd = item.querySelector('dd');
      if (dt?.textContent?.toLowerCase().includes('headquarter') && dd) {
        headquarters = dd.textContent?.trim() || '';
        break;
      }
    }

    // Description/tagline
    const descEl =
      document.querySelector('.org-top-card-summary__tagline') ||
      document.querySelector('.org-about-us-organization-description__text') ||
      document.querySelector('.break-words.org-top-card-summary__tagline');
    const description = descEl?.textContent?.trim() || '';

    return {
      companyName,
      industry,
      employeeCount,
      website,
      headquarters,
      description,
      linkedinUrl: getLinkedInUrl(),
    };
  } catch (e) {
    log.error('Error extracting company data:', e);
    return null;
  }
}

// ============== CACHING ==============

async function getCachedResult(url: string): Promise<ValidationResult | null> {
  try {
    const key = `validation_${url}`;
    const result = await chrome.storage.local.get([key]);
    const cached = result[key] as CachedValidation | undefined;
    if (!cached) return null;

    // Check TTL
    if (Date.now() - cached.cachedAt > CACHE_TTL_MS) {
      await chrome.storage.local.remove([key]);
      return null;
    }

    return cached.result;
  } catch {
    return null;
  }
}

async function setCachedResult(url: string, validationResult: ValidationResult): Promise<void> {
  try {
    const key = `validation_${url}`;
    const cached: CachedValidation = {
      result: validationResult,
      cachedAt: Date.now(),
      url,
    };
    await chrome.storage.local.set({ [key]: cached });
  } catch {
    // Cache write failure is not critical
  }
}

// ============== SERVICE WORKER COMMUNICATION ==============

function sendMessage(message: Record<string, unknown>): Promise<ValidationResult> {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve(response as ValidationResult);
      }
    });
  });
}

async function validateProfile(data: ProfileData): Promise<ValidationResult> {
  return sendMessage({ type: 'VALIDATE_PROFILE', data });
}

async function validateCompany(data: CompanyPageData): Promise<ValidationResult> {
  return sendMessage({ type: 'VALIDATE_COMPANY', data });
}

async function updateContact(contactId: string, fields: Record<string, unknown>): Promise<void> {
  await sendMessage({ type: 'UPDATE_CONTACT', contactId, fields });
}

async function updateCompany(companyId: string, fields: Record<string, unknown>): Promise<void> {
  await sendMessage({ type: 'UPDATE_COMPANY', companyId, fields });
}

async function addContact(data: ProfileData): Promise<void> {
  await sendMessage({ type: 'ADD_CONTACT', data });
}

// ============== OVERLAY UI — SAFE DOM CONSTRUCTION ==============

function createStyles(): string {
  return [
    `#${OVERLAY_ID} { position: fixed; bottom: 20px; right: 20px; z-index: 99999; font-family: -apple-system, system-ui, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 14px; line-height: 1.4; transition: all 0.2s ease; }`,
    `#${OVERLAY_ID} * { box-sizing: border-box; }`,
    `.vv-badge { display: flex; align-items: center; gap: 6px; padding: 8px 14px; border-radius: 20px; cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,0.15); transition: all 0.2s ease; user-select: none; border: 1px solid rgba(0,0,0,0.08); }`,
    `.vv-badge:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.2); transform: translateY(-1px); }`,
    `.vv-badge--found { background: #e8f5e9; color: #2e7d32; }`,
    `.vv-badge--not-found { background: #f5f5f5; color: #616161; }`,
    `.vv-badge--mismatch { background: #fff8e1; color: #f57f17; }`,
    `.vv-badge--loading { background: #e3f2fd; color: #1565c0; }`,
    `.vv-badge__dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }`,
    `.vv-badge--found .vv-badge__dot { background: #4caf50; }`,
    `.vv-badge--not-found .vv-badge__dot { background: #9e9e9e; }`,
    `.vv-badge--mismatch .vv-badge__dot { background: #ff9800; }`,
    `.vv-badge--loading .vv-badge__dot { background: #42a5f5; animation: vv-pulse 1.2s ease infinite; }`,
    `@keyframes vv-pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.5; transform: scale(0.8); } }`,
    `.vv-card { width: 340px; background: #fff; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.15); border: 1px solid rgba(0,0,0,0.08); overflow: hidden; }`,
    `.vv-card__header { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; border-bottom: 1px solid #f0f0f0; }`,
    `.vv-card__status { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 13px; }`,
    `.vv-card__close { cursor: pointer; color: #9e9e9e; font-size: 18px; line-height: 1; padding: 4px; border: none; background: none; border-radius: 4px; }`,
    `.vv-card__close:hover { color: #616161; background: #f5f5f5; }`,
    `.vv-card__body { padding: 14px 16px; }`,
    `.vv-card__field { display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; }`,
    `.vv-card__field-label { color: #757575; flex-shrink: 0; margin-right: 8px; }`,
    `.vv-card__field-value { color: #212121; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }`,
    `.vv-card__mismatches { margin-top: 10px; padding-top: 10px; border-top: 1px solid #f0f0f0; }`,
    `.vv-card__mismatch-title { font-size: 12px; font-weight: 600; color: #f57f17; margin-bottom: 6px; }`,
    `.vv-card__mismatch-item { font-size: 12px; color: #616161; padding: 3px 0; }`,
    `.vv-card__mismatch-field { font-weight: 500; color: #424242; }`,
    `.vv-card__actions { display: flex; gap: 8px; padding: 12px 16px; border-top: 1px solid #f0f0f0; }`,
    `.vv-btn { flex: 1; padding: 8px 12px; border-radius: 6px; border: 1px solid #e0e0e0; background: #fff; color: #424242; font-size: 12px; font-weight: 500; cursor: pointer; text-align: center; transition: all 0.15s ease; }`,
    `.vv-btn:hover { background: #f5f5f5; border-color: #bdbdbd; }`,
    `.vv-btn--primary { background: #0a66c2; color: #fff; border-color: #0a66c2; }`,
    `.vv-btn--primary:hover { background: #004182; border-color: #004182; }`,
    `.vv-enrichment-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 500; margin-left: 8px; }`,
    `.vv-enrichment-badge--high { background: #e8f5e9; color: #2e7d32; }`,
    `.vv-enrichment-badge--medium { background: #fff8e1; color: #f57f17; }`,
    `.vv-enrichment-badge--low { background: #ffebee; color: #c62828; }`,
    `.vv-env-badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; letter-spacing: 0.5px; margin-left: 6px; text-transform: uppercase; }`,
    `.vv-env-badge-staging { background: #ff6f00; color: #fff; }`,
  ].join('\n');
}

function getStatusInfo(result: ValidationResult): {
  label: string;
  badgeClass: string;
  dotColor: string;
} {
  if (!result.match) {
    return { label: 'Not in CRM', badgeClass: 'vv-badge--not-found', dotColor: '#9e9e9e' };
  }
  if (result.mismatches && result.mismatches.length > 0) {
    return { label: 'Data mismatch', badgeClass: 'vv-badge--mismatch', dotColor: '#ff9800' };
  }
  return { label: 'Found in CRM', badgeClass: 'vv-badge--found', dotColor: '#4caf50' };
}

/** Create a DOM element safely using only textContent for user data. */
function el(tag: string, attrs?: Record<string, string>, textContent?: string): HTMLElement {
  const element = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'className') {
        element.className = v;
      } else {
        element.setAttribute(k, v);
      }
    }
  }
  if (textContent !== undefined) {
    element.textContent = textContent;
  }
  return element;
}

function renderBadge(result: ValidationResult | null, loading: boolean = false): HTMLElement {
  const badge = el('div', { className: 'vv-badge' });

  if (loading) {
    badge.classList.add('vv-badge--loading');
    badge.appendChild(el('span', { className: 'vv-badge__dot' }));
    badge.appendChild(el('span', {}, 'Checking CRM...'));
    return badge;
  }

  if (!result) return badge;

  const { label, badgeClass } = getStatusInfo(result);
  badge.classList.add(badgeClass);
  badge.appendChild(el('span', { className: 'vv-badge__dot' }));
  badge.appendChild(el('span', {}, label));

  badge.addEventListener('click', () => {
    isExpanded = !isExpanded;
    renderOverlay(result);
  });

  return badge;
}

function buildFieldRow(label: string, value: string): HTMLElement {
  const row = el('div', { className: 'vv-card__field' });
  row.appendChild(el('span', { className: 'vv-card__field-label' }, label));
  row.appendChild(el('span', { className: 'vv-card__field-value' }, value));
  return row;
}

function renderCard(result: ValidationResult): HTMLElement {
  const card = el('div', { className: 'vv-card' });
  const { label, dotColor } = getStatusInfo(result);

  // Header
  const header = el('div', { className: 'vv-card__header' });
  const statusDiv = el('div', { className: 'vv-card__status' });
  const dot = el('span', { className: 'vv-badge__dot' });
  dot.style.background = dotColor;
  statusDiv.appendChild(dot);
  statusDiv.appendChild(el('span', {}, label));

  // Env badge — only show for non-prod so the user can tell which build
  // rendered this overlay when prod + staging are loaded side-by-side.
  if (__EXT_ENV__ !== 'prod') {
    statusDiv.appendChild(
      el(
        'span',
        { className: `vv-env-badge vv-env-badge-${__EXT_ENV__}` },
        `[${__EXT_ENV__.toUpperCase()}]`,
      ),
    );
  }

  // Enrichment quality badge
  if (result.enrichment_quality && result.enrichment_quality.score) {
    const score = Number(result.enrichment_quality.score);
    let cls = 'low';
    let qualityLabel = 'Low Quality';
    if (score >= 7) { cls = 'high'; qualityLabel = 'High Quality'; }
    else if (score >= 4) { cls = 'medium'; qualityLabel = 'Medium Quality'; }
    statusDiv.appendChild(el('span', { className: `vv-enrichment-badge vv-enrichment-badge--${cls}` }, qualityLabel));
  }

  header.appendChild(statusDiv);

  const closeBtn = el('button', { className: 'vv-card__close', title: 'Collapse' }, '\u00d7');
  closeBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    isExpanded = false;
    renderOverlay(result);
  });
  header.appendChild(closeBtn);
  card.appendChild(header);

  // Body
  const body = el('div', { className: 'vv-card__body' });

  if (result.match && result.contact) {
    const c = result.contact;
    const fields: [string, unknown][] = [
      ['Name', c.full_name || c.name],
      ['Title', c.job_title],
      ['Company', c.company_name],
      ['Email', c.email],
      ['Score', c.contact_score],
      ['ICP Fit', c.icp_fit],
    ];
    for (const [fieldLabel, fieldValue] of fields) {
      const v = String(fieldValue || '');
      if (v) body.appendChild(buildFieldRow(fieldLabel, v));
    }
  } else if (result.match && result.company) {
    const c = result.company;
    const fields: [string, unknown][] = [
      ['Name', c.name],
      ['Industry', c.industry],
      ['Status', c.status],
      ['Tier', c.tier],
      ['Size', c.company_size],
      ['Country', c.hq_country],
    ];
    for (const [fieldLabel, fieldValue] of fields) {
      const v = String(fieldValue || '');
      if (v) body.appendChild(buildFieldRow(fieldLabel, v));
    }
  } else {
    const msg = el('div', {}, 'Not found in your CRM database.');
    msg.style.color = '#757575';
    msg.style.textAlign = 'center';
    msg.style.padding = '10px 0';
    body.appendChild(msg);
  }

  // Mismatches section
  if (result.mismatches && result.mismatches.length > 0) {
    const mismatchesDiv = el('div', { className: 'vv-card__mismatches' });
    mismatchesDiv.appendChild(el('div', { className: 'vv-card__mismatch-title' }, 'Data differences detected'));
    for (const m of result.mismatches) {
      const itemDiv = el('div', { className: 'vv-card__mismatch-item' });
      const fieldSpan = el('span', { className: 'vv-card__mismatch-field' }, m.field + ': ');
      itemDiv.appendChild(fieldSpan);
      itemDiv.appendChild(document.createTextNode(`LinkedIn: "${m.linkedin_value}" vs CRM: "${m.crm_value}"`));
      mismatchesDiv.appendChild(itemDiv);
    }
    body.appendChild(mismatchesDiv);
  }

  card.appendChild(body);

  // Action buttons
  const actions = el('div', { className: 'vv-card__actions' });

  if (result.match) {
    if (result.mismatches && result.mismatches.length > 0) {
      const updateBtn = el('button', { className: 'vv-btn vv-btn--primary' }, 'Update CRM');
      updateBtn.addEventListener('click', handleUpdateCrm);
      actions.appendChild(updateBtn);
    }
    const dismissBtn = el('button', { className: 'vv-btn' }, 'Dismiss');
    dismissBtn.addEventListener('click', handleDismiss);
    actions.appendChild(dismissBtn);
  } else {
    const addBtn = el('button', { className: 'vv-btn vv-btn--primary' }, 'Add to CRM');
    addBtn.addEventListener('click', handleAddToCrm);
    actions.appendChild(addBtn);
    const dismissBtn = el('button', { className: 'vv-btn' }, 'Dismiss');
    dismissBtn.addEventListener('click', handleDismiss);
    actions.appendChild(dismissBtn);
  }

  card.appendChild(actions);
  return card;
}

function renderOverlay(result: ValidationResult | null, loading: boolean = false): void {
  removeOverlay();

  const container = el('div', { id: OVERLAY_ID });

  const style = document.createElement('style');
  style.textContent = createStyles();
  container.appendChild(style);

  if (isExpanded && result) {
    container.appendChild(renderCard(result));
  } else {
    container.appendChild(renderBadge(result, loading));
  }

  document.body.appendChild(container);
  currentOverlay = container;
}

function removeOverlay(): void {
  const existing = document.getElementById(OVERLAY_ID);
  if (existing) existing.remove();
  currentOverlay = null;
}

// ============== ACTION HANDLERS ==============

let lastValidationResult: ValidationResult | null = null;
let lastExtractedProfile: ProfileData | null = null;
let lastExtractedCompany: CompanyPageData | null = null;

async function handleUpdateCrm(): Promise<void> {
  if (!lastValidationResult?.match) return;

  try {
    const pageType = getPageType();
    if (pageType === 'profile' && lastValidationResult.contact && lastExtractedProfile) {
      const contactId = String(lastValidationResult.contact.id);
      const fields: Record<string, unknown> = {};
      if (lastExtractedProfile.headline) fields.job_title = lastExtractedProfile.headline;
      if (lastExtractedProfile.location) fields.location = lastExtractedProfile.location;
      if (lastExtractedProfile.profilePhotoUrl) fields.profile_photo_url = lastExtractedProfile.profilePhotoUrl;
      await updateContact(contactId, fields);
      log.success('Contact updated in CRM');
    } else if (pageType === 'company' && lastValidationResult.company && lastExtractedCompany) {
      const companyId = String(lastValidationResult.company.id);
      const fields: Record<string, unknown> = {};
      if (lastExtractedCompany.industry) fields.industry = lastExtractedCompany.industry;
      if (lastExtractedCompany.headquarters) fields.hq_city = lastExtractedCompany.headquarters;
      if (lastExtractedCompany.website) fields.domain = lastExtractedCompany.website;
      await updateCompany(companyId, fields);
      log.success('Company updated in CRM');
    }

    // Clear cache and re-validate
    const url = getLinkedInUrl();
    await chrome.storage.local.remove([`validation_${url}`]);
    isExpanded = false;
    runValidation();
  } catch (e) {
    log.error('Failed to update CRM:', e);
  }
}

async function handleAddToCrm(): Promise<void> {
  if (!lastExtractedProfile) return;

  try {
    await addContact(lastExtractedProfile);
    log.success('Contact added to CRM');

    const url = getLinkedInUrl();
    await chrome.storage.local.remove([`validation_${url}`]);
    isExpanded = false;
    runValidation();
  } catch (e) {
    log.error('Failed to add to CRM:', e);
  }
}

function handleDismiss(): void {
  isExpanded = false;
  removeOverlay();
}

// ============== MAIN VALIDATION FLOW ==============

async function runValidation(): Promise<void> {
  const pageType = getPageType();
  if (!pageType) return;

  const url = getLinkedInUrl();
  log.info(`Validating ${pageType} page: ${url}`);

  // Check cache first
  const cached = await getCachedResult(url);
  if (cached) {
    log.debug('Using cached result');
    lastValidationResult = cached;
    renderOverlay(cached);
    return;
  }

  // Show loading state
  renderOverlay(null, true);

  try {
    let result: ValidationResult;

    if (pageType === 'profile') {
      const profileData = extractProfileData();
      if (!profileData) {
        log.warn('Could not extract profile data, aborting validation');
        removeOverlay();
        return;
      }
      lastExtractedProfile = profileData;
      lastExtractedCompany = null;
      result = await validateProfile(profileData);
    } else {
      const companyData = extractCompanyData();
      if (!companyData) {
        log.warn('Could not extract company data, aborting validation');
        removeOverlay();
        return;
      }
      lastExtractedCompany = companyData;
      lastExtractedProfile = null;
      result = await validateCompany(companyData);
    }

    lastValidationResult = result;
    await setCachedResult(url, result);
    renderOverlay(result);
    log.success(`Validation complete: match=${result.match}, mismatches=${result.mismatches?.length || 0}`);
  } catch (e) {
    log.error('Validation failed:', e);
    removeOverlay();
  }
}

function debouncedValidation(): void {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    runValidation();
  }, DEBOUNCE_MS);
}

// ============== URL CHANGE DETECTION (SPA) ==============

let lastUrl = window.location.href;

function checkUrlChange(): void {
  const currentUrl = window.location.href;
  if (currentUrl !== lastUrl) {
    lastUrl = currentUrl;
    log.debug('URL changed, re-validating...');
    isExpanded = false;
    debouncedValidation();
  }
}

// ============== INITIALIZATION ==============

function init(): void {
  const pageType = getPageType();
  if (!pageType) {
    log.debug('Not a profile or company page, skipping');
    return;
  }

  log.info(`LinkedIn Validator initialized on ${pageType} page`);

  // Run initial validation after page settles
  debouncedValidation();

  // Watch for SPA navigation (LinkedIn is a SPA)
  const observer = new MutationObserver(() => {
    checkUrlChange();
  });
  observer.observe(document.body, { childList: true, subtree: true });

  // Also check on popstate (browser back/forward)
  window.addEventListener('popstate', () => {
    checkUrlChange();
  });
}

// Suppress unused variable warnings — these are used by event handlers
void currentOverlay;

// Start when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
