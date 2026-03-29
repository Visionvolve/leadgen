/**
 * Extension service worker (background script).
 *
 * Handles:
 * - Lead upload relay from content scripts to API
 * - Activity event batching and periodic sync
 * - Multi-page orchestration for Sales Navigator pagination
 * - Scheduled activity sync via chrome.alarms
 *
 * Ported from ~/git/linkedin-lead-uploader/background.js
 */

import { uploadLeads, uploadActivities, reportLinkedInIdentity } from '../common/api-client';
import { getAuthState, storeAuthState } from '../common/auth';
import { config, jitter } from '../common/config';
import type {
  Lead,
  ActivityEvent,
  MultiPageProcess,
  ActivitySyncSettings,
  PageExtractionResult,
  AuthState,
  ImportSettings,
} from '../common/types';

// ============== LOGGING ==============
const LOG_PREFIX = '[VV Service Worker]';

const log = {
  info: (msg: string, ...args: unknown[]) => console.log(`${LOG_PREFIX} ${msg}`, ...args),
  success: (msg: string, ...args: unknown[]) => console.log(`${LOG_PREFIX} ${msg}`, ...args),
  warn: (msg: string, ...args: unknown[]) => console.warn(`${LOG_PREFIX} ${msg}`, ...args),
  error: (msg: string, ...args: unknown[]) => console.error(`${LOG_PREFIX} ${msg}`, ...args),
  debug: (msg: string, ...args: unknown[]) => console.debug(`${LOG_PREFIX} ${msg}`, ...args),
};

// ============== ACTIVITY BUFFER ==============
let activityBuffer: ActivityEvent[] = [];

// Sync lock to prevent multiple simultaneous syncs
let isSyncing = false;

// Tab-triggered sync throttling
let lastLinkedInTabTime = 0;

// ============== SETTINGS ==============

async function getActivitySettings(): Promise<ActivitySyncSettings> {
  const result = await chrome.storage.local.get(['activitySettings']);
  return (
    (result.activitySettings as ActivitySyncSettings) || {
      lastSyncTime: config.defaultSyncDate,
      syncEnabled: true,
    }
  );
}

async function saveActivitySettings(
  settings: Partial<ActivitySyncSettings>,
): Promise<void> {
  const currentSettings = await getActivitySettings();
  await chrome.storage.local.set({
    activitySettings: { ...currentSettings, ...settings },
  });
}

// ============== LEAD UPLOAD ==============

async function handleLeadUpload(
  leads: Lead[],
  source: string,
  tag: string,
): Promise<{ success: boolean; created_contacts?: number; skipped_duplicates?: number; error?: string }> {
  const maxRetries = 3;
  let lastError = '';

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const result = await uploadLeads(leads, source, tag);
      log.success(
        `Uploaded ${leads.length} leads: ${result.created_contacts} created, ${result.skipped_duplicates} skipped`,
      );

      // Accumulate upload stats in multiPageProcess for side panel display
      const { multiPageProcess } = await chrome.storage.local.get(['multiPageProcess']);
      const process = multiPageProcess as MultiPageProcess | undefined;
      if (process) {
        await chrome.storage.local.set({
          multiPageProcess: {
            ...process,
            createdContacts: (process.createdContacts || 0) + result.created_contacts,
            skippedDuplicates: (process.skippedDuplicates || 0) + result.skipped_duplicates,
          },
        });
      }

      return { success: true, created_contacts: result.created_contacts, skipped_duplicates: result.skipped_duplicates };
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
      if (attempt < maxRetries) {
        const delay = 2000 * Math.pow(2, attempt - 1); // 2s, 4s, 8s
        log.warn(`Lead upload attempt ${attempt}/${maxRetries} failed: ${lastError}. Retrying in ${delay / 1000}s...`);
        await new Promise<void>((r) => setTimeout(r, delay));
      }
    }
  }

  log.error(`Lead upload failed after ${maxRetries} attempts: ${lastError}`);
  return { success: false, error: lastError };
}

// ============== ACTIVITY SYNC ==============

