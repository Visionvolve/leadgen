import { login, logout, getAuthState, storeAuthState, getImportSettings, storeImportSettings, getImportTag, storeImportTag } from '../common/auth';
import { getStatus, fetchTags } from '../common/api-client';
import { config } from '../common/config';
import type { AuthState, ExtractionProgress, MultiPageProcess, PageInfo } from '../common/types';

// --------------- DOM Elements ---------------
const header = document.getElementById('header') as HTMLDivElement;
const loginView = document.getElementById('login-view') as HTMLDivElement;
const namespaceView = document.getElementById('namespace-view') as HTMLDivElement;
const connectedView = document.getElementById('connected-view') as HTMLDivElement;
const loginForm = document.getElementById('login-form') as HTMLFormElement;
const emailInput = document.getElementById('email') as HTMLInputElement;
const passwordInput = document.getElementById('password') as HTMLInputElement;
const loginBtn = document.getElementById('login-btn') as HTMLButtonElement;
const loginError = document.getElementById('login-error') as HTMLDivElement;
const envBadge = document.getElementById('env-badge') as HTMLSpanElement;
const namespaceSelect = document.getElementById('namespace-select') as HTMLSelectElement;
const namespaceConfirm = document.getElementById('namespace-confirm') as HTMLButtonElement;
const userEmail = document.getElementById('user-email') as HTMLSpanElement;
const leadCount = document.getElementById('lead-count') as HTMLDivElement;
const activityCount = document.getElementById('activity-count') as HTMLDivElement;
const syncBtn = document.getElementById('sync-btn') as HTMLButtonElement;
const logoutBtn = document.getElementById('logout-btn') as HTMLButtonElement;
const syncStatus = document.getElementById('sync-status') as HTMLDivElement;
const googleSsoBtn = document.getElementById('google-sso-btn') as HTMLButtonElement;
const githubSsoBtn = document.getElementById('github-sso-btn') as HTMLButtonElement;
const maxContactsSelect = document.getElementById('max-contacts') as HTMLSelectElement;
const namespaceSwitcher = document.getElementById('namespace-switcher') as HTMLDivElement;
const namespaceSwitch = document.getElementById('namespace-switch') as HTMLSelectElement;
const importTagInput = document.getElementById('import-tag') as HTMLInputElement;
const tagSuggestions = document.getElementById('tag-suggestions') as HTMLDataListElement;
const loadLeadsBtn = document.getElementById('load-leads-btn') as HTMLButtonElement;
const stopExtractionBtn = document.getElementById('stop-extraction-btn') as HTMLButtonElement;
const extractionStatus = document.getElementById('extraction-status') as HTMLDivElement;
const tabNotice = document.getElementById('tab-notice') as HTMLDivElement;

// --------------- Import Preview Elements ---------------
const importPreview = document.getElementById('import-preview') as HTMLDivElement;
const previewPage = document.getElementById('preview-page') as HTMLSpanElement;
const previewContactsOnPage = document.getElementById('preview-contacts-on-page') as HTMLSpanElement;
const previewTotalResults = document.getElementById('preview-total-results') as HTMLSpanElement;
const previewNote = document.getElementById('preview-note') as HTMLDivElement;
const previewEstimatedLeads = document.getElementById('preview-estimated-leads') as HTMLSpanElement;
const previewExpectedTime = document.getElementById('preview-expected-time') as HTMLSpanElement;

// --------------- LinkedIn Identity Elements ---------------
const linkedinIdentityEl = document.getElementById('linkedin-identity') as HTMLDivElement;
const linkedinIdentityName = document.getElementById('linkedin-identity-name') as HTMLSpanElement;

function updateLinkedInIdentity(identity: { linkedin_name: string; linkedin_url: string } | null): void {
  if (identity && identity.linkedin_name) {
    linkedinIdentityName.textContent = `LinkedIn: ${identity.linkedin_name}`;
    linkedinIdentityEl.classList.remove('hidden');
  } else {
    linkedinIdentityEl.classList.add('hidden');
  }
}

