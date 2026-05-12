import { useState, useCallback } from 'react'
import { useUpdateCompany, type CompanyDetail as CompanyDetailType } from '../../api/queries/useCompanies'
import { useToast } from '../../components/ui/Toast'
import { Badge } from '../../components/ui/Badge'
import {
  FieldGrid, Field,
  EditableSelect, EditableTextarea,
  SectionDivider, MiniTable,
} from '../../components/ui/DetailField'
import { Tabs, type TabDef } from '../../components/ui/Tabs'
import { EnrichmentTimeline } from '../../components/ui/EnrichmentTimeline'
import { CorrectiveActionButtons } from '../../components/ui/CorrectiveActionButtons'
import { RawResearchSection } from '../../components/ui/RawResearchSection'
import type { SourceInfo } from '../../components/ui/SourceTooltip'
import { ModuleSummaryCard, type ModuleField } from './ModuleSummaryCard'
import { deriveStage } from '../../lib/deriveStage'
import {
  TIER_DISPLAY, TIER_REVERSE,
  BUYING_STAGE_DISPLAY, BUYING_STAGE_REVERSE,
  ENGAGEMENT_STATUS_DISPLAY, ENGAGEMENT_STATUS_REVERSE,
  filterOptions,
} from '../../lib/display'

interface Props {
  company: CompanyDetailType
  onNavigate: (type: 'company' | 'contact', id: string) => void
}