async function syncActivitiesBatch(): Promise<{
  success: boolean;
  created?: number;
  skipped_duplicates?: number;
  error?: string;
}> {
  if (activityBuffer.length === 0) {
    return { success: true, created: 0, skipped_duplicates: 0 };
  }

  const batch = activityBuffer.splice(0, config.activityBatchSize);
  try {
    const result = await uploadActivities(batch);
    await chrome.storage.local.set({ last_activity_sync: Date.now() });
    log.success(
      `Synced ${batch.length} activities: ${result.created} created, ${result.skipped_duplicates} skipped`,
    );
    return { success: true, created: result.created, skipped_duplicates: result.skipped_duplicates };
  } catch (error) {
    // Put events back in buffer on failure
    activityBuffer.unshift(...batch);
    const msg = error instanceof Error ? error.message : String(error);
    log.error(`Activity sync failed: ${msg}`);
    return { success: false, error: msg };
  }
}

// ============== CONTENT-SCRIPT DRIVEN SYNC ==============

/**
 * Find a LinkedIn tab to run the content script activity sync.
 * Prefers messaging or network tabs.
 */
async function findLinkedInTab(): Promise<chrome.tabs.Tab | null> {
  const tabs = await chrome.tabs.query({ url: 'https://www.linkedin.com/*' });
  const priorityTab = tabs.find(
    (t) =>
      t.url?.includes('/messaging') || t.url?.includes('/mynetwork'),
  );
  return priorityTab || tabs[0] || null;
}

/**
 * Run the full activity sync flow:
 * 1. Find a LinkedIn tab
 * 2. Inject content script if needed
 * 3. Ask content script to scrape
 * 4. Receive events and upload to API
 */
async function runFullActivitySync(
  isManual: boolean = false,
): Promise<{
  success: boolean;
  eventCount?: number;
  error?: string;
  reason?: string;
}> {
  if (isSyncing) {
    log.info('Sync already in progress, skipping');
    return { success: false, reason: 'sync_in_progress' };
  }

  isSyncing = true;
  log.info(`Starting activity sync (manual: ${isManual})...`);

  try {
    const settings = await getActivitySettings();

    if (!settings.syncEnabled && !isManual) {
      log.info('Activity sync disabled, skipping');
      return { success: false, reason: 'disabled' };
    }

    // Find a LinkedIn tab
    const tab = await findLinkedInTab();
    if (!tab || !tab.id) {
      log.warn('No LinkedIn tab found, cannot sync');

      // If there are buffered events, try to upload those
      if (activityBuffer.length > 0) {
        log.info(`Uploading ${activityBuffer.length} buffered events...`);
        const bufferResult = await syncActivitiesBatch();
        return {
          success: bufferResult.success,
          eventCount: bufferResult.created || 0,
        };
      }

      return { success: false, reason: 'no_linkedin_tab' };
    }

    log.info(`Using tab ${tab.id}: ${tab.url}`);

    // Inject content script if needed
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ['activity-monitor.js'],
      });
    } catch {
      // Script may already be loaded
    }

    // Wait for script to load
    await new Promise<void>((r) => setTimeout(r, 500));

    // Request activity sync from content script
    const response = await new Promise<{
      success: boolean;
      events?: ActivityEvent[];
      wasPartial?: boolean;
      error?: string;
    }>((resolve) => {
      chrome.tabs.sendMessage(
        tab.id!,
        {
          action: 'runActivitySync',
          lastSyncTime: settings.lastSyncTime,
        },
        (resp) => {
          if (chrome.runtime.lastError) {
            resolve({
              success: false,
              error: chrome.runtime.lastError.message,
            });
          } else {
            resolve(resp || { success: false, error: 'No response' });
          }
        },
      );
    });

    if (!response.success) {
      log.error(`Activity sync failed: ${response.error || 'Unknown error'}`);
      return { success: false, error: response.error };
    }

    const events = response.events || [];
    const wasPartial = response.wasPartial || false;
    log.info(
      `Received ${events.length} events from content script (partial: ${wasPartial})`,
    );

    if (events.length === 0) {
      // Only advance sync time if we did a complete scan
      if (!wasPartial) {
        await saveActivitySettings({
          lastSyncTime: new Date().toISOString(),
        });
      }
      return { success: true, eventCount: 0 };
    }

    // Add to buffer and upload
    activityBuffer.push(...events);
    let totalSent = 0;

    while (activityBuffer.length > 0) {
      const result = await syncActivitiesBatch();
      if (!result.success) break;
      totalSent += result.created || 0;
    }

    // Update last sync time to newest event
    const newestTimestamp = events.reduce((newest, e) => {
      return new Date(e.timestamp) > new Date(newest) ? e.timestamp : newest;
    }, events[0].timestamp);

    if (newestTimestamp) {
      await saveActivitySettings({ lastSyncTime: newestTimestamp });
    }

    log.success(`Activity sync complete: ${totalSent} events uploaded`);
    return { success: true, eventCount: totalSent };
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    log.error(`Activity sync error: ${msg}`);
    return { success: false, error: msg };
  } finally {
    isSyncing = false;
  }
}