// Load identity from storage on init
chrome.storage.local.get(['linkedinIdentity'], (result) => {
  const identity = result.linkedinIdentity as { linkedin_name: string; linkedin_url: string } | undefined;
  updateLinkedInIdentity(identity ?? null);
});

let cachedPageInfo: PageInfo | null = null;

function updateImportPreview(pageInfo: PageInfo | null): void {
  cachedPageInfo = pageInfo;
  if (!pageInfo || pageInfo.contactsOnPage === 0) {
    importPreview.classList.add('hidden');
    return;
  }

  // Don't show preview when extraction is active
  const progressVisible = !progressContainer.classList.contains('hidden');
  if (progressVisible) {
    importPreview.classList.add('hidden');
    return;
  }

  importPreview.classList.remove('hidden');

  // Current page display
  if (pageInfo.totalPages) {
    previewPage.textContent = `Page ${pageInfo.currentPage} of ~${pageInfo.totalPages}`;
  } else {
    previewPage.textContent = `Page ${pageInfo.currentPage}`;
  }

  // Contacts on current page
  previewContactsOnPage.textContent = String(pageInfo.contactsOnPage);

  // Total results
  if (pageInfo.totalResults) {
    previewTotalResults.textContent = pageInfo.totalResults.toLocaleString();
  } else {
    previewTotalResults.textContent = '--';
  }

  // Note about starting page
  if (pageInfo.currentPage > 1) {
    previewNote.textContent = `Leads from page ${pageInfo.currentPage} onward will be imported`;
    previewNote.classList.remove('hidden');
  } else {
    previewNote.classList.add('hidden');
  }

  // Estimated leads calculation
  recalcEstimatedLeads();
}

function recalcEstimatedLeads(): void {
  if (!cachedPageInfo) return;

  const contactsPerPage = 25;
  const totalPages = cachedPageInfo.totalPages;
  const currentPage = cachedPageInfo.currentPage;
  const maxContacts = parseInt(maxContactsSelect.value, 10);

  let totalRemaining: number | null = null;
  if (totalPages) {
    totalRemaining = (totalPages - currentPage + 1) * contactsPerPage;
  }

  let estimatedLeads: number | string;
  if (totalRemaining !== null) {
    if (maxContacts > 0) {
      estimatedLeads = Math.min(totalRemaining, maxContacts);
    } else {
      estimatedLeads = totalRemaining;
    }
  } else if (maxContacts > 0) {
    estimatedLeads = maxContacts;
  } else {
    estimatedLeads = '--';
  }

  previewEstimatedLeads.textContent = typeof estimatedLeads === 'number'
    ? `~${estimatedLeads}`
    : estimatedLeads;

  // Expected time: ~15 seconds per page
  if (typeof estimatedLeads === 'number') {
    const pages = Math.ceil(estimatedLeads / contactsPerPage);
    const totalSeconds = pages * 15;
    if (totalSeconds < 60) {
      previewExpectedTime.textContent = `~${totalSeconds}s for ~${estimatedLeads} leads`;
    } else {
      const mins = Math.ceil(totalSeconds / 60);
      previewExpectedTime.textContent = `~${mins} min for ~${estimatedLeads} leads`;
    }
  } else {
    previewExpectedTime.textContent = '--';
  }
}

function requestPageInfo(): void {
  chrome.runtime.sendMessage({ type: 'get_page_info' }, (resp?: PageInfo | null) => {
    if (chrome.runtime.lastError) return;
    updateImportPreview(resp ?? null);
  });
}

// --------------- Environment Badge ---------------
if (config.environment === 'staging') {
  envBadge.textContent = 'STAGING';
  envBadge.classList.remove('hidden');
  header.classList.add('staging');
}

