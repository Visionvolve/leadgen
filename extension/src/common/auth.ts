import type { AuthState, ImportSettings } from './types';
import { config } from './config';

const STORAGE_KEY = 'auth_state';
const IMPORT_SETTINGS_KEY = 'import_settings';
const IMPORT_TAG_KEY = 'import_tag';

/** Retrieve stored auth state from chrome.storage.local. */
export async function getAuthState(): Promise<AuthState | null> {
  const result = await chrome.storage.local.get(STORAGE_KEY);
  return (result[STORAGE_KEY] as AuthState) ?? null;
}

/** Persist auth state to chrome.storage.local. */
export async function storeAuthState(state: AuthState): Promise<void> {
  await chrome.storage.local.set({ [STORAGE_KEY]: state });
}

/** Remove auth state from storage (logout). */
export async function clearAuthState(): Promise<void> {
  await chrome.storage.local.remove(STORAGE_KEY);
}

/**
 * Check if a JWT token is expired (or about to expire).
 * Returns true if the token should be refreshed.
 */
export function isTokenExpired(token: string): boolean {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return true;
    const payload = JSON.parse(atob(parts[1])) as { exp?: number };
    if (!payload.exp) return true;
    const expiresAt = payload.exp * 1000;
    return Date.now() > expiresAt - config.tokenRefreshBuffer;
  } catch {
    return true;
  }
}

/**
 * Log in with email/password against the leadgen API.
 * Stores auth state on success and returns it.
 */
export async function login(
  email: string,
  password: string,
): Promise<AuthState> {
  const resp = await fetch(`${config.apiBase}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ error: 'Login failed' })) as { error?: string };
    throw new Error(err.error || `Login failed (${resp.status})`);
  }

  const data = await resp.json() as {
    access_token: string;
    refresh_token: string;
    user: {
      id: string;
      email: string;
      display_name: string;
      owner_id: string | null;
      roles: Record<string, string>;
    };
  };

  const roles = data.user.roles || {};
  const namespaces = Object.keys(roles);

  // Auto-select namespace when only one is available
  const namespace = namespaces.length === 1 ? namespaces[0] : '';

  const state: AuthState = {
    access_token: data.access_token,
    refresh_token: data.refresh_token,
    namespace,
    user: {
      id: data.user.id,
      email: data.user.email,
      display_name: data.user.display_name,
      owner_id: data.user.owner_id,
      roles,
    },
    token_stored_at: Date.now(),
  };

  await storeAuthState(state);
  return state;
}

/**
 * Refresh the access token using the stored refresh token.
 * Updates storage with the new access token and returns it.
 * Clears auth state if refresh fails (session expired).
 */
export async function refreshToken(): Promise<string> {
  const state = await getAuthState();
  if (!state) throw new Error('Not authenticated');

  const resp = await fetch(`${config.apiBase}/api/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: state.refresh_token }),
  });

  if (!resp.ok) {
    await clearAuthState();
    throw new Error('Session expired -- please log in again');
  }

  const data = await resp.json() as { access_token: string };
  const updated: AuthState = {
    ...state,
    access_token: data.access_token,
    token_stored_at: Date.now(),
  };
  await storeAuthState(updated);
  return data.access_token;
}

/** Clear auth state (logout). */
export async function logout(): Promise<void> {
  await clearAuthState();
}

/** Retrieve import settings from chrome.storage.local. */
export async function getImportSettings(): Promise<ImportSettings> {
  const result = await chrome.storage.local.get(IMPORT_SETTINGS_KEY);
  return (result[IMPORT_SETTINGS_KEY] as ImportSettings) ?? { maxContacts: config.defaultMaxContacts };
}

/** Persist import settings to chrome.storage.local. */
export async function storeImportSettings(settings: ImportSettings): Promise<void> {
  await chrome.storage.local.set({ [IMPORT_SETTINGS_KEY]: settings });
}

/** Retrieve the user-chosen import tag from chrome.storage.local. */
export async function getImportTag(): Promise<string> {
  const result = await chrome.storage.local.get(IMPORT_TAG_KEY);
  return (result[IMPORT_TAG_KEY] as string) ?? '';
}

/** Persist the import tag to chrome.storage.local. */
export async function storeImportTag(tag: string): Promise<void> {
  await chrome.storage.local.set({ [IMPORT_TAG_KEY]: tag });
}