// ============== MULTI-PAGE ORCHESTRATION ==============

async function startMultiPageFromTab(
  tabId: number,
  processData: Partial<MultiPageProcess>,
): Promise<void> {
  log.info(`Starting multi-page extraction on tab ${tabId}`);

  const state: MultiPageProcess = {
    active: true,
    stopped: false,
    tabId,
    currentPage: processData.currentPage || 1,
    totalLeads: processData.totalLeads || 0,
    totalProfileUrls: processData.totalProfileUrls || 0,
    pagesCompleted: processData.pagesCompleted || 0,
    startTime: Date.now(),
    tag: processData.tag,
  };

  await chrome.storage.local.set({ multiPageProcess: state });

  // Start extraction on current page
  await triggerExtraction(tabId);
}

async function triggerExtraction(tabId: number): Promise<void> {
  const { multiPageProcess } = await chrome.storage.local.get([
    'multiPageProcess',
  ]);

  const process = multiPageProcess as MultiPageProcess | undefined;
  if (!process || !process.active || process.stopped) {
    log.info('Process not active, skipping extraction trigger');
    return;
  }

  // Pre-check: stop before extracting if max contacts already reached
  const { import_settings: triggerSettings } = await chrome.storage.local.get('import_settings');
  const triggerMax = (triggerSettings as ImportSettings | undefined)?.maxContacts ?? config.defaultMaxContacts;
  if (triggerMax > 0 && process.totalLeads >= triggerMax) {
    log.success(`Max contacts limit already reached (${process.totalLeads}/${triggerMax}), not starting extraction`);
    await finishMultiPage(process);
    return;
  }

  log.info(
    `Triggering extraction on tab ${tabId}, page ${process.currentPage}`,
  );

  try {
    // Inject content script
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        files: ['sales-navigator.js'],
      });
    } catch {
      // Script may already be loaded
    }

    // Wait for script to initialize
    await new Promise<void>((r) => setTimeout(r, 500));

    // Tell content script to extract, passing the tag from multi-page state
    chrome.tabs.sendMessage(
      tabId,
      { action: 'extractAndReport', isMultiPage: true, tag: process?.tag || '' },
      (response?: { success: boolean }) => {
        if (chrome.runtime.lastError) {
          log.error(
            `Failed to trigger extraction: ${chrome.runtime.lastError.message}`,
          );
          // Retry after delay
          setTimeout(() => triggerExtraction(tabId), 2000);
        } else {
          log.debug(`Extraction trigger response: ${response?.success}`);
        }
      },
    );
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    log.error(`Error triggering extraction: ${msg}`);
  }
}

