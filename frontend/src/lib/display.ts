/**
 * Enum display/reverse maps — TypeScript port of api/display.py.
 * The API returns display-format values; these maps let us build
 * filter dropdowns and reverse-map for PATCH submissions.
 */

export const STATUS_DISPLAY: Record<string, string> = {
  new: 'New',
  enrichment_failed: 'Enrichment Failed',
  triage_passed: 'Triage: Passed',
  triage_review: 'Triage: Review',
  triage_disqualified: 'Triage: Disqualified',
  enrichment_l2_failed: 'Enrichment L2 Failed',
  enriched_l2: 'Enriched L2',
  synced: 'Synced',
  needs_review: 'Needs Review',
  enriched: 'Enriched',
  error_pushing_lemlist: 'Error pushing to Lemlist',
}

export const ENRICHMENT_STAGE_DISPLAY: Record<string, string> = {
  imported: 'Imported',
  researched: 'Researched',
  qualified: 'Qualified',
  enriched: 'Enriched',
  contacts_ready: 'Contacts Ready',
  failed: 'Failed',
  disqualified: 'Disqualified',
}

export const TIER_DISPLAY: Record<string, string> = {
  tier_1_platinum: 'Tier 1 - Platinum',
  tier_2_gold: 'Tier 2 - Gold',
  tier_3_silver: 'Tier 3 - Silver',
  tier_4_bronze: 'Tier 4 - Bronze',
  tier_5_copper: 'Tier 5 - Copper',
  deprioritize: 'Deprioritize',
}

export const MESSAGE_STATUS_DISPLAY: Record<string, string> = {
  not_started: 'not_started',
  generating: 'generating',
  pending_review: 'pending_review',
  approved: 'approved',
  sent: 'sent',
  replied: 'replied',
  no_channel: 'no_channel',
  generation_failed: 'generation_failed',
}

export const REVIEW_STATUS_DISPLAY: Record<string, string> = {
  draft: 'draft',
  approved: 'approved',
  rejected: 'rejected',
  sent: 'sent',
  delivered: 'delivered',
  replied: 'replied',
}

export const ICP_FIT_DISPLAY: Record<string, string> = {
  strong_fit: 'Strong Fit',
  moderate_fit: 'Moderate Fit',
  weak_fit: 'Weak Fit',
  unknown: 'Unknown',
}

export const SENIORITY_DISPLAY: Record<string, string> = {
  c_level: 'C-Level',
  vp: 'VP',
  director: 'Director',
  manager: 'Manager',
  individual_contributor: 'Individual Contributor',
  founder: 'Founder',
  other: 'Other',
}

export const DEPARTMENT_DISPLAY: Record<string, string> = {
  executive: 'Executive',
  engineering: 'Engineering',
  product: 'Product',
  sales: 'Sales',
  marketing: 'Marketing',
  customer_success: 'Customer Success',
  finance: 'Finance',
  hr: 'HR',
  operations: 'Operations',
  other: 'Other',
}

export const BUSINESS_MODEL_DISPLAY: Record<string, string> = {
  b2b: 'B2B',
  b2c: 'B2C',
  marketplace: 'Marketplace',
  gov: 'Government',
  non_profit: 'Non-Profit',
  hybrid: 'Hybrid',
}

export const COMPANY_SIZE_DISPLAY: Record<string, string> = {
  micro: 'Micro',
  startup: 'Startup',
  smb: 'SMB',
  mid_market: 'Mid-Market',
  enterprise: 'Enterprise',
}

export const GEO_REGION_DISPLAY: Record<string, string> = {
  dach: 'DACH',
  nordics: 'Nordics',
  benelux: 'Benelux',
  cee: 'CEE',
  uk_ireland: 'UK & Ireland',
  southern_europe: 'Southern Europe',
  us: 'US',
  other: 'Other',
}

export const INDUSTRY_DISPLAY: Record<string, string> = {
  software_saas: 'Software / SaaS',
  it: 'IT',
  professional_services: 'Professional Services',
  financial_services: 'Financial Services',
  healthcare: 'Healthcare',
  manufacturing: 'Manufacturing',
  retail: 'Retail',
  media: 'Media',
  energy: 'Energy',
  telecom: 'Telecom',
  transport: 'Transport',
  construction: 'Construction',
  education: 'Education',
  public_sector: 'Public Sector',
  other: 'Other',
}

export const RELATIONSHIP_STATUS_DISPLAY: Record<string, string> = {
  prospect: 'Prospect',
  active: 'Active',
  dormant: 'Dormant',
  former: 'Former',
  partner: 'Partner',
  internal: 'Internal',
}

export const REVENUE_RANGE_DISPLAY: Record<string, string> = {
  micro: 'Micro',
  small: 'Small',
  medium: 'Medium',
  mid_market: 'Mid-Market',
  enterprise: 'Enterprise',
}

export const BUYING_STAGE_DISPLAY: Record<string, string> = {
  unaware: 'Unaware',
  problem_aware: 'Problem Aware',
  exploring_ai: 'Exploring AI',
  looking_for_partners: 'Looking for Partners',
  in_discussion: 'In Discussion',
  proposal_sent: 'Proposal Sent',
  won: 'Won',
  lost: 'Lost',
}