// --------------- View Management ---------------
function showView(view: 'login' | 'namespace' | 'connected'): void {
  loginView.classList.toggle('hidden', view !== 'login');
  namespaceView.classList.toggle('hidden', view !== 'namespace');
  connectedView.classList.toggle('hidden', view !== 'connected');
}

async function showConnected(state: AuthState): Promise<void> {
  userEmail.textContent = state.user.email;
  showView('connected');

  // Load import settings
  const importSettings = await getImportSettings();
  maxContactsSelect.value = String(importSettings.maxContacts);

  // Load import tag
  const savedTag = await getImportTag();
  importTagInput.value = savedTag;

  // Fetch tag suggestions for autocomplete
  fetchTags()
    .then((tags) => {
      while (tagSuggestions.firstChild) {
        tagSuggestions.removeChild(tagSuggestions.firstChild);
      }
      for (const t of tags) {
        const opt = document.createElement('option');
        opt.value = t.name;
        tagSuggestions.appendChild(opt);
      }
    })
    .catch(() => {
      // Autocomplete not critical
    });

  // Always show namespace switcher (label for single, dropdown for multi)
  const namespaces = Object.keys(state.user.roles);
  while (namespaceSwitch.firstChild) {
    namespaceSwitch.removeChild(namespaceSwitch.firstChild);
  }
  for (const ns of namespaces) {
    const opt = document.createElement('option');
    opt.value = ns;
    opt.textContent = ns;
    if (ns === state.namespace) opt.selected = true;
    namespaceSwitch.appendChild(opt);
  }
  namespaceSwitch.disabled = namespaces.length <= 1;

  try {
    const status = await getStatus();
    leadCount.textContent = String(status.total_leads_imported);
    activityCount.textContent = String(status.total_activities_synced);
  } catch {
    leadCount.textContent = '\u2014';
    activityCount.textContent = '\u2014';
  }

  // Check current tab for Sales Navigator and request page info
  checkCurrentTab();
  requestPageInfo();
}

function showNamespacePicker(state: AuthState): void {
  // Clear existing options
  while (namespaceSelect.firstChild) {
    namespaceSelect.removeChild(namespaceSelect.firstChild);
  }
  for (const ns of Object.keys(state.user.roles)) {
    const opt = document.createElement('option');
    opt.value = ns;
    opt.textContent = ns;
    namespaceSelect.appendChild(opt);
  }
  showView('namespace');
}

// --------------- Tab Awareness ---------------
async function checkCurrentTab(): Promise<void> {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const isSalesNav = tab?.url?.includes('linkedin.com/sales/') ?? false;
    tabNotice.classList.toggle('hidden', isSalesNav);
    loadLeadsBtn.disabled = !isSalesNav;
  } catch {
    // Tab query may fail in some contexts
  }
}

// Listen for tab switches — side panel stays open across tabs
chrome.tabs.onActivated.addListener(() => {
  checkCurrentTab();
  requestPageInfo();
});

// Listen for tab URL changes (e.g. navigating within a tab)
chrome.tabs.onUpdated.addListener((_tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.active) {
    checkCurrentTab();
    // Delay page info request to allow content script to load
    setTimeout(requestPageInfo, 2000);
  }
});

// --------------- Initialization ---------------
async function init(): Promise<void> {
  const state = await getAuthState();
  if (state && state.namespace) {
    await showConnected(state);
  } else if (state && !state.namespace) {
    showNamespacePicker(state);
  } else {
    showView('login');
  }
}

// --------------- Login Handler ---------------
loginForm.addEventListener('submit', async (e: SubmitEvent) => {
  e.preventDefault();
  loginBtn.disabled = true;
  loginError.classList.add('hidden');

  try {
    const state = await login(emailInput.value, passwordInput.value);
    if (!state.namespace) {
      showNamespacePicker(state);
    } else {
      await showConnected(state);
    }
  } catch (err: unknown) {
    loginError.textContent = err instanceof Error ? err.message : 'Login failed';
    loginError.classList.remove('hidden');
  } finally {
    loginBtn.disabled = false;
  }
});