async function handlePageExtractionComplete(
  tabId: number,
  result: PageExtractionResult,
): Promise<void> {
  const { multiPageProcess } = await chrome.storage.local.get([
    'multiPageProcess',
  ]);

  const process = multiPageProcess as MultiPageProcess | undefined;
  if (!process || !process.active || process.stopped) {
    log.info('Process stopped, not continuing');
    return;
  }

  // Stop multi-page process if upload failed
  if (!result.success) {
    log.error('Upload failed for page, stopping multi-page process');
    await finishMultiPage({ ...process, uploadError: 'Upload failed — check authentication' });
    return;
  }

  // Update stats
  const updatedData: MultiPageProcess = {
    ...process,
    totalLeads: process.totalLeads + (result.leadCount || 0),
    totalProfileUrls:
      (process.totalProfileUrls || 0) +
      (result.stats?.profileUrlsFound || 0),
    pagesCompleted: process.pagesCompleted + 1,
  };

  log.success(
    `Page ${process.currentPage} complete: +${result.leadCount || 0} leads`,
  );

  await chrome.storage.local.set({ multiPageProcess: updatedData });

  // Check if max contacts limit has been reached
  const { import_settings } = await chrome.storage.local.get('import_settings');
  const maxContacts = (import_settings as ImportSettings | undefined)?.maxContacts ?? config.defaultMaxContacts;
  if (maxContacts > 0 && updatedData.totalLeads >= maxContacts) {
    log.success(`Max contacts limit reached (${updatedData.totalLeads}/${maxContacts}), stopping`);
    await finishMultiPage(updatedData);
    return;
  }

  // Re-check max contacts limit before starting next page (belt-and-suspenders)
  const { import_settings: settingsRecheck } = await chrome.storage.local.get('import_settings');
  const maxContactsRecheck = (settingsRecheck as ImportSettings | undefined)?.maxContacts ?? config.defaultMaxContacts;
  if (maxContactsRecheck > 0 && updatedData.totalLeads >= maxContactsRecheck) {
    log.success(`Max contacts limit reached after re-check (${updatedData.totalLeads}/${maxContactsRecheck}), stopping`);
    await finishMultiPage(updatedData);
    return;
  }

  // Navigate to next page if available
  if (result.hasNextPage && result.nextPage) {
    const nextPageData: MultiPageProcess = {
      ...updatedData,
      currentPage: result.nextPage,
    };
    await chrome.storage.local.set({ multiPageProcess: nextPageData });

    const pageDelay = jitter(config.multiPageDelay);
    log.info(
      `Waiting ${(pageDelay / 1000).toFixed(1)}s before navigating to page ${result.nextPage}...`,
    );
    await new Promise<void>((r) => setTimeout(r, pageDelay));

    // Re-check if still active after delay
    const { multiPageProcess: current } = await chrome.storage.local.get([
      'multiPageProcess',
    ]);
    const currentProcess = current as MultiPageProcess | undefined;
    if (!currentProcess || !currentProcess.active || currentProcess.stopped) {
      log.info('Process stopped during page delay');
      return;
    }

    log.info(`Navigating to page ${result.nextPage}...`);
    chrome.tabs.sendMessage(tabId, { action: 'goToNextPage' });
    // Tab onUpdated listener will trigger extraction when page loads
  } else {
    // No more pages -- finish
    log.success('All pages processed!');
    await finishMultiPage(updatedData);
  }
}

async function finishMultiPage(data: MultiPageProcess): Promise<void> {
  const finalData: MultiPageProcess = {
    ...data,
    active: false,
    endTime: Date.now(),
  };

  await chrome.storage.local.set({ multiPageProcess: finalData });
  log.success(
    `Multi-page complete: ${data.totalLeads} leads, ${data.totalProfileUrls} URLs, ${data.pagesCompleted} pages`,
  );
}

// ============== SSO AUTH ==============

// Track SSO auth tab so we can detect the callback and close it
let ssoAuthTabId: number | null = null;

async function startSsoLogin(
  provider: 'google' | 'github',
): Promise<{ success: boolean; error?: string }> {
  const callbackUrl = `${config.apiBase}/api/auth/iam/callback`;
  const oauthUrl = `${config.iamBase}/oauth/${provider}?redirect=${encodeURIComponent(callbackUrl)}`;

  try {
    const tab = await chrome.tabs.create({ url: oauthUrl });
    if (tab.id) {
      ssoAuthTabId = tab.id;
    }
    return { success: true };
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    log.error(`SSO login failed: ${msg}`);
    return { success: false, error: msg };
  }
}

function parseSsoCallback(url: string): AuthState | null {
  try {
    const parsed = new URL(url);
    const hash = parsed.hash.substring(1); // remove leading #
    if (!hash) return null;

    const params = new URLSearchParams(hash);
    const accessToken = params.get('access_token');
    const refreshToken = params.get('refresh_token');
    const userJson = params.get('user');

    if (!accessToken || !userJson) return null;

    const user = JSON.parse(userJson) as {
      id: string;
      email: string;
      display_name?: string;
      name?: string;
      owner_id: string | null;
      roles: Record<string, string>;
    };

    const roles = user.roles || {};
    const namespaces = Object.keys(roles);

    return {
      access_token: accessToken,
      refresh_token: refreshToken || '',
      namespace: namespaces.length === 1 ? namespaces[0] : '',
      user: {
        id: user.id,
        email: user.email,
        display_name: user.display_name || user.name || '',
        owner_id: user.owner_id,
        roles,
      },
      token_stored_at: Date.now(),
    };
  } catch (error) {
    log.error(`Failed to parse SSO callback: ${error}`);
    return null;
  }
}

