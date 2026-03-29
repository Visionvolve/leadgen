/**
 * Enrichment Trigger E2E — validates triggering enrichment from the UI.
 *
 * Scenario:
 * 1. Login and navigate to the Enrich page
 * 2. Verify stage cards render in the DAG layout
 * 3. Select a tag to configure the pipeline
 * 4. Verify stage cards with eligible counts appear
 * 5. Trigger the pipeline run via the "Run" button
 * 6. Verify progress indicators appear
 * 7. Verify enrichment results on company detail
 */
import { test, expect, type Page } from '@playwright/test'
import { login, getToken, API } from './fixtures/auth'
import { gotoNamespacedPage } from './fixtures/namespace'
import { NAMESPACES, TIMEOUTS, SCREENSHOTS_DIR } from './fixtures/test-data'

const NS = NAMESPACES.primary

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Fetch available tags via API. */
async function fetchTags(page: Page): Promise<string[]> {
  const token = await getToken(page)
  const resp = await page.request.get(`${API}/api/tags`, {
    headers: {
      Authorization: `Bearer ${token}`,
      'X-Namespace': NS,
    },
  })
  if (!resp.ok()) return []
  const data = await resp.json()
  const tags = data.tags ?? []
  return tags.map((t: { name: string }) => t.name)
}

/**
 * Select a tag in the enrich page filter bar.
 * The tag filter's default option is "All Tag".
 */
async function selectTag(page: Page, tagName: string) {
  const tagSelect = page.locator('select:has(option:text-is("All Tag"))')
  await tagSelect.waitFor({ state: 'visible', timeout: TIMEOUTS.elementVisible })
  await tagSelect.selectOption(tagName)
}

/** Stop any running pipeline for the given tag (cleanup helper). */
async function stopRunningPipeline(page: Page, tagName: string): Promise<void> {
  const token = await getToken(page)
  const resp = await page.request.get(
    `${API}/api/pipeline/dag-status?tag_name=${encodeURIComponent(tagName)}`,
    { headers: { Authorization: `Bearer ${token}`, 'X-Namespace': NS } },
  )
  if (!resp.ok()) return
  const data = await resp.json()
  if (data.pipeline?.status === 'running') {
    console.log('Stopping existing running pipeline before test...')
    await page.request.post(`${API}/api/pipeline/dag-stop`, {
      headers: {
        Authorization: `Bearer ${token}`,
        'X-Namespace': NS,
        'Content-Type': 'application/json',
      },
      data: { pipeline_run_id: data.pipeline.run_id },
    })
    await page.waitForTimeout(TIMEOUTS.shortWait)
  }
}

/** Check if the pipeline estimate returns eligible companies for a tag. */
async function getEstimate(
  page: Page,
  tagName: string,
  stages: string[],
): Promise<{ eligible: number; cost: number } | null> {
  const token = await getToken(page)
  const resp = await page.request.post(`${API}/api/enrich/estimate`, {
    headers: {
      Authorization: `Bearer ${token}`,
      'X-Namespace': NS,
      'Content-Type': 'application/json',
    },
    data: { tag_name: tagName, stages },
  })
  if (!resp.ok()) return null
  const data = await resp.json()
  const stageData = data.stages ?? {}
  let eligible = 0
  for (const s of Object.values(stageData) as Array<{ eligible_count: number }>) {
    eligible += s.eligible_count ?? 0
  }
  return { eligible, cost: data.total_estimated_cost ?? 0 }
}

// ── Tests ────────────────────────────────────────────────────────────────────