export function CompanyDetail({ company, onNavigate }: Props) {
  const { toast } = useToast()
  const mutation = useUpdateCompany()

  const [edits, setEdits] = useState<Record<string, string>>({})
  const [cfEdits, setCfEdits] = useState<Record<string, string>>({})

  const handleFieldChange = useCallback((name: string, value: string) => {
    setEdits((prev) => ({ ...prev, [name]: value }))
  }, [])

  const handleCfChange = useCallback((name: string, value: string) => {
    setCfEdits((prev) => ({ ...prev, [name]: value }))
  }, [])

  const getEditableValue = (field: string, original: string | null | undefined) => {
    return field in edits ? edits[field] : (original ?? '')
  }

  const hasChanges = Object.keys(edits).length > 0 || Object.keys(cfEdits).length > 0

  const handleSave = async () => {
    const reverseMap: Record<string, Record<string, string>> = {
      tier: TIER_REVERSE,
      buying_stage: BUYING_STAGE_REVERSE,
      engagement_status: ENGAGEMENT_STATUS_REVERSE,
    }

    const payload: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(edits)) {
      const rev = reverseMap[key]
      payload[key] = rev ? (rev[value] ?? value) : value
    }
    if (Object.keys(cfEdits).length > 0) {
      payload.custom_fields = cfEdits
    }

    try {
      await mutation.mutateAsync({ id: company.id, data: payload })
      toast('Company updated', 'success')
      setEdits({})
      setCfEdits({})
    } catch {
      toast('Failed to save changes', 'error')
    }
  }

  const l2 = company.enrichment_l2
  const l2m = l2?.modules
  const reg = company.registry_data as Record<string, unknown> | null

  const l1Source: SourceInfo = {
    label: 'L1 Enrichment',
    timestamp: company.updated_at,
    cost: company.enrichment_cost_usd,
  }
  // l2Source reserved for future SourceTooltip on L2 fields
  const regSource: SourceInfo | undefined = reg ? {
    label: 'Registry Lookup',
    timestamp: (reg.enriched_at as string | null) ?? null,
  } : undefined

  const needsAttention = company.status && ['Needs Review', 'Enrichment Failed', 'Enrichment L2 Failed'].includes(company.status)
  const derived = company.derived_stage ?? deriveStage(company.stage_completions)

  /* ---- Tab definitions ---- */

  const tabs: TabDef[] = []

  // Overview tab
  tabs.push({
    id: 'overview',
    label: 'Overview',
    content: (
      <div className="space-y-1">
        {/* Derived stage + company links */}
        <div className="flex items-center gap-3 mb-3">
          {derived && (
            <span className="px-3 py-1 text-xs font-medium rounded-full text-white" style={{ backgroundColor: derived.color }}>
              {derived.label}
            </span>
          )}
          {company.website_url && (
            <a href={company.website_url} target="_blank" rel="noopener noreferrer" className="text-xs text-accent hover:text-accent-hover">
              Website ↗
            </a>
          )}
          {company.linkedin_url && (
            <a href={company.linkedin_url} target="_blank" rel="noopener noreferrer" className="text-xs text-accent hover:text-accent-hover">
              LinkedIn ↗
            </a>
          )}
          {company.data_quality_score != null && (
            <span className="text-xs text-text-muted">Quality: {company.data_quality_score}%</span>
          )}
          {company.last_enriched_at && (
            <span className="text-xs text-text-dim">Last enriched: {new Date(company.last_enriched_at).toLocaleDateString()}</span>
          )}
        </div>

        {/* L1 metadata: confidence, quality, QC flags */}
        {company.enrichment_l1 && (
          <div className="flex items-center gap-3 mb-2">
            {company.enrichment_l1.confidence != null && (
              <span className="text-xs text-text-muted">L1 Confidence: <span className="font-medium text-text">{(company.enrichment_l1.confidence * 100).toFixed(0)}%</span></span>
            )}
            {company.enrichment_l1.quality_score != null && (
              <span className="text-xs text-text-muted">Quality: <span className="font-medium text-text">{company.enrichment_l1.quality_score}</span></span>
            )}
            {company.enrichment_l1.qc_flags && company.enrichment_l1.qc_flags.length > 0 && (
              <div className="flex gap-1">
                {company.enrichment_l1.qc_flags.map((flag) => (
                  <span key={flag} className="px-1.5 py-0.5 text-[10px] bg-warning/10 text-warning rounded border border-warning/20">
                    {flag}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        <SectionDivider title="Classification" />
        <FieldGrid cols={3}>
          <Field label="Business Model" value={company.business_model} source={l1Source} />
          <Field label="Company Size" value={company.company_size} source={l1Source} />
          <Field label="Ownership" value={company.ownership_type} source={l1Source} />
          <Field label="Geo Region" value={company.geo_region} source={l1Source} />
          <Field label="Industry" value={company.industry} source={l1Source} />
          <Field label="Industry Category" value={company.industry_category} source={l1Source} />
          <Field label="Revenue Range" value={company.revenue_range} source={l1Source} />
          <Field label="Business Type" value={company.business_type} source={l1Source} />
        </FieldGrid>

        <SectionDivider title="CRM" />
        <FieldGrid cols={3}>
          <EditableSelect label="Tier" name="tier" value={getEditableValue('tier', company.tier)} options={filterOptions(TIER_DISPLAY)} onChange={handleFieldChange} />
          <EditableSelect label="Buying Stage" name="buying_stage" value={getEditableValue('buying_stage', company.buying_stage)} options={filterOptions(BUYING_STAGE_DISPLAY)} onChange={handleFieldChange} />
          <EditableSelect label="Engagement" name="engagement_status" value={getEditableValue('engagement_status', company.engagement_status)} options={filterOptions(ENGAGEMENT_STATUS_DISPLAY)} onChange={handleFieldChange} />
        </FieldGrid>

        <SectionDivider title="Key Metrics" />
        <FieldGrid cols={3}>
          <Field label="Triage Score" value={company.triage_score?.toFixed(1)} source={l1Source} />
          <Field label="Verified Revenue (EUR M)" value={company.verified_revenue_eur_m} source={l1Source} />
          <Field label="Verified Employees" value={company.verified_employees} source={l1Source} />
        </FieldGrid>

        <SectionDivider title="Location" />
        <FieldGrid>
          <Field label="City" value={company.hq_city} source={l1Source} />
          <Field label="Country" value={company.hq_country} source={l1Source} />
        </FieldGrid>

        <SectionDivider title="Summary & Notes" />
        <div className="space-y-3">
          <Field label="Summary" value={company.summary} className="col-span-full" source={l1Source} />
          <EditableTextarea label="Notes" name="notes" value={getEditableValue('notes', company.notes)} onChange={handleFieldChange} />
        </div>

        {company.tags.length > 0 && (
          <>
            <SectionDivider title="Tags" />
            {Object.entries(
              company.tags.reduce<Record<string, string[]>>((acc, t) => {
                ;(acc[t.category] ??= []).push(t.value)
                return acc
              }, {}),
            ).map(([cat, values]) => (
              <div key={cat} className="mb-2">
                <span className="text-xs text-text-muted">{cat}:</span>
                <div className="flex flex-wrap gap-1 mt-1">
                  {values.map((v) => (
                    <span key={v} className="px-2 py-0.5 text-xs bg-accent/10 text-accent-hover rounded border border-accent/20">
                      {v}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </>
        )}

        {company.custom_fields && Object.keys(company.custom_fields).length > 0 && (
          <>
            <SectionDivider title="Custom Fields" />
            <div className="space-y-3">
              {Object.entries(company.custom_fields).map(([key, val]) => (
                <EditableTextarea
                  key={key}
                  label={key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                  name={key}
                  value={key in cfEdits ? cfEdits[key] : (val ?? '')}
                  onChange={handleCfChange}
                  rows={2}
                />
              ))}
            </div>
          </>
        )}

        {hasChanges && (
          <div className="sticky bottom-0 bg-surface border-t border-border-solid py-3 mt-4 flex justify-end">
            <button
              onClick={handleSave}
              disabled={mutation.isPending}
              className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm font-medium rounded-md transition-colors disabled:opacity-50"
            >
              {mutation.isPending ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        )}
      </div>
    ),
  })

  // Intelligence tab — module-based progressive disclosure
  if (l2m || reg || company.enrichment_l1) {
    // Color maps for colored badges
    const pitchFramingColors: Record<string, string> = {
      growth_acceleration: 'bg-success/15 text-success border-success/30',
      efficiency_protection: 'bg-[#3B82F6]/15 text-[#3B82F6] border-[#3B82F6]/30',
      competitive_catch_up: 'bg-warning/15 text-warning border-warning/30',
      compliance_driven: 'bg-error/15 text-error border-error/30',
    }
    const revenueTrendColors: Record<string, string> = {
      growing: 'bg-success/15 text-success border-success/30',
      stable: 'bg-[#3B82F6]/15 text-[#3B82F6] border-[#3B82F6]/30',
      declining: 'bg-error/15 text-error border-error/30',
      restructuring: 'bg-warning/15 text-warning border-warning/30',
    }

    // Extract pitch framing and executive brief from opportunity module
    const pitchFraming = (l2m?.opportunity as Record<string, unknown> | undefined)?.pitch_framing as string | null ?? null
    const executiveBrief = (l2m?.opportunity as Record<string, unknown> | undefined)?.executive_brief as string | null ?? null
    const painHypothesis = l2m?.opportunity?.pain_hypothesis ?? null

    const profileFields: ModuleField[] = l2m?.profile ? [
      { label: 'Company Intel', value: l2m.profile.company_intel },
      { label: 'Key Products', value: l2m.profile.key_products },
      { label: 'Customer Segments', value: l2m.profile.customer_segments },
      { label: 'Competitors', value: l2m.profile.competitors, type: 'tags' as const },
      { label: 'Tech Stack', value: l2m.profile.tech_stack },
      { label: 'Leadership', value: l2m.profile.leadership_team },
      { label: 'Certifications', value: l2m.profile.certifications },
    ] : []

    const signalsFields: ModuleField[] = l2m?.signals ? [
      { label: 'AI Adoption', value: l2m.signals.ai_adoption_level, type: 'badge' as const },
      { label: 'Digital Maturity', value: l2m.signals.digital_maturity_score, type: 'score_bar' as const },
      { label: 'Fiscal Year End', value: l2m.signals.fiscal_year_end },
      { label: 'Tech Stack Categories', value: l2m.signals.tech_stack_categories },
      { label: 'IT Spend Indicators', value: l2m.signals.it_spend_indicators },
      { label: 'Growth Indicators', value: l2m.signals.growth_indicators },
      { label: 'Digital Initiatives', value: l2m.signals.digital_initiatives },
      { label: 'Job Postings', value: l2m.signals.job_posting_count, type: 'count' as const },
      { label: 'Hiring Departments', value: l2m.signals.hiring_departments },
      { label: 'Hiring Signals', value: l2m.signals.hiring_signals },
      { label: 'AI Hiring', value: l2m.signals.ai_hiring },
      { label: 'Leadership Changes', value: l2m.signals.leadership_changes },
      { label: 'Tech Partnerships', value: l2m.signals.tech_partnerships },
      { label: 'Competitor AI Moves', value: l2m.signals.competitor_ai_moves },
      { label: 'Regulatory Pressure', value: l2m.signals.regulatory_pressure },
      { label: 'Employee Sentiment', value: l2m.signals.employee_sentiment },
    ] : []

    const marketFields: ModuleField[] = l2m?.market ? [
      { label: 'Revenue Trend', value: l2m.market.revenue_trend, type: 'colored_badge' as const, colorMap: revenueTrendColors },
      { label: 'Growth Signals', value: l2m.market.growth_signals },
      { label: 'Recent News', value: l2m.market.recent_news },
      { label: 'Media Sentiment', value: l2m.market.media_sentiment, type: 'badge' as const },
      { label: 'Funding History', value: l2m.market.funding_history },
      { label: 'EU Grants', value: l2m.market.eu_grants },
      { label: 'M&A Activity', value: l2m.market.ma_activity },
      { label: 'Expansion', value: l2m.market.expansion },
      { label: 'Workflow AI Evidence', value: l2m.market.workflow_ai_evidence },
      { label: 'Press Releases', value: l2m.market.press_releases },
      { label: 'Thought Leadership', value: l2m.market.thought_leadership },
    ] : []

    const opportunityFields: ModuleField[] = l2m?.opportunity ? [
      { label: 'Pitch Framing', value: pitchFraming, type: 'colored_badge' as const, colorMap: pitchFramingColors },
      { label: 'Pain Hypothesis', value: l2m.opportunity.pain_hypothesis },
      { label: 'AI Opportunities', value: l2m.opportunity.ai_opportunities },
      { label: 'Quick Wins', value: l2m.opportunity.quick_wins, type: 'list' as const },
      { label: 'Industry Pain Points', value: l2m.opportunity.industry_pain_points },
      { label: 'Cross-Functional Pain', value: l2m.opportunity.cross_functional_pain },
      { label: 'Adoption Barriers', value: l2m.opportunity.adoption_barriers },
      { label: 'Relevant Case Study', value: l2m.opportunity.relevant_case_study },
    ] : []

    // Check if executive brief section has data
    const hasExecutiveBrief = pitchFraming || executiveBrief || painHypothesis

    tabs.push({
      id: 'intelligence',
      label: 'Intelligence',
      content: (
        <div className="max-w-3xl space-y-3">
          {/* ---- Executive Brief (always visible, no collapse) ---- */}
          {hasExecutiveBrief && (
            <div className="border border-accent/20 rounded-lg p-4 bg-accent/5 space-y-3">
              <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider">Executive Brief</h3>
              {pitchFraming && (
                <div>
                  <span className={`inline-flex items-center px-2.5 py-1 text-xs font-semibold rounded-full border ${pitchFramingColors[pitchFraming.toLowerCase()] ?? 'bg-accent/10 text-accent-hover border-accent/20'}`}>
                    {pitchFraming.replace(/_/g, ' ')}
                  </span>
                </div>
              )}
              {executiveBrief && (
                <div>
                  <p className="text-sm text-text leading-relaxed">{executiveBrief}</p>
                </div>
              )}
              {painHypothesis && (
                <div>
                  <h4 className="text-xs font-medium text-text-muted mb-1">Pain Hypothesis</h4>
                  <p className="text-sm text-text leading-relaxed">{painHypothesis}</p>
                </div>
              )}
            </div>
          )}

          {l2m && (
            <>
              <ModuleSummaryCard
                title="Company Profile"
                icon="🏢"
                fields={profileFields}
                enrichedAt={l2m.profile?.enriched_at}
                cost={l2m.profile?.enrichment_cost_usd}
                defaultOpen
              />
              <ModuleSummaryCard
                title="Strategic Signals"
                icon="📡"
                fields={signalsFields}
                enrichedAt={l2m.signals?.enriched_at}
                cost={l2m.signals?.enrichment_cost_usd}
              />
              <ModuleSummaryCard
                title="Market Intelligence"
                icon="📰"
                fields={marketFields}
                enrichedAt={l2m.market?.enriched_at}
                cost={l2m.market?.enrichment_cost_usd}
              />
              <ModuleSummaryCard
                title="AI Opportunity Assessment"
                icon="🎯"
                fields={opportunityFields}
                enrichedAt={l2m.opportunity?.enriched_at}
                cost={l2m.opportunity?.enrichment_cost_usd}
              />
            </>
          )}

          {/* ---- Legal & Registry ---- */}
          {reg && (
            <section className="space-y-4 border-t border-border/40 pt-8">
              <h2 className="text-xs font-semibold text-text-muted uppercase tracking-wider">Legal & Registry</h2>
              {reg.credibility_score != null && (
                <div className="mb-1">
                  <span className="text-xs text-text-muted">Credibility Score:</span>
                  <span className="ml-2 text-sm font-medium text-accent-cyan">{String(reg.credibility_score)}%</span>
                </div>
              )}
              <FieldGrid cols={3}>
                <Field label="Official Name" value={reg.official_name as string} source={regSource} />
                <Field label="ICO" value={reg.ico as string} source={regSource} />
                <Field label="DIC" value={reg.dic as string} source={regSource} />
                <Field label="Legal Form" value={reg.legal_form_name as string} source={regSource} />
                <Field label="Established" value={reg.date_established as string} source={regSource} />
                <Field label="Dissolved" value={reg.date_dissolved as string} source={regSource} />
                <Field label="City" value={reg.address_city as string} source={regSource} />
                <Field label="Postal Code" value={reg.address_postal_code as string} source={regSource} />
                <Field label="Registration Court" value={reg.registration_court as string} source={regSource} />
                <Field label="Registration Number" value={reg.registration_number as string} source={regSource} />
                <Field label="Registered Capital" value={reg.registered_capital as string} source={regSource} />
                <Field label="Status" value={reg.registration_status as string} source={regSource} />
                <Field label="Country" value={reg.registration_country as string} source={regSource} />
                <Field label="Match Confidence" value={reg.match_confidence as number} source={regSource} />
                <Field label="Match Method" value={reg.match_method as string} source={regSource} />
                <Field label="Insolvency" value={reg.insolvency_flag ? 'Yes' : 'No'} source={regSource} />
                {(reg.active_insolvency_count as number) > 0 && (
                  <Field label="Active Proceedings" value={String(reg.active_insolvency_count)} />
                )}
              </FieldGrid>
              <Field label="Address" value={reg.registered_address as string} className="mt-3" source={regSource} />

              {Array.isArray(reg.directors) && reg.directors.length > 0 && (
                <>
                  <h4 className="text-xs text-text-muted font-medium mt-4 mb-2">Directors</h4>
                  <div className="text-sm text-text space-y-1">
                    {(reg.directors as Array<Record<string, string>>).map((d, i) => (
                      <div key={i}>{String(d.name || d.jmeno || JSON.stringify(d))}</div>
                    ))}
                  </div>
                </>
              )}
              {Array.isArray(reg.nace_codes) && reg.nace_codes.length > 0 && (
                <>
                  <h4 className="text-xs text-text-muted font-medium mt-4 mb-2">NACE Codes</h4>
                  <div className="flex flex-wrap gap-1">
                    {(reg.nace_codes as Array<Record<string, string>>).map((n, i) => (
                      <span key={i} className="px-2 py-0.5 text-xs bg-surface-alt rounded border border-border-solid text-text-muted">
                        {String(n.code || n.kod)}: {String(n.name || n.nazev || '')}
                      </span>
                    ))}
                  </div>
                </>
              )}
              {Array.isArray(reg.insolvency_details) && (reg.insolvency_details as unknown[]).length > 0 && (
                <>
                  <h4 className="text-xs text-text-muted font-medium mt-4 mb-2">Insolvency Proceedings</h4>
                  <div className="space-y-2">
                    {(reg.insolvency_details as Array<Record<string, unknown>>).map((p, i) => (
                      <div key={i} className="text-sm bg-red-500/5 border border-red-500/20 rounded p-2">
                        <span className="font-medium text-text">{String(p.file_ref || p.spisova_znacka || `Proceeding ${i + 1}`)}</span>
                        {p.status ? <span className="text-xs text-text-muted ml-2">({String(p.status)})</span> : null}
                        {p.start_date ? <span className="text-xs text-text-dim ml-2">{String(p.start_date)}</span> : null}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </section>
          )}

          {/* ---- Raw Research ---- */}
          <RawResearchSection
            title="Raw Intelligence"
            data={company.enrichment_l1?.raw_response}
            subtitle="Unstructured research data — may contain additional insights not captured in structured fields above."
          />
        </div>
      ),
    })
  }

  // Contacts tab (only if contacts exist)
  if (company.contacts.length > 0) {
    tabs.push({
      id: 'contacts',
      label: 'Contacts',
      count: company.contacts.length,
      content: (
        <MiniTable
          columns={[
            { key: 'full_name', label: 'Name' },
            { key: 'job_title', label: 'Title' },
            { key: 'seniority_level', label: 'Seniority' },
            { key: 'icp_fit', label: 'ICP', render: (c) => <Badge variant="icp" value={c.icp_fit as string} /> },
            { key: 'contact_score', label: 'Score' },
            { key: 'authority_score', label: 'Authority' },
            { key: 'ai_champion', label: 'AI Champion', render: (c) => c.ai_champion ? <span className="text-xs text-accent-cyan font-medium">Yes</span> : null },
          ]}
          data={company.contacts as unknown as Array<Record<string, unknown>>}
          onRowClick={(c) => onNavigate('contact', c.id as string)}
        />
      ),
    })
  }

  // History tab — timeline + L1 metadata + timestamps + errors
  tabs.push({
    id: 'history',
    label: 'History',
    content: (
      <div className="space-y-1">
        <SectionDivider title="Enrichment Timeline" />
        <EnrichmentTimeline entries={[
          { label: 'Created', timestamp: company.created_at },
          ...(company.stage_completions ?? []).map((sc) => ({
            label: sc.stage.toUpperCase(),
            timestamp: sc.completed_at,
            cost: sc.cost_usd,
            status: sc.status as 'completed' | 'failed' | 'skipped',
            error: sc.error,
          })),
        ]} />

        {/* L1 Triage Metadata */}
        {company.enrichment_l1 && (
          <>
            <SectionDivider title="L1 Triage Details" />
            <FieldGrid cols={3}>
              <Field label="Confidence" value={company.enrichment_l1.confidence?.toFixed(2)} />
              <Field label="Quality Score" value={company.enrichment_l1.quality_score} />
              <Field label="Pre Score" value={company.enrichment_l1.pre_score?.toFixed(1)} />
              <Field label="Enrichment Cost" value={company.enrichment_l1.enrichment_cost_usd != null ? `${Math.round(company.enrichment_l1.enrichment_cost_usd * 1000)} credits` : undefined} />
              <Field label="Enriched At" value={company.enrichment_l1.enriched_at ? new Date(company.enrichment_l1.enriched_at).toLocaleString() : null} />
            </FieldGrid>
            {company.enrichment_l1.qc_flags && company.enrichment_l1.qc_flags.length > 0 && (
              <div className="mt-2">
                <span className="text-xs text-text-muted">QC Flags:</span>
                <div className="flex flex-wrap gap-1 mt-1">
                  {company.enrichment_l1.qc_flags.map((flag) => (
                    <span key={flag} className="px-2 py-0.5 text-[10px] bg-amber-500/10 text-amber-400 rounded border border-amber-500/20">
                      {flag}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {company.enrichment_l1.research_query && (
              <div className="mt-2">
                <span className="text-xs text-text-muted">Research Query:</span>
                <p className="text-xs text-text-dim mt-0.5 bg-surface-alt/50 rounded p-2">{company.enrichment_l1.research_query}</p>
              </div>
            )}
            <EditableTextarea label="Triage Notes" name="triage_notes" value={getEditableValue('triage_notes', company.triage_notes)} onChange={handleFieldChange} />
          </>
        )}

        {/* Enrichment Costs */}
        <SectionDivider title="Costs & Quality" />
        <FieldGrid cols={3}>
          <Field label="Total Enrichment Cost" value={company.enrichment_cost_usd != null ? `${Math.round(company.enrichment_cost_usd * 1000)} credits` : undefined} />
          <Field label="Data Quality Score" value={company.data_quality_score} />
          <Field label="AI Adoption" value={company.ai_adoption} />
          <Field label="News Confidence" value={company.news_confidence} />
        </FieldGrid>

        <SectionDivider title="Timestamps" />
        <FieldGrid cols={3}>
          <Field label="Created" value={company.created_at ? new Date(company.created_at).toLocaleString() : null} />
          <Field label="Updated" value={company.updated_at ? new Date(company.updated_at).toLocaleString() : null} />
          <Field label="Last Enriched" value={company.last_enriched_at ? new Date(company.last_enriched_at).toLocaleString() : null} />
        </FieldGrid>

        {company.error_message && (
          <>
            <SectionDivider title="Errors" />
            <div className="bg-error/10 border border-error/30 rounded-md p-3 text-sm text-error">
              {company.error_message}
            </div>
          </>
        )}
      </div>
    ),
  })

  return (
    <div>
      {/* Header — badges + links + metadata */}
      <div className="mb-4 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          {derived && (
            <span className="px-2.5 py-0.5 text-xs font-medium rounded-full text-white" style={{ backgroundColor: derived.color }}>
              {derived.label}
            </span>
          )}
          <Badge variant="tier" value={company.tier} />
          {company.data_quality_score != null && (
            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-accent-cyan/10 text-accent-cyan">
              DQ {company.data_quality_score}
            </span>
          )}
          {company.owner_name && <span className="text-xs text-text-muted">{company.owner_name}</span>}
          {company.tag_name && <span className="text-xs text-text-dim">{company.tag_name}</span>}
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          {company.domain && (
            <a href={`https://${company.domain}`} target="_blank" rel="noopener noreferrer" className="text-accent-cyan hover:underline">{company.domain}</a>
          )}
          {company.website_url && !company.domain && (
            <a href={company.website_url} target="_blank" rel="noopener noreferrer" className="text-accent-cyan hover:underline">Website</a>
          )}
          {company.linkedin_url && (
            <a href={company.linkedin_url} target="_blank" rel="noopener noreferrer" className="text-accent-cyan hover:underline">LinkedIn</a>
          )}
          {company.last_enriched_at && (
            <span className="text-text-dim">Enriched {new Date(company.last_enriched_at).toLocaleDateString()}</span>
          )}
        </div>
      </div>

      {/* Corrective actions for failed/review entities */}
      {needsAttention && (
        <div className="mb-4 p-3 bg-surface-alt rounded-lg border border-border-solid">
          <p className="text-xs text-text-muted mb-2">This company requires attention:</p>
          <CorrectiveActionButtons companyId={company.id} />
        </div>
      )}

      {/* Tabbed content */}
      <Tabs tabs={tabs} />
    </div>
  )
}
