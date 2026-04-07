/**
 * Auth token management — localStorage-based JWT handling.
 * Ported from dashboard/auth.js to typed module.
 */

const TOKEN_KEY = 'lg_access_token'
const REFRESH_KEY = 'lg_refresh_token'
const USER_KEY = 'lg_user'

export interface UserRoles {
  [namespace: string]: 'viewer' | 'editor' | 'admin'
}

export interface StoredUser {
  id: string
  email: string
  display_name: string
  is_super_admin: boolean
  roles: UserRoles
  iam_user_id?: string
  auth_provider?: string
}

export type Role = 'viewer' | 'editor' | 'admin'

const ROLE_HIERARCHY: Record<Role, number> = { viewer: 1, editor: 2, admin: 3 }

// ---- Token CRUD ----

export function getAccessToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY)
}

export function storeTokens(access: string, refresh?: string): void {
  localStorage.setItem(TOKEN_KEY, access)
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh)
}

export function clearTokens(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(REFRESH_KEY)
  localStorage.removeItem(USER_KEY)
}

export function getStoredUser(): StoredUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as StoredUser) : null
  } catch {
    return null
  }
}

export function storeUser(user: StoredUser): void {
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

// ---- JWT helpers ----

interface JWTPayload {
  exp?: number
  sub?: string
  [key: string]: unknown
}

function decodeJWT(token: string): JWTPayload | null {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    const payload = parts[1]!.replace(/-/g, '+').replace(/_/g, '/')
    return JSON.parse(atob(payload)) as JWTPayload
  } catch {
    return null
  }
}

export function isTokenExpired(token: string): boolean {
  const payload = decodeJWT(token)
  if (!payload?.exp) return true
  return payload.exp * 1000 < Date.now()
}

// ---- Role helpers ----

export function getUserRole(user: StoredUser | null): Role {
  if (!user) return 'viewer'
  if (user.is_super_admin) return 'admin'
  const vals = Object.values(user.roles)
  if (vals.includes('admin')) return 'admin'
  if (vals.includes('editor')) return 'editor'
  return 'viewer'
}

export function hasMinRole(userRole: Role, minRole: Role): boolean {
  return (ROLE_HIERARCHY[userRole] ?? 0) >= (ROLE_HIERARCHY[minRole] ?? 0)
}

// ---- Namespace helpers ----

export function getNamespaceFromPath(pathname: string = window.location.pathname): string | null {
  const match = pathname.match(/^\/([a-z0-9][a-z0-9_-]*)(?:\/|$)/i)
  if (!match) return null
  const slug = match[1]!.toLowerCase()
  return slug.includes('.') ? null : slug
}

const LAST_NAMESPACE_KEY = 'leadgen_last_namespace'

export function getDefaultNamespace(user: StoredUser | null): string | null {
  if (!user?.roles) return null
  const namespaces = Object.keys(user.roles)

  // Check localStorage for last-used namespace
  const stored = localStorage.getItem(LAST_NAMESPACE_KEY)

  if (namespaces.length === 0) {
    // Super admin with no tenant-scoped roles — use stored or fallback
    if (user.is_super_admin) return stored || 'visionvolve'
    return null
  }

  if (stored && namespaces.includes(stored)) return stored

  // For super admins, also check if the stored namespace exists (may not be in roles)
  if (stored && user.is_super_admin) return stored

  return namespaces[0]!
}

export function setLastNamespace(slug: string): void {
  localStorage.setItem(LAST_NAMESPACE_KEY, slug)
}
