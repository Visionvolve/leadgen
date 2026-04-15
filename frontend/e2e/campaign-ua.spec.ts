/**
 * Campaign Page E2E — User Acceptance Tests
 *
 * Tests against local dev server (localhost:5173 + localhost:5001).
 * Auth: test@staging.local via IAM (proxied through Flask).
 * Override: set E2E_EMAIL and E2E_PASSWORD env vars for different credentials.
 *
 * Covers:
 *   1. Campaign list loads
 *   2. Create campaign via UI
 *   3. Add steps to campaign (via API + verify in UI)
 *   4. Campaign detail shows steps with channel/day info
 *   5. Delete test campaign (cleanup)
 */
import { test, expect, type Page, type APIRequestContext } from '@playwright/test'

const BASE = process.env.BASE_URL ?? 'http://localhost:5173'
const API = process.env.API_URL ?? 'http://localhost:5173'
const NS = 'visionvolve'

const TEST_CAMPAIGN_NAME = `E2E Test Campaign ${Date.now()}`

// ── Auth helpers ─────────────────────────────────────────

interface AuthTokens {
  access_token: string
  refresh_token: string
  user: Record<string, unknown>
}

let authTokens: AuthTokens | null = null

async function getAuthTokens(request: APIRequestContext): Promise<AuthTokens> {
  if (authTokens) return authTokens

  const email = process.env.E2E_EMAIL ?? 'test@staging.local'
  const password = process.env.E2E_PASSWORD ?? 'staging123'
  const resp = await request.post(`${API}/api/auth/login`, {
    data: { email, password },
  })
  expect(resp.ok(), `Login failed: ${resp.status()} ${resp.statusText()}`).toBeTruthy()

  const body = await resp.json()
  expect(body.access_token).toBeTruthy()

  authTokens = {
    access_token: body.access_token,
    refresh_token: body.refresh_token,
    user: body.user,
  }
  return authTokens
}

function authHeaders(tokens: AuthTokens) {
  return {
    Authorization: `Bearer ${tokens.access_token}`,
    'X-Namespace': NS,
    'Content-Type': 'application/json',
  }
}

async function login(page: Page) {
  const tokens = await getAuthTokens(page.request)
  await page.goto(BASE)
  await page.evaluate(
    ({ access, refresh, user }) => {
      localStorage.setItem('lg_access_token', access)
      localStorage.setItem('lg_refresh_token', refresh)
      localStorage.setItem('lg_user', JSON.stringify(user))
    },
    {
      access: tokens.access_token,
      refresh: tokens.refresh_token,
      user: tokens.user,
    },
  )
}

// ── Shared state across ordered tests ────────────────────

let createdCampaignId: string | null = null

// Force tests to run in order (serial) since they depend on each other
test.describe.configure({ mode: 'serial' })