// --------------- Namespace Confirm ---------------
namespaceConfirm.addEventListener('click', async () => {
  const state = await getAuthState();
  if (!state) return;
  const updated: AuthState = { ...state, namespace: namespaceSelect.value };
  await storeAuthState(updated);
  await showConnected(updated);
});

// --------------- Namespace Switch (connected view) ---------------
namespaceSwitch.addEventListener('change', async () => {
  const state = await getAuthState();
  if (!state) return;
  const updated: AuthState = { ...state, namespace: namespaceSwitch.value };
  await storeAuthState(updated);
  await showConnected(updated);
});

// --------------- Import Tag Setting ---------------
importTagInput.addEventListener('change', async () => {
  await storeImportTag(importTagInput.value.trim());
});

// --------------- Max Contacts Setting ---------------
maxContactsSelect.addEventListener('change', async () => {
  await storeImportSettings({ maxContacts: parseInt(maxContactsSelect.value, 10) });
  recalcEstimatedLeads();
});

// --------------- Sync Button ---------------
syncBtn.addEventListener('click', () => {
  syncStatus.textContent = 'Syncing activities...';
  chrome.runtime.sendMessage(
    { type: 'sync_activities' },
    (response?: { success: boolean; created?: number; error?: string }) => {
      if (chrome.runtime.lastError) {
        syncStatus.textContent = 'Sync failed: ' + chrome.runtime.lastError.message;
        return;
      }
      if (response?.success) {
        syncStatus.textContent = `Synced: ${response.created ?? 0} new activities`;
        // Refresh stats
        getStatus()
          .then((status) => {
            leadCount.textContent = String(status.total_leads_imported);
            activityCount.textContent = String(status.total_activities_synced);
          })
          .catch(() => {});
      } else {
        syncStatus.textContent = response?.error || 'Sync failed';
      }
    },
  );
});

// --------------- Logout Button ---------------
logoutBtn.addEventListener('click', async () => {
  await logout();
  showView('login');
  syncStatus.textContent = '';
});

// --------------- Load Leads Button ---------------
let extractionPollTimer: ReturnType<typeof setInterval> | null = null;
let extractionStartTime = 0;

const progressContainer = document.getElementById('extraction-progress') as HTMLDivElement;
const progressTitle = document.getElementById('progress-title') as HTMLSpanElement;
const progressElapsed = document.getElementById('progress-elapsed') as HTMLSpanElement;
const progressBar = document.getElementById('progress-bar') as HTMLDivElement;
const progressDetail = document.getElementById('progress-detail') as HTMLDivElement;
const progressLeads = document.getElementById('progress-leads') as HTMLSpanElement;
const progressPage = document.getElementById('progress-page') as HTMLSpanElement;
const progressPagesDone = document.getElementById('progress-pages-done') as HTMLSpanElement;