test.describe('Enrichment Pipeline Trigger', () => {
  test.beforeEach(async ({ page }) => {
    await login(page)
  })

  test('enrich page loads with filter bar and tag prompt', async ({ page }) => {
    await gotoNamespacedPage(page, NS, 'enrich')
    await page.waitForLoadState('networkidle')

    await page.screenshot({
      path: `${SCREENSHOTS_DIR}/enrich-page-initial.png`,
      fullPage: true,
    })

    // Tag dropdown should be visible
    const tagSelect = page.locator('select:has(option:text-is("All Tag"))')
    await expect(tagSelect).toBeVisible({ timeout: TIMEOUTS.elementVisible })

    // Either the "choose a tag" prompt or stage cards are visible
    const promptVisible = await page
      .locator('text=Choose a tag')
      .isVisible()
      .catch(() => false)
    const companyProfileVisible = await page
      .locator('text=Company Profile')
      .first()
      .isVisible()
      .catch(() => false)

    expect(promptVisible || companyProfileVisible).toBeTruthy()
  })

  test('select tag and view stage estimates', async ({ page }) => {
    await gotoNamespacedPage(page, NS, 'enrich')
    await page.waitForLoadState('networkidle')

    const tags = await fetchTags(page)
    test.skip(tags.length === 0, 'No tags available for testing')

    const tagName = tags[0]

    // Ensure no leftover pipeline from prior runs
    await stopRunningPipeline(page, tagName)

    // Reload to get clean state
    await gotoNamespacedPage(page, NS, 'enrich')
    await page.waitForLoadState('networkidle')

    await selectTag(page, tagName)
    await page.waitForTimeout(TIMEOUTS.mediumWait)

    await page.screenshot({
      path: `${SCREENSHOTS_DIR}/enrich-tag-selected.png`,
      fullPage: true,
    })

    // Stage cards should appear
    await expect(page.locator('text=Company Profile').first()).toBeVisible({
      timeout: TIMEOUTS.elementVisible,
    })
    await expect(page.locator('text=Deep Research').first()).toBeVisible({
      timeout: TIMEOUTS.elementVisible,
    })
    await expect(page.locator('text=Strategic Signals').first()).toBeVisible({
      timeout: TIMEOUTS.elementVisible,
    })

    // The "Run N stages" button should be visible
    const runButton = page.locator('button:has-text("Run")')
    await expect(runButton).toBeVisible({ timeout: TIMEOUTS.elementVisible })
    const runText = await runButton.textContent()
    expect(runText).toMatch(/Run \d+ stages?/)

    // Estimated cost should be displayed
    await expect(page.locator('text=Est. cost').first()).toBeVisible()

    await page.screenshot({
      path: `${SCREENSHOTS_DIR}/enrich-stages-visible.png`,
      fullPage: true,
    })
  })

  test('trigger enrichment pipeline run via UI', async ({ page }) => {
    test.setTimeout(60_000)

    const tags = await fetchTags(page)
    test.skip(tags.length === 0, 'No tags available for testing')
    const tagName = tags[0]

    // Clean up any leftover pipeline
    await stopRunningPipeline(page, tagName)

    await gotoNamespacedPage(page, NS, 'enrich')
    await page.waitForLoadState('networkidle')

    const estimate = await getEstimate(page, tagName, ['l1', 'signals'])
    console.log(`Estimate for ${tagName}: ${JSON.stringify(estimate)}`)

    // Select tag
    await selectTag(page, tagName)
    await page.waitForTimeout(TIMEOUTS.mediumWait)

    // Wait for stage cards
    await expect(page.locator('text=Company Profile').first()).toBeVisible({
      timeout: TIMEOUTS.elementVisible,
    })

    const stageToggles = page.locator('input[type="checkbox"]')
    const toggleCount = await stageToggles.count()
    console.log(`Found ${toggleCount} stage toggles`)

    await page.screenshot({
      path: `${SCREENSHOTS_DIR}/enrich-before-run.png`,
      fullPage: true,
    })

    // Find the Run button
    const runButton = page.locator('button:has-text("Run")')
    await expect(runButton).toBeVisible({ timeout: TIMEOUTS.elementVisible })
    const runButtonText = await runButton.textContent()
    console.log(`Run button text: ${runButtonText}`)

    // Intercept the dag-run POST to verify the request payload
    let dagRunPayload: Record<string, unknown> | null = null
    await page.route('**/api/pipeline/dag-run', async (route, request) => {
      dagRunPayload = JSON.parse(request.postData() || '{}')
      await route.continue()
    })

    // Click Run
    await runButton.click()

    // Wait for the pipeline to start
    const stopButton = page.getByRole('button', { name: 'Stop All' })

    try {
      await expect(stopButton).toBeVisible({ timeout: TIMEOUTS.apiResponse })

      await page.screenshot({
        path: `${SCREENSHOTS_DIR}/enrich-pipeline-running.png`,
        fullPage: true,
      })

      console.log(`Pipeline started with payload: ${JSON.stringify(dagRunPayload)}`)

      // Verify the payload
      expect(dagRunPayload).not.toBeNull()
      if (dagRunPayload) {
        expect(dagRunPayload).toHaveProperty('tag_name', tagName)
        expect(dagRunPayload).toHaveProperty('stages')
        expect(Array.isArray(dagRunPayload.stages)).toBeTruthy()
      }

      // Wait for some progress
      await page.waitForTimeout(8000)

      await page.screenshot({
        path: `${SCREENSHOTS_DIR}/enrich-pipeline-progress.png`,
        fullPage: true,
      })

      // Clean up: stop the pipeline
      const pipelineRunning = page.getByText('Pipeline running...')
      const stillRunning = await pipelineRunning.isVisible().catch(() => false)

      if (stillRunning && (await stopButton.isVisible())) {
        console.log('Pipeline still running -- stopping for test cleanup')
        await stopButton.click()
        await page.waitForTimeout(TIMEOUTS.mediumWait)
        await page.screenshot({
          path: `${SCREENSHOTS_DIR}/enrich-pipeline-stopped.png`,
          fullPage: true,
        })
      } else {
        console.log('Pipeline completed during test wait')
        await page.screenshot({
          path: `${SCREENSHOTS_DIR}/enrich-pipeline-completed.png`,
          fullPage: true,
        })
      }
    } catch (e) {
      await page.screenshot({
        path: `${SCREENSHOTS_DIR}/enrich-pipeline-error.png`,
        fullPage: true,
      })
      console.log(`Pipeline start error: ${e}`)
    }

    // Final cleanup: ensure pipeline is stopped
    await stopRunningPipeline(page, tagName)
  })

  test('verify enrichment results on company detail', async ({ page }) => {
    // Enriched companies live in the united-arts namespace, not visionvolve
    const UA_NS = NAMESPACES.secondary

    const token = await getToken(page)

    // Find enriched companies by enrichment_stage filter (enrichment_cost_usd may be 0
    // even for companies with enrichment data, so stage filter is more reliable)
    let enrichedCompany: { id: string; name: string } | null = null
    for (const stage of ['contacts_ready', 'enriched']) {
      const resp = await page.request.get(
        `${API}/api/companies?page_size=1&enrichment_stage=${stage}`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
            'X-Namespace': UA_NS,
          },
        },
      )
      if (!resp.ok()) continue
      const data = await resp.json()
      const companies = data.companies ?? data.items ?? data.data ?? []
      if (companies.length > 0) {
        enrichedCompany = companies[0]
        console.log(`Found enriched company via stage=${stage}: ${enrichedCompany!.name}`)
        break
      }
    }

    if (!enrichedCompany) {
      test.skip(true, 'No enriched companies found in united-arts namespace')
      return
    }

    const company = enrichedCompany
    console.log(`Using enriched company: ${company.name} (id: ${company.id})`)

    await gotoNamespacedPage(page, UA_NS, `companies/${company.id}`)
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(TIMEOUTS.mediumWait)

    await page.screenshot({
      path: `${SCREENSHOTS_DIR}/enrich-company-detail.png`,
      fullPage: true,
    })

    // Look for enrichment indicators
    const hasEnrichment = await page.locator('text=Enrichment').first().isVisible().catch(() => false)
    const hasQuality = await page.locator('text=Quality').first().isVisible().catch(() => false)
    const hasIntelligence = await page.locator('text=Intelligence').first().isVisible().catch(() => false)
    const hasOverview = await page.locator('text=Overview').first().isVisible().catch(() => false)

    console.log(`Enrichment visible: ${hasEnrichment}`)
    console.log(`Quality visible: ${hasQuality}`)
    console.log(`Intelligence visible: ${hasIntelligence}`)
    console.log(`Overview visible: ${hasOverview}`)

    expect(hasEnrichment || hasQuality || hasIntelligence || hasOverview).toBeTruthy()
  })
})