export const ENGAGEMENT_STATUS_DISPLAY: Record<string, string> = {
  cold: 'Cold',
  approached: 'Approached',
  prospect: 'Prospect',
  customer: 'Customer',
  churned: 'Churned',
}

export const CRM_STATUS_DISPLAY: Record<string, string> = {
  cold: 'Cold',
  scheduled_for_outreach: 'Scheduled for Outreach',
  outreach: 'Outreach',
  prospect: 'Prospect',
  customer: 'Customer',
  churn: 'Churn',
}

export const OWNERSHIP_TYPE_DISPLAY: Record<string, string> = {
  bootstrapped: 'Bootstrapped',
  vc_backed: 'VC-Backed',
  pe_backed: 'PE-Backed',
  public: 'Public',
  family_owned: 'Family-Owned',
  state_owned: 'State-Owned',
  other: 'Other',
}

export const CONFIDENCE_LEVEL_DISPLAY: Record<string, string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
}

export const COHORT_DISPLAY: Record<string, string> = {
  a: 'A',
  b: 'B',
}

export const LINKEDIN_ACTIVITY_DISPLAY: Record<string, string> = {
  active: 'Active',
  moderate: 'Moderate',
  quiet: 'Quiet',
  unknown: 'Unknown',
}

export const CONTACT_SOURCE_DISPLAY: Record<string, string> = {
  inbound: 'Inbound',
  outbound: 'Outbound',
  referral: 'Referral',
  event: 'Event',
  social: 'Social',
  other: 'Other',
}

export const LANGUAGE_DISPLAY: Record<string, string> = {
  en: 'English',
  cs: 'Czech',
  da: 'Danish',
  de: 'German',
  es: 'Spanish',
  fi: 'Finnish',
  fr: 'French',
  it: 'Italian',
  nl: 'Dutch',
  no: 'Norwegian',
  pl: 'Polish',
  pt: 'Portuguese',
  sv: 'Swedish',
}

// --- Reverse maps (display value -> DB value) ---

function buildReverse(map: Record<string, string>): Record<string, string> {
  const rev: Record<string, string> = {}
  for (const [k, v] of Object.entries(map)) {
    rev[v] = k
  }
  return rev
}

export const STATUS_REVERSE = buildReverse(STATUS_DISPLAY)
export const TIER_REVERSE = buildReverse(TIER_DISPLAY)
export const ICP_FIT_REVERSE = buildReverse(ICP_FIT_DISPLAY)
export const MESSAGE_STATUS_REVERSE = buildReverse(MESSAGE_STATUS_DISPLAY)
export const SENIORITY_REVERSE = buildReverse(SENIORITY_DISPLAY)
export const DEPARTMENT_REVERSE = buildReverse(DEPARTMENT_DISPLAY)
export const RELATIONSHIP_STATUS_REVERSE = buildReverse(RELATIONSHIP_STATUS_DISPLAY)
export const LINKEDIN_ACTIVITY_REVERSE = buildReverse(LINKEDIN_ACTIVITY_DISPLAY)
export const CONTACT_SOURCE_REVERSE = buildReverse(CONTACT_SOURCE_DISPLAY)
export const LANGUAGE_REVERSE = buildReverse(LANGUAGE_DISPLAY)
export const BUYING_STAGE_REVERSE = buildReverse(BUYING_STAGE_DISPLAY)
export const ENGAGEMENT_STATUS_REVERSE = buildReverse(ENGAGEMENT_STATUS_DISPLAY)
export const CRM_STATUS_REVERSE = buildReverse(CRM_STATUS_DISPLAY)
export const COHORT_REVERSE = buildReverse(COHORT_DISPLAY)

/** Look up display value from a map, returning raw value as fallback. */
export function displayValue(map: Record<string, string>, v: string | null | undefined): string {
  if (!v) return ''
  return map[v] ?? v
}

/** Reverse-look up DB value from display value, returning raw value as fallback. */
export function reverseValue(map: Record<string, string>, v: string | null | undefined): string {
  if (!v) return ''
  return map[v] ?? v
}

/** Build filter options from a display map: [{ value: dbKey, label: displayVal }] */
export function filterOptions(map: Record<string, string>): { value: string; label: string }[] {
  return Object.entries(map).map(([dbVal, label]) => ({ value: dbVal, label }))
}

/** Format a phone number for display: "+420602123456" -> "+420 602 123 456" */
export function formatPhone(phone: string | null | undefined): string | null {
  if (!phone) return null
  // Strip trailing .0 (float artifact from imports)
  let s = phone.replace(/\.0+$/, '')
  // Czech numbers: +420 XXX XXX XXX
  const czMatch = s.match(/^\+420(\d{3})(\d{3})(\d{3})$/)
  if (czMatch) return `+420 ${czMatch[1]} ${czMatch[2]} ${czMatch[3]}`
  // Generic international: space after country code, then groups of 3
  const intlMatch = s.match(/^\+(\d{1,3})(\d+)$/)
  if (intlMatch) {
    const rest = intlMatch[2]
    const groups = rest.match(/.{1,3}/g) || []
    return `+${intlMatch[1]} ${groups.join(' ')}`
  }
  return s
}