// ============== MESSAGE HANDLER ==============

chrome.runtime.onMessage.addListener(
  (
    message: Record<string, unknown>,
    sender: chrome.runtime.MessageSender,
    sendResponse: (response: unknown) => void,
  ): boolean | void => {
    const msgType = message.type as string;

    // Lead upload from content script
    if (msgType === 'leads_extracted') {
      handleLeadUpload(
        message.leads as Lead[],
        message.source as string,
        message.tag as string,
      ).then(sendResponse);
      return true;
    }

    // Test upload from side panel (staging debug)
    if (msgType === 'test_upload') {
      const testLeads: Lead[] = [
        { name: 'Test User Alpha', company_name: 'AlphaCorp', industry: 'Construction', linkedin_url: `https://linkedin.com/in/test-${Date.now()}-1` },
        { name: 'Test User Beta', company_name: 'BetaSoft', industry: 'Furniture and Home Furnishings Manufacturing', linkedin_url: `https://linkedin.com/in/test-${Date.now()}-2` },
        { name: 'Test User Gamma', company_name: 'GammaTech', industry: 'software_saas', linkedin_url: `https://linkedin.com/in/test-${Date.now()}-3` },
      ];
      handleLeadUpload(testLeads, 'test', message.tag as string || 'test-upload').then(sendResponse);
      return true;
    }

    // Activity events from content script
    if (msgType === 'activities_scraped') {
      const events = message.events as ActivityEvent[];
      activityBuffer.push(...events);
      sendResponse({ success: true, buffered: activityBuffer.length });
      return false;
    }

    // Manual activity sync (from popup)
    if (msgType === 'sync_activities') {
      runFullActivitySync(true).then((result) =>
        sendResponse({
          success: result.success,
          created: result.eventCount || 0,
          error: result.error,
        }),
      );
      return true;
    }

    // Get auth state (content scripts can request this)
    if (msgType === 'get_auth_state') {
      getAuthState().then(sendResponse);
      return true;
    }

    // Multi-page orchestration
    if (msgType === 'start_multi_page') {
      const tabId =
        (message.tabId as number) || sender.tab?.id || 0;
      startMultiPageFromTab(
        tabId,
        message.processData as Partial<MultiPageProcess>,
      );
      sendResponse({ success: true });
      return true;
    }

    if (msgType === 'page_extraction_complete') {
      handlePageExtractionComplete(
        message.tabId as number,
        message.result as PageExtractionResult,
      );
      sendResponse({ success: true });
      return true;
    }

    if (msgType === 'stop_multi_page') {
      chrome.storage.local.get(['multiPageProcess'], (result) => {
        const process = result.multiPageProcess as
          | MultiPageProcess
          | undefined;
        if (process) {
          chrome.storage.local.set({
            multiPageProcess: { ...process, stopped: true, active: false },
          });
          // Clear extraction lock so stale content scripts stop
          chrome.storage.local.remove('extractionLock');
        }
      });
      sendResponse({ success: true });
      return true;
    }

    if (msgType === 'get_multi_page_state') {
      chrome.storage.local.get(['multiPageProcess'], (result) => {
        sendResponse(result.multiPageProcess || null);
      });
      return true;
    }

    // Start lead extraction from popup
    if (msgType === 'start_extraction') {
      const tabId = message.tabId as number;
      const tag = (message.tag as string) || '';
      const maxContacts = (message.maxContacts as number) || 0;

      // Store import settings so the multi-page process respects them
      chrome.storage.local
        .set({
          import_settings: { maxContacts } as ImportSettings,
          import_tag: tag,
        })
        .then(() => startMultiPageFromTab(tabId, { currentPage: 1, tag }))
        .then(() => {
          sendResponse({ success: true });
        });
      return true;
    }

    // SSO login (from popup)
    if (msgType === 'sso_login') {
      const provider = message.provider as 'google' | 'github';
      startSsoLogin(provider).then(sendResponse);
      return true;
    }

    // Per-lead extraction progress from content script
    if (msgType === 'extraction_progress') {
      chrome.storage.local.set({ extractionProgress: message.progress });
      sendResponse({ success: true });
      return false;
    }

    // Page info from content script (proactive push on SN page load)
    if (msgType === 'page_info') {
      chrome.storage.local.set({ pageInfo: message.pageInfo });
      sendResponse({ success: true });
      return false;
    }

    // Page info request from side panel — relay to active tab's content script
    if (msgType === 'get_page_info') {
      chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        const tab = tabs[0];
        if (!tab?.id || !tab.url?.includes('linkedin.com/sales/')) {
          sendResponse(null);
          return;
        }
        chrome.tabs.sendMessage(tab.id, { type: 'get_page_info' }, (resp) => {
          if (chrome.runtime.lastError) {
            sendResponse(null);
          } else {
            // Also store in storage for later reads
            if (resp) chrome.storage.local.set({ pageInfo: resp });
            sendResponse(resp);
          }
        });
      });
      return true;
    }

    // LinkedIn identity detected by content script
    if (msgType === 'linkedin_identity') {
      const liName = message.linkedin_name as string;
      const liUrl = message.linkedin_url as string;
      log.info(`LinkedIn identity detected: ${liName} (${liUrl})`);
      chrome.storage.local.set({ linkedinIdentity: { linkedin_name: liName, linkedin_url: liUrl } });
      // Forward to API (fire-and-forget, don't block the content script)
      reportLinkedInIdentity(liName, liUrl)
        .then((resp) => log.info(`LinkedIn identity reported to API: is_new=${resp.is_new}`))
        .catch((err) => log.warn(`Failed to report LinkedIn identity: ${err}`));
      sendResponse({ success: true });
      return false;
    }

    // LinkedIn page loaded notification
    if (msgType === 'linkedin_page_loaded') {
      log.debug(`LinkedIn page loaded: ${message.url}`);
      sendResponse({ success: true });
      return true;
    }

    // Ping
    if (message.action === 'ping') {
      sendResponse({ success: true });
      return true;
    }

    return false;
  },
);

