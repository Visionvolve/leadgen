/** A lead extracted from Sales Navigator. */
export interface Lead {
  name: string;
  job_title?: string;
  company_name?: string;
  linkedin_url?: string;
  company_website?: string;
  revenue?: string;
  headcount?: string;
  industry?: string;
}

/** An activity event scraped from LinkedIn messaging/connections. */
export interface ActivityEvent {
  event_type: 'message_sent' | 'message_received' | 'connection_request_received' | 'connection_request_sent' | 'connection_accepted';
  timestamp: string;
  contact_linkedin_url: string | null;
  external_id: string;
  payload: {
    contact_name: string;
    message?: string | null;
    conversation_id?: string;
    message_id?: string;
    sender_id?: string | null;
    direction?: 'sent' | 'received';
    contact_headline?: string;
    invitation_id?: string;
  };
}

/** Stored auth state in chrome.storage.local. */
export interface AuthState {
  access_token: string;
  refresh_token: string;
  namespace: string;
  user: {
    id: string;
    email: string;
    display_name: string;
    owner_id: string | null;
    roles: Record<string, string>;
  };
  token_stored_at: number;
}

/** Response from POST /api/extension/leads. */
export interface UploadLeadsResponse {
  created_contacts: number;
  created_companies: number;
  skipped_duplicates: number;
}

/** Response from POST /api/extension/activities. */
export interface UploadActivitiesResponse {
  created: number;
  skipped_duplicates: number;
}

/** Response from GET /api/extension/status. */
export interface ExtensionStatus {
  connected: boolean;
  last_lead_sync: string | null;
  last_activity_sync: string | null;
  total_leads_imported: number;
  total_activities_synced: number;
}

/** Internal lead structure during extraction (before converting to Lead). */
export interface RawLeadRow {
  name: string;
  jobTitle: string;
  company: string;
  companyId: string;
  leadId: string;
  authType: string;
  authToken: string;
}

/** Enriched lead row after Sales API calls. */
export interface EnrichedLeadRow {
  name: string;
  jobTitle: string;
  company: string;
  linkedInUrl: string;
  industry: string;
  revenue: string;
  employees: string;
  website: string;
}

/** Pagination info for Sales Navigator list pages. */
export interface PaginationInfo {
  currentPage: number;
  totalPages: number | null;
  hasNextPage: boolean;
  nextPage: number | null;
}

/** Multi-page orchestration state stored in chrome.storage.local. */
export interface MultiPageProcess {
  active: boolean;
  stopped: boolean;
  tabId: number;
  currentPage: number;
  totalLeads: number;
  totalProfileUrls: number;
  pagesCompleted: number;
  startTime: number;
  endTime?: number;
  maxContacts?: number;
  /** Import tag passed from side panel, used as primary source of truth. */
  tag?: string;
  /** Cumulative count of newly created contacts across all pages. */
  createdContacts?: number;
  /** Cumulative count of duplicate contacts (tagged only) across all pages. */
  skippedDuplicates?: number;
  /** Error message if upload failed. */
  uploadError?: string;
}

/** Import settings stored in chrome.storage.local. */
export interface ImportSettings {
  maxContacts: number;
}

/** Extraction result from content script. */
export interface ExtractionResult {
  success: boolean;
  results?: EnrichedLeadRow[];
  leadCount?: number;
  error?: string;
  stats?: {
    profileUrlsFound: number;
    companyDataFound: number;
    duration: string;
  };
}

/** Messages sent between content scripts and service worker. */
export type ExtensionMessage =
  | { type: 'leads_extracted'; leads: Lead[]; source: string; tag: string }
  | { type: 'activities_scraped'; events: ActivityEvent[] }
  | { type: 'sync_activities' }
  | { type: 'get_auth_state' }
  | { type: 'extract_page' }
  | { type: 'page_extraction_complete'; tabId: number; result: PageExtractionResult }
  | { type: 'start_multi_page'; tabId: number; processData: Partial<MultiPageProcess> }
  | { type: 'stop_multi_page' }
  | { type: 'get_multi_page_state' }
  | { type: 'check_page' }
  | { type: 'go_to_next_page' }
  | { type: 'linkedin_page_loaded'; url: string }
  | { type: 'sso_login'; provider: 'google' | 'github' }
  | { type: 'extraction_progress'; progress: ExtractionProgress }
  | { type: 'get_page_info' }
  | { type: 'page_info'; pageInfo: PageInfo }
  | { type: 'linkedin_identity'; linkedin_name: string; linkedin_url: string };

/** Result reported after extracting a single page in multi-page mode. */
export interface PageExtractionResult {
  success: boolean;
  leadCount: number;
  stats?: {
    profileUrlsFound: number;
    companyDataFound: number;
    duration: string;
  };
  hasNextPage: boolean;
  nextPage: number | null;
}

/** Activity sync settings stored in chrome.storage.local. */
export interface ActivitySyncSettings {
  lastSyncTime: string;
  syncEnabled: boolean;
}

/** Page info for import preview (read from Sales Navigator DOM). */
export interface PageInfo {
  currentPage: number;
  totalResults: number | null;
  totalPages: number | null;
  contactsOnPage: number;
}

/** Per-lead extraction progress stored in chrome.storage.local. */
export interface ExtractionProgress {
  /** Current lead index being processed (1-based). */
  currentLead: number;
  /** Total leads on this page to process. */
  totalLeadsOnPage: number;
  /** Name of the lead currently being enriched. */
  currentLeadName: string;
  /** Current enrichment phase. */
  phase: 'extracting' | 'enriching_profile' | 'enriching_company' | 'uploading' | 'done';
  /** Company name being enriched (if in enriching_company phase). */
  currentCompany?: string;
  /** Timestamp of this update. */
  updatedAt: number;
}
