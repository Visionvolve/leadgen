import { login, logout, getAuthState, storeAuthState, getImportSettings, storeImportSettings, getImportTag, storeImportTag } from '../common/auth';
import { getStatus, fetchTags } from '../common/api-client';
import { config } from '../common/config';
import type { AuthState } from '../common/types';

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

function showExtractionStatus(text: string, isError = false): void {
  extractionStatus.textContent = text;
  extractionStatus.classList.remove('hidden', 'error-status');
  if (isError) extractionStatus.classList.add('error-status');
}

function hideExtractionStatus(): void {
  extractionStatus.classList.add('hidden');
}

function setExtractionUI(extracting: boolean): void {
  loadLeadsBtn.classList.toggle('hidden', extracting);
  stopExtractionBtn.classList.toggle('hidden', !extracting);
}

function startExtractionPolling(): void {
  if (extractionPollTimer) return;
  extractionPollTimer = setInterval(() => {
    chrome.runtime.sendMessage({ type: 'get_multi_page_state' }, (state) => {
      if (chrome.runtime.lastError || !state) return;

      if (state.active && !state.stopped) {
        setExtractionUI(true);
        showExtractionStatus(
          `Extracting... ${state.totalLeads} leads found (page ${state.currentPage}, ${state.pagesCompleted} pages done)`,
        );
      } else {
        setExtractionUI(false);
        if (state.totalLeads > 0) {
          showExtractionStatus(
            `Extraction complete: ${state.totalLeads} leads imported from ${state.pagesCompleted} pages`,
          );
        }
        stopExtractionPolling();
        // Refresh stats
        getStatus()
          .then((status) => {
            leadCount.textContent = String(status.total_leads_imported);
            activityCount.textContent = String(status.total_activities_synced);
          })
          .catch(() => {});
      }
    });
  }, 1000);
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
        setExtractionUI(true);
        showExtractionStatus('Starting extraction...');
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
    showExtractionStatus('Extraction stopped');
    stopExtractionPolling();
  });
});

// Check if extraction is already running on popup open
chrome.runtime.sendMessage({ type: 'get_multi_page_state' }, (state) => {
  if (chrome.runtime.lastError || !state) return;
  if (state.active && !state.stopped) {
    setExtractionUI(true);
    showExtractionStatus(
      `Extracting... ${state.totalLeads} leads found (page ${state.currentPage})`,
    );
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

// Listen for auth state changes (e.g., from SSO completing in background)
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
});

// --------------- Start ---------------
init();