function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, '0')}`;
}

function showExtractionStatus(text: string, isError = false, isSuccess = false): void {
  extractionStatus.textContent = text;
  extractionStatus.classList.remove('hidden', 'error-status', 'success-status');
  if (isError) extractionStatus.classList.add('error-status');
  if (isSuccess) extractionStatus.classList.add('success-status');
}

function hideExtractionStatus(): void {
  extractionStatus.classList.add('hidden');
}

function showProgress(show: boolean): void {
  progressContainer.classList.toggle('hidden', !show);
}

function setExtractionUI(extracting: boolean): void {
  loadLeadsBtn.classList.toggle('hidden', extracting);
  stopExtractionBtn.classList.toggle('hidden', !extracting);
}

function updateProgress(state: { active: boolean; stopped: boolean; totalLeads: number; currentPage: number; pagesCompleted: number; totalPages?: number }): void {
  const maxContacts = parseInt(maxContactsSelect.value, 10);
  const elapsed = Date.now() - extractionStartTime;
  progressElapsed.textContent = formatElapsed(elapsed);
  progressLeads.textContent = String(state.totalLeads);
  progressPage.textContent = String(state.currentPage);
  progressPagesDone.textContent = String(state.pagesCompleted);

  // Calculate progress percentage
  let pct = 0;
  if (maxContacts > 0 && state.totalLeads > 0) {
    pct = Math.min(95, (state.totalLeads / maxContacts) * 100);
  } else if (state.totalPages && state.totalPages > 0) {
    pct = Math.min(95, (state.pagesCompleted / state.totalPages) * 100);
  } else if (state.pagesCompleted > 0) {
    pct = Math.min(95, state.pagesCompleted * 25);
  }
  progressBar.style.width = `${Math.max(5, pct)}%`;

  if (state.totalLeads > 0) {
    progressDetail.textContent = `Enriching leads on page ${state.currentPage}...`;
    progressTitle.textContent = 'Extracting leads...';
  } else {
    progressDetail.textContent = 'Scanning page for leads...';
  }
}

function showCompletionProgress(totalLeads: number, pagesCompleted: number, createdContacts?: number, skippedDuplicates?: number): void {
  const elapsed = Date.now() - extractionStartTime;
  progressBar.style.width = '100%';
  progressBar.classList.remove('animated');
  progressTitle.textContent = 'Extraction complete';
  progressElapsed.textContent = formatElapsed(elapsed);

  // Show breakdown if upload stats are available
  let detail: string;
  if (createdContacts != null && skippedDuplicates != null) {
    const parts = [`${createdContacts} new`];
    if (skippedDuplicates > 0) parts.push(`${skippedDuplicates} duplicates tagged`);
    detail = `${totalLeads} leads processed (${parts.join(', ')}) from ${pagesCompleted} page${pagesCompleted !== 1 ? 's' : ''} in ${formatElapsed(elapsed)}`;
  } else {
    detail = `${totalLeads} leads imported from ${pagesCompleted} page${pagesCompleted !== 1 ? 's' : ''} in ${formatElapsed(elapsed)}`;
  }

  progressDetail.textContent = detail;
  progressLeads.textContent = String(totalLeads);
  progressPagesDone.textContent = String(pagesCompleted);
}

function updateLeadProgress(progress: ExtractionProgress): void {
  if (progressContainer.classList.contains('hidden')) return;

  const phaseName = {
    extracting: 'Scanning page...',
    enriching_profile: 'Enriching profile...',
    enriching_company: 'Enriching company data...',
    uploading: 'Uploading leads...',
    done: 'Page enrichment complete',
  }[progress.phase];

  let detail = `Lead ${progress.currentLead}/${progress.totalLeadsOnPage}`;
  if (progress.currentLeadName) {
    detail += ` \u2014 <span class="lead-name">${progress.currentLeadName}</span>`;
  }
  if (progress.phase === 'enriching_company' && progress.currentCompany) {
    detail += ` \u2014 ${progress.currentCompany}`;
  }

  progressDetail.innerHTML = detail;
  progressTitle.textContent = phaseName;

  // Show in-progress lead count (totalLeads only updates after page completes)
  progressLeads.textContent = String(progress.currentLead);

  // Bar reflects per-lead progress on the current page
  if (progress.totalLeadsOnPage > 0) {
    const pct = Math.min(95, (progress.currentLead / progress.totalLeadsOnPage) * 100);
    progressBar.style.width = `${Math.max(5, pct)}%`;
  }
}

function startExtractionPolling(): void {
  if (extractionPollTimer) return;
  if (!extractionStartTime) extractionStartTime = Date.now();
  showProgress(true);
  progressBar.classList.add('animated');

  extractionPollTimer = setInterval(() => {
    // Poll both multi-page state and per-lead extraction progress from storage
    chrome.storage.local.get(['multiPageProcess', 'extractionProgress'], (result) => {
      const state = result.multiPageProcess as MultiPageProcess | undefined;
      const leadProgress = result.extractionProgress as ExtractionProgress | undefined;

      if (!state) return;

      // Update elapsed time
      const elapsed = Date.now() - extractionStartTime;
      progressElapsed.textContent = formatElapsed(elapsed);

      if (state.active && !state.stopped) {
        setExtractionUI(true);
        hideExtractionStatus();
        updateProgress(state);

        // Overlay per-lead detail if available
        if (leadProgress) {
          updateLeadProgress(leadProgress);
        }
      } else {
        setExtractionUI(false);
        if (state.uploadError) {
          // Upload failed — show error prominently
          showExtractionStatus(`Upload failed: ${state.uploadError}`, true);
          progressBar.style.width = '100%';
          progressBar.classList.remove('animated');
          progressTitle.textContent = 'Upload failed';
          progressDetail.textContent = state.uploadError;
        } else if (state.totalLeads > 0) {
          showCompletionProgress(state.totalLeads, state.pagesCompleted, state.createdContacts, state.skippedDuplicates);
          // Show summary with new/duplicate breakdown if available
          let statusText: string;
          if (state.createdContacts != null && state.skippedDuplicates != null) {
            const parts = [`${state.createdContacts} new`];
            if (state.skippedDuplicates > 0) parts.push(`${state.skippedDuplicates} duplicates tagged`);
            statusText = `${state.totalLeads} leads (${parts.join(', ')})`;
          } else {
            statusText = `${state.totalLeads} leads imported from ${state.pagesCompleted} pages`;
          }
          showExtractionStatus(statusText, false, true);
        }
        stopExtractionPolling();
        getStatus()
          .then((status) => {
            leadCount.textContent = String(status.total_leads_imported);
            activityCount.textContent = String(status.total_activities_synced);
          })
          .catch(() => {});
      }
    });
  }, 500);
}

function stopExtractionPolling(): void {
  if (extractionPollTimer) {
    clearInterval(extractionPollTimer);
    extractionPollTimer = null;
  }
}

loadLeadsBtn.addEventListener('click', async () => {
  // Check if current tab is Sales Navigator
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url?.includes('linkedin.com/sales/')) {
    showExtractionStatus('Navigate to LinkedIn Sales Navigator first', true);
    return;
  }

  loadLeadsBtn.disabled = true;
  hideExtractionStatus();

  const tag = importTagInput.value.trim();
  const maxContacts = parseInt(maxContactsSelect.value, 10);

  chrome.runtime.sendMessage(
    { type: 'start_extraction', tabId: tab.id, tag, maxContacts },
    (response?: { success: boolean; error?: string }) => {
      loadLeadsBtn.disabled = false;
      if (chrome.runtime.lastError) {
        showExtractionStatus('Failed: ' + chrome.runtime.lastError.message, true);
        return;
      }
      if (response?.success) {
        extractionStartTime = Date.now();
        setExtractionUI(true);
        hideExtractionStatus();
        importPreview.classList.add('hidden');
        showProgress(true);
        progressBar.style.width = '5%';
        progressBar.classList.add('animated');
        progressTitle.textContent = 'Extracting leads...';
        progressDetail.textContent = 'Scanning page for leads...';
        progressElapsed.textContent = '0:00';
        progressLeads.textContent = '0';
        progressPage.textContent = '1';
        progressPagesDone.textContent = '0';
        startExtractionPolling();
      } else {
        showExtractionStatus(response?.error || 'Failed to start extraction', true);
      }
    },
  );
});

stopExtractionBtn.addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'stop_multi_page' }, () => {
    setExtractionUI(false);
    showProgress(false);
    showExtractionStatus('Extraction stopped');
    stopExtractionPolling();
  });
});

// Check if extraction is already running on panel open
chrome.storage.local.get(['multiPageProcess', 'extractionProgress'], (result) => {
  const state = result.multiPageProcess as MultiPageProcess | undefined;
  const leadProgress = result.extractionProgress as ExtractionProgress | undefined;

  if (!state) return;
  if (state.active && !state.stopped) {
    extractionStartTime = state.startTime || Date.now();
    setExtractionUI(true);
    hideExtractionStatus();
    showProgress(true);
    progressBar.classList.add('animated');
    updateProgress(state);

    // Show per-lead detail if recent
    if (leadProgress && leadProgress.updatedAt > Date.now() - 10000) {
      updateLeadProgress(leadProgress);
    }

    startExtractionPolling();
  }
});

// --------------- SSO Buttons ---------------
function handleSsoClick(provider: 'google' | 'github'): void {
  googleSsoBtn.disabled = true;
  githubSsoBtn.disabled = true;
  loginError.classList.add('hidden');

  chrome.runtime.sendMessage(
    { type: 'sso_login', provider },
    (response?: { success: boolean; error?: string }) => {
      if (chrome.runtime.lastError || !response?.success) {
        loginError.textContent = response?.error || chrome.runtime.lastError?.message || 'SSO failed';
        loginError.classList.remove('hidden');
        googleSsoBtn.disabled = false;
        githubSsoBtn.disabled = false;
      }
      // On success, the service worker will store auth state.
      // We listen for storage changes to update the UI.
    },
  );
}

googleSsoBtn.addEventListener('click', () => handleSsoClick('google'));
githubSsoBtn.addEventListener('click', () => handleSsoClick('github'));

// Listen for auth state and extraction progress changes
chrome.storage.onChanged.addListener((changes) => {
  if (changes.auth_state?.newValue) {
    const state = changes.auth_state.newValue as AuthState;
    if (state.access_token) {
      googleSsoBtn.disabled = false;
      githubSsoBtn.disabled = false;
      if (!state.namespace) {
        showNamespacePicker(state);
      } else {
        showConnected(state);
      }
    }
  }

  // Per-lead extraction progress from content script (via service worker → storage)
  if (changes.extractionProgress?.newValue) {
    const progress = changes.extractionProgress.newValue as ExtractionProgress;
    updateLeadProgress(progress);
  }

  // Page info from content script (proactive push on SN page load)
  if (changes.pageInfo?.newValue) {
    updateImportPreview(changes.pageInfo.newValue as PageInfo);
  }

  // LinkedIn identity change (account switch detected)
  if (changes.linkedinIdentity?.newValue) {
    updateLinkedInIdentity(changes.linkedinIdentity.newValue as { linkedin_name: string; linkedin_url: string });
  }
});

// --------------- Test Upload (staging only) ---------------
if (config.environment === 'staging') {
  const testSection = document.getElementById('test-upload-section') as HTMLDivElement;
  const testBtn = document.getElementById('test-upload-btn') as HTMLButtonElement;
  const testStatus = document.getElementById('test-upload-status') as HTMLDivElement;
  testSection.classList.remove('hidden');

  testBtn.addEventListener('click', () => {
    testBtn.disabled = true;
    testStatus.textContent = 'Uploading 3 mock leads...';
    testStatus.style.color = '#9896a6';

    const tag = importTagInput.value.trim() || 'test-upload';

    chrome.runtime.sendMessage(
      { type: 'test_upload', tag },
      (response?: { success: boolean; created_contacts?: number; skipped_duplicates?: number; error?: string }) => {
        testBtn.disabled = false;
        if (chrome.runtime.lastError) {
          testStatus.textContent = `Error: ${chrome.runtime.lastError.message}`;
          testStatus.style.color = '#ff4d6a';
        } else if (response?.success) {
          testStatus.textContent = `OK: ${response.created_contacts} created, ${response.skipped_duplicates} duplicates`;
          testStatus.style.color = '#00d68f';
          // Refresh stats
          getStatus().then((status) => {
            leadCount.textContent = String(status.total_leads_imported);
          }).catch(() => {});
        } else {
          testStatus.textContent = `Failed: ${response?.error || 'Unknown'}`;
          testStatus.style.color = '#ff4d6a';
        }
      },
    );
  });
}

// --------------- Start ---------------
init();