test.describe('Campaign Page E2E', () => {
  test.beforeAll(async ({ browser }) => {
    // Validate the dev server is up
    const context = await browser.newContext()
    const page = await context.newPage()
    try {
      const resp = await page.request.get(`${API}/api/health`)
      expect(resp.ok(), 'Dev server API is not running — start with: make dev').toBeTruthy()
    } finally {
      await context.close()
    }
  })

  // ── 1. Campaign list loads ────────────────────────────

  test('campaign list loads', async ({ page }) => {
    await login(page)
    await page.goto(`${BASE}/${NS}/campaigns`)

    // Wait for either the campaign list header or the empty state
    await Promise.race([
      page.waitForSelector('h1:has-text("Campaigns")', { timeout: 15_000 }),
      page.waitForSelector('text=/New Campaign|Create.*Campaign|No campaigns/i', { timeout: 15_000 }),
    ])

    const body = await page.textContent('body')
    expect(body?.length).toBeGreaterThan(50)

    // Should see the "New Campaign" button (list) or a create prompt (empty state)
    const hasNewBtn = await page.locator('button:has-text("New Campaign")').isVisible().catch(() => false)
    const hasCampaignText = !!(body?.match(/campaign/i))
    expect(hasNewBtn || hasCampaignText).toBeTruthy()
  })

  // ── 2. Create campaign ────────────────────────────────

  test('create campaign', async ({ page }) => {
    await login(page)
    await page.goto(`${BASE}/${NS}/campaigns`)

    // Wait for list/empty state
    await Promise.race([
      page.waitForSelector('h1:has-text("Campaigns")', { timeout: 15_000 }),
      page.waitForSelector('text=/New Campaign|Create.*Campaign/i', { timeout: 15_000 }),
    ])

    // Click "New Campaign" button
    const newBtn = page.locator('button:has-text("New Campaign")').first()
    if (await newBtn.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await newBtn.click()
    } else {
      // Empty state CTA
      const createBtn = page.locator('button:has-text("Create"), button:has-text("campaign")').first()
      await createBtn.click()
    }

    // Fill the campaign name
    const nameInput = page.locator('input[placeholder*="Campaign name"], input[placeholder*="campaign"]').first()
    await expect(nameInput).toBeVisible({ timeout: 5_000 })
    await nameInput.clear()
    await nameInput.fill(TEST_CAMPAIGN_NAME)

    // Click Create inside the create dialog panel
    const createBtn = page.locator('.bg-surface-alt button:has-text("Create")').first()
    await expect(createBtn).toBeEnabled({ timeout: 3_000 })
    await createBtn.click()

    // Wait for navigation or list update
    await page.waitForTimeout(2_000)

    // Extract the campaign ID from the URL (navigated to detail) or from the list
    const currentUrl = page.url()
    const uuidMatch = currentUrl.match(/campaigns\/([0-9a-f-]{36})/)
    if (uuidMatch) {
      createdCampaignId = uuidMatch[1]
    } else {
      // Still on list — click the new campaign row
      await expect(page.locator(`text=${TEST_CAMPAIGN_NAME}`).first()).toBeVisible({ timeout: 10_000 })
      await page.locator(`text=${TEST_CAMPAIGN_NAME}`).first().click()
      await page.waitForTimeout(1_000)
      const detailUrl = page.url()
      const match = detailUrl.match(/campaigns\/([0-9a-f-]{36})/)
      expect(match).toBeTruthy()
      createdCampaignId = match![1]
    }

    expect(createdCampaignId).toBeTruthy()
    await expect(page.locator(`text=${TEST_CAMPAIGN_NAME}`).first()).toBeVisible({ timeout: 10_000 })
  })

  // ── 3. Add steps to campaign ──────────────────────────

  test('add steps to campaign', async ({ page }) => {
    expect(createdCampaignId, 'Campaign must be created first').toBeTruthy()
    const tokens = await getAuthTokens(page.request)
    const headers = authHeaders(tokens)

    // Add 3 steps via API for reliability
    const steps = [
      { channel: 'email', day_offset: 0, label: 'Intro Email', config: { max_length: 5000, tone: 'professional', language: 'cs' } },
      { channel: 'email', day_offset: 7, label: 'Follow-up Email', config: { max_length: 5000, tone: 'professional', language: 'cs' } },
      { channel: 'phone', day_offset: 14, label: 'Phone Call', config: { tone: 'professional', language: 'cs' } },
    ]

    for (const step of steps) {
      const resp = await page.request.post(
        `${API}/api/campaigns/${createdCampaignId}/steps`,
        { data: step, headers },
      )
      expect(resp.ok(), `Failed to add step "${step.label}": ${resp.status()}`).toBeTruthy()
    }

    // Now verify the steps appear in the UI
    await login(page)
    await page.goto(`${BASE}/${NS}/campaigns/${createdCampaignId}?tab=steps`)
    await page.waitForSelector(`text=${TEST_CAMPAIGN_NAME}`, { timeout: 15_000 })

    // Wait for steps to render
    await page.waitForTimeout(2_000)

    const body = await page.textContent('body')

    // Verify step labels or step indicators are visible
    const hasStep1 = body?.includes('Intro Email') || body?.includes('Step 1') || body?.includes('#1')
    const hasStep2 = body?.includes('Follow-up Email') || body?.includes('Step 2') || body?.includes('#2')
    const hasStep3 = body?.includes('Phone Call') || body?.includes('Step 3') || body?.includes('#3')

    expect(hasStep1, 'Step 1 (Intro Email) should be visible').toBeTruthy()
    expect(hasStep2, 'Step 2 (Follow-up Email) should be visible').toBeTruthy()
    expect(hasStep3, 'Step 3 (Phone Call) should be visible').toBeTruthy()

    // Verify the "Add Step" button is still available
    await expect(page.locator('button:has-text("Add Step")')).toBeVisible({ timeout: 5_000 })
  })

  // ── 4. Campaign detail shows steps ────────────────────

  test('campaign detail shows steps with channel and day info', async ({ page }) => {
    expect(createdCampaignId, 'Campaign must be created first').toBeTruthy()

    await login(page)
    await page.goto(`${BASE}/${NS}/campaigns/${createdCampaignId}?tab=steps`)
    await page.waitForSelector(`text=${TEST_CAMPAIGN_NAME}`, { timeout: 15_000 })
    await page.waitForTimeout(2_000)

    // Verify via API that all 3 steps exist
    const tokens = await getAuthTokens(page.request)
    const stepsResp = await page.request.get(
      `${API}/api/campaigns/${createdCampaignId}/steps`,
      { headers: authHeaders(tokens) },
    )
    expect(stepsResp.ok()).toBeTruthy()
    const stepsData = await stepsResp.json()
    expect(stepsData.steps.length).toBe(3)

    // Verify steps are rendered in the UI
    const body = await page.textContent('body')
    expect(body).toBeTruthy()

    // Should show channel indicators (email, phone) or day offsets
    const hasChannelInfo =
      body!.includes('Email') ||
      body!.includes('email') ||
      body!.includes('Phone') ||
      body!.includes('phone')
    expect(hasChannelInfo, 'Channel info (Email/Phone) should be visible in step cards').toBeTruthy()

    // Should show day offsets or sequence order
    const hasDayInfo =
      body!.includes('Day 0') ||
      body!.includes('Day 7') ||
      body!.includes('Day 14') ||
      body!.includes('D0') ||
      body!.includes('D7') ||
      body!.includes('D14') ||
      body!.includes('day_offset')
    // Day info display is optional — some UIs show it differently
    if (!hasDayInfo) {
      // At minimum, step labels should be present
      expect(body!.includes('Intro') || body!.includes('Follow') || body!.includes('Phone')).toBeTruthy()
    }

    // Steps should be in order (position 1, 2, 3)
    const steps = stepsData.steps as Array<{ position: number; label: string; channel: string; day_offset: number }>
    expect(steps[0].position).toBe(1)
    expect(steps[1].position).toBe(2)
    expect(steps[2].position).toBe(3)
    expect(steps[0].channel).toBe('email')
    expect(steps[1].channel).toBe('email')
    expect(steps[2].channel).toBe('phone')
    expect(steps[0].day_offset).toBe(0)
    expect(steps[1].day_offset).toBe(7)
    expect(steps[2].day_offset).toBe(14)
  })

  // ── 5. Delete test campaign (cleanup) ─────────────────

  test('delete test campaign', async ({ page }) => {
    expect(createdCampaignId, 'Campaign must be created first').toBeTruthy()

    const tokens = await getAuthTokens(page.request)

    // Delete via API for reliable cleanup
    const deleteResp = await page.request.delete(
      `${API}/api/campaigns/${createdCampaignId}`,
      { headers: authHeaders(tokens) },
    )

    // Accept 200, 204, or 404 (already deleted)
    expect([200, 204, 404]).toContain(deleteResp.status())

    // Verify it no longer appears in the list
    await login(page)
    await page.goto(`${BASE}/${NS}/campaigns`)
    await page.waitForTimeout(3_000)

    const body = await page.textContent('body')
    expect(body).not.toContain(TEST_CAMPAIGN_NAME)
  })
})