// ============== ALARM SETUP ==============

chrome.alarms.create('activitySync', {
  periodInMinutes: config.activitySyncInterval,
});

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === 'activitySync') {
    log.info('Activity sync alarm triggered');
    const state = await getAuthState();
    if (!state) return; // Not logged in
    try {
      await runFullActivitySync(false);
    } catch {
      // Silent fail on scheduled sync -- will retry next interval
    }
  }
});

// ============== TAB UPDATE LISTENER ==============

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== 'complete') return;

  // Detect SSO callback: /auth/callback#access_token=...
  if (
    ssoAuthTabId === tabId &&
    tab.url &&
    tab.url.includes('/auth/callback#')
  ) {
    log.info('SSO callback detected, extracting tokens...');
    ssoAuthTabId = null;

    const authState = parseSsoCallback(tab.url);
    if (authState) {
      await storeAuthState(authState);
      log.success(`SSO login successful for ${authState.user.email}`);
    } else {
      log.error('Failed to extract auth data from SSO callback URL');
    }

    // Close the auth tab
    try {
      await chrome.tabs.remove(tabId);
    } catch {
      // Tab may already be closed
    }
    return;
  }

  if (!tab.url?.includes('linkedin.com')) return;

  // Tab-triggered activity sync (throttled)
  const now = Date.now();
  if (now - lastLinkedInTabTime > config.minTabSyncInterval) {
    lastLinkedInTabTime = now;
    const state = await getAuthState();
    if (state) {
      log.info('LinkedIn tab detected, triggering sync...');
      setTimeout(() => runFullActivitySync(false), 3000);
    }
  }

  // Multi-page orchestration: trigger extraction on tracked tab
  if (tab.url?.includes('linkedin.com/sales')) {
    const { multiPageProcess } = await chrome.storage.local.get([
      'multiPageProcess',
    ]);
    const process = multiPageProcess as MultiPageProcess | undefined;

    if (
      process &&
      process.active &&
      !process.stopped &&
      process.tabId === tabId
    ) {
      log.info(
        `Sales page loaded on tracked tab ${tabId}, waiting for page to stabilize...`,
      );
      setTimeout(() => triggerExtraction(tabId), jitter(config.multiPageDelay));
    }
  }
});

// ============== SIDE PANEL ==============

// Open side panel when extension icon is clicked
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

// ============== STARTUP ==============

log.success('Service worker started');
log.info(`Environment: ${config.environment}, API: ${config.apiBase}`);
