import { useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useUpdateContact, type ContactDetail as ContactDetailType } from '../../api/queries/useContacts'
import { useToast } from '../../components/ui/Toast'
import { Badge } from '../../components/ui/Badge'
import {
  FieldGrid, Field, FieldLink,
  EditableSelect, EditableTextarea,
  SectionDivider, CollapsibleSection, MiniTable,
} from '../../components/ui/DetailField'
import { Tabs, type TabDef } from '../../components/ui/Tabs'
import { EnrichmentTimeline } from '../../components/ui/EnrichmentTimeline'
import { RawResearchSection } from '../../components/ui/RawResearchSection'
import {
  SENIORITY_DISPLAY, SENIORITY_REVERSE,
  DEPARTMENT_DISPLAY, DEPARTMENT_REVERSE,
  ICP_FIT_DISPLAY, ICP_FIT_REVERSE,
  RELATIONSHIP_STATUS_DISPLAY, RELATIONSHIP_STATUS_REVERSE,
  CONTACT_SOURCE_DISPLAY, CONTACT_SOURCE_REVERSE,
  LANGUAGE_DISPLAY, LANGUAGE_REVERSE,
  MESSAGE_STATUS_REVERSE,
  filterOptions,
  formatPhone,
} from '../../lib/display'

/** Renders a markdown string with proper heading/bold/list formatting. */
function MarkdownField({ label, text }: { label?: string; text: string }) {
  return (
    <div>
      {label && <h4 className="text-xs font-medium text-text-muted mb-1">{label}</h4>}
      <div className="prose-sm-msg text-sm text-text leading-relaxed">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      </div>
    </div>
  )
}

interface Props {
  contact: ContactDetailType
  onNavigate: (type: 'company' | 'contact', id: string) => void
}

export function ContactDetail({ contact, onNavigate }: Props) {
  const { toast } = useToast()
  const mutation = useUpdateContact()

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
      seniority_level: SENIORITY_REVERSE,
      department: DEPARTMENT_REVERSE,
      icp_fit: ICP_FIT_REVERSE,
      relationship_status: RELATIONSHIP_STATUS_REVERSE,
      contact_source: CONTACT_SOURCE_REVERSE,
      language: LANGUAGE_REVERSE,
      message_status: MESSAGE_STATUS_REVERSE,
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
      await mutation.mutateAsync({ id: contact.id, data: payload })
      toast('Contact updated', 'success')
      setEdits({})
      setCfEdits({})
    } catch {
      toast('Failed to save changes', 'error')
    }
  }

  /* ---- Tab definitions ---- */

  const tabs: TabDef[] = []

  // Overview tab
  tabs.push({
    id: 'overview',
    label: 'Overview',
    content: (
      <div className="space-y-1">
        {/* Company link */}
        {contact.company && (
          <>
            <SectionDivider title="Company" />
            <button
              onClick={() => contact.company && onNavigate('company', contact.company.id)}
              className="w-full text-left flex items-center gap-3 px-3 py-2 rounded-md bg-surface-alt border border-border-solid hover:border-accent/40 transition-colors"
            >
              <div className="flex-1 min-w-0">
                <span className="text-sm font-medium text-text">{contact.company.name}</span>
                {contact.company.domain && (
                  <span className="text-xs text-text-dim ml-2">{contact.company.domain}</span>
                )}
              </div>
              <Badge variant="status" value={contact.company.status} />
              <Badge variant="tier" value={contact.company.tier} />
            </button>
          </>
        )}

        {/* Contact Info */}
        <SectionDivider title="Contact Info" />
        <FieldGrid cols={3}>
          <FieldLink label="Email" value={contact.email_address} href={contact.email_address ? `mailto:${contact.email_address}` : null} />
          <FieldLink label="Phone" value={formatPhone(contact.phone_number)} href={contact.phone_number ? `tel:${contact.phone_number}` : null} />
          <Field label="City" value={contact.location_city} />
          <Field label="Country" value={contact.location_country} />
          <Field label="Employment Status" value={contact.employment_status} />
          {contact.employment_verified_at && (
            <Field label="Employment Verified" value={new Date(contact.employment_verified_at).toLocaleDateString()} />
          )}
        </FieldGrid>

        {/* Classification (editable) */}
        <SectionDivider title="Classification" />
        <FieldGrid cols={3}>
          <EditableSelect label="Seniority" name="seniority_level" value={getEditableValue('seniority_level', contact.seniority_level)} options={filterOptions(SENIORITY_DISPLAY)} onChange={handleFieldChange} />
          <EditableSelect label="Department" name="department" value={getEditableValue('department', contact.department)} options={filterOptions(DEPARTMENT_DISPLAY)} onChange={handleFieldChange} />
          <EditableSelect label="ICP Fit" name="icp_fit" value={getEditableValue('icp_fit', contact.icp_fit)} options={filterOptions(ICP_FIT_DISPLAY)} onChange={handleFieldChange} />
          <EditableSelect label="Relationship" name="relationship_status" value={getEditableValue('relationship_status', contact.relationship_status)} options={filterOptions(RELATIONSHIP_STATUS_DISPLAY)} onChange={handleFieldChange} />
          <EditableSelect label="Source" name="contact_source" value={getEditableValue('contact_source', contact.contact_source)} options={filterOptions(CONTACT_SOURCE_DISPLAY)} onChange={handleFieldChange} />
          <EditableSelect label="Language" name="language" value={getEditableValue('language', contact.language)} options={filterOptions(LANGUAGE_DISPLAY)} onChange={handleFieldChange} />
        </FieldGrid>

        {/* Notes (editable) */}
        <SectionDivider title="Notes" />
        <EditableTextarea
          label="Notes"
          name="notes"
          value={getEditableValue('notes', contact.notes)}
          onChange={handleFieldChange}
        />

        {/* Custom Fields */}
        {contact.custom_fields && Object.keys(contact.custom_fields).length > 0 && (
          <>
            <SectionDivider title="Custom Fields" />
            <div className="space-y-3">
              {Object.entries(contact.custom_fields).map(([key, val]) => (
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

        {/* Save button */}
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

  // Enrichment tab (only if person enrichment exists)
  if (contact.enrichment) {
    const e = contact.enrichment

    // Career trajectory color mapping
    const careerTrajectoryColors: Record<string, string> = {
      ascending: 'bg-success/15 text-success border-success/30',
      lateral: 'bg-[#3B82F6]/15 text-[#3B82F6] border-[#3B82F6]/30',
      descending: 'bg-warning/15 text-warning border-warning/30',
      early_career: 'bg-[#8B92A0]/10 text-text-muted border-[#8B92A0]/20',
    }
    const careerColor = e.career_trajectory ? (careerTrajectoryColors[e.career_trajectory.toLowerCase()] ?? null) : null

    // Check if various sections have data
    const hasCareerData = e.career_trajectory || (e.previous_companies && e.previous_companies.length > 0)
      || e.speaking_engagements || e.publications || e.twitter_handle || e.github_username
      || e.education || e.certifications || e.expertise_areas

    const hasBuyingSignals = (e.ai_champion != null) || e.ai_champion_score != null
      || (e.authority_score ?? contact.authority_score) != null
      || e.budget_signals || e.buying_signals || e.pain_indicators || e.technology_interests

    const hasRelationshipStrategy = e.personalization_angle || e.connection_points || e.conversation_starters || e.objection_prediction

    tabs.push({
      id: 'enrichment',
      label: 'Enrichment',
      content: (
        <div className="max-w-3xl space-y-3">
          {/* ---- Person Summary (always visible, no collapse) ---- */}
          {(e.person_summary || e.relationship_synthesis || e.linkedin_profile_summary) && (
            <div className="border border-accent/20 rounded-lg p-4 bg-accent/5 space-y-3">
              <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider">Person Summary</h3>
              {e.person_summary && (
                <MarkdownField text={e.person_summary} />
              )}
              {e.relationship_synthesis && (
                <MarkdownField label="Relationship Insights" text={e.relationship_synthesis} />
              )}
              {e.linkedin_profile_summary && (
                <MarkdownField label="LinkedIn Summary" text={e.linkedin_profile_summary} />
              )}
            </div>
          )}

          {/* ---- Career & Background (collapsible) ---- */}
          {hasCareerData && (
            <CollapsibleSection
              title="Career & Background"
              defaultOpen
              badge={careerColor && e.career_trajectory ? (
                <span className={`px-2 py-0.5 text-xs rounded-full border ${careerColor}`}>
                  {e.career_trajectory.replace(/_/g, ' ')}
                </span>
              ) : undefined}
            >
              <div className="space-y-4">
                {e.career_trajectory && (
                  <div>
                    <h4 className="text-xs font-medium text-text-muted mb-1">Career Trajectory</h4>
                    {careerColor ? (
                      <span className={`inline-flex items-center px-2.5 py-1 text-xs font-medium rounded-full border ${careerColor}`}>
                        {e.career_trajectory.replace(/_/g, ' ')}
                      </span>
                    ) : (
                      <span className="text-sm text-text">{e.career_trajectory}</span>
                    )}
                  </div>
                )}

                {e.previous_companies && e.previous_companies.length > 0 && (
                  <div>
                    <h4 className="text-xs font-medium text-text-muted mb-1">Previous Companies</h4>
                    <div className="space-y-1.5">
                      {e.previous_companies.map((pc, i) => (
                        <div key={i} className="flex items-baseline gap-2 text-sm text-text pl-2 border-l-2 border-border-solid/40">
                          <span className="font-medium">{String(pc.name || pc.company || `Company ${i + 1}`)}</span>
                          {pc.role ? <span className="text-text-muted">-- {String(pc.role)}</span> : null}
                          {pc.years ? <span className="text-text-dim text-xs">({String(pc.years)})</span> : null}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {e.education && (
                  <MarkdownField label="Education" text={String(e.education)} />
                )}
                {e.certifications && (
                  <MarkdownField label="Certifications" text={String(e.certifications)} />
                )}
                {e.expertise_areas && (
                  <div>
                    <h4 className="text-xs font-medium text-text-muted mb-1">Expertise Areas</h4>
                    <div className="flex flex-wrap gap-1.5">
                      {(Array.isArray(e.expertise_areas) ? e.expertise_areas : String(e.expertise_areas).split(',').map(s => s.trim())).filter(Boolean).map((area, i) => (
                        <span key={i} className="px-2 py-0.5 text-xs bg-accent/10 text-accent-hover rounded border border-accent/20">
                          {String(area)}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {e.speaking_engagements && (
                  <MarkdownField label="Speaking Engagements" text={String(e.speaking_engagements)} />
                )}
                {e.publications && (
                  <MarkdownField label="Publications" text={String(e.publications)} />
                )}

                {(e.twitter_handle || e.github_username) && (
                  <FieldGrid cols={3}>
                    {e.twitter_handle && (
                      <FieldLink label="Twitter / X" value={`@${e.twitter_handle.replace(/^@/, '')}`} href={`https://x.com/${e.twitter_handle.replace(/^@/, '')}`} />
                    )}
                    {e.github_username && (
                      <FieldLink label="GitHub" value={e.github_username} href={`https://github.com/${e.github_username}`} />
                    )}
                  </FieldGrid>
                )}
              </div>
            </CollapsibleSection>
          )}

          {/* ---- Buying Signals (collapsible) ---- */}
          {hasBuyingSignals && (
            <CollapsibleSection
              title="Buying Signals"
              defaultOpen
              badge={(() => {
                const isChampion = e.ai_champion ?? (contact.ai_champion === 'true' || contact.ai_champion === 'True')
                if (isChampion) return <span className="px-2 py-0.5 text-xs rounded-full bg-accent-cyan/15 text-accent-cyan border border-accent-cyan/30 font-medium">AI Champion</span>
                return undefined
              })()}
            >
              <div className="space-y-4">
                {/* AI Champion + Score — prominent display */}
                <div className="flex items-center gap-4 flex-wrap">
                  {e.ai_champion != null && (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-text-muted">AI Champion:</span>
                      <span className={`px-2 py-0.5 text-xs font-medium rounded-full border ${
                        e.ai_champion
                          ? 'bg-accent-cyan/15 text-accent-cyan border-accent-cyan/30'
                          : 'bg-[#8B92A0]/10 text-text-muted border-[#8B92A0]/20'
                      }`}>
                        {e.ai_champion ? 'Yes' : 'No'}
                      </span>
                    </div>
                  )}
                  {(e.ai_champion_score ?? contact.ai_champion_score) != null && (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-text-muted">Champion Score:</span>
                      <span className="text-sm font-bold text-accent-cyan">{e.ai_champion_score ?? contact.ai_champion_score}</span>
                    </div>
                  )}
                  {(e.authority_score ?? contact.authority_score) != null && (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-text-muted">Authority:</span>
                      {(() => {
                        const score = e.authority_score ?? contact.authority_score ?? 0
                        const color = score >= 7 ? 'text-success' : score >= 4 ? 'text-warning' : 'text-text-muted'
                        return <span className={`text-sm font-bold ${color}`}>{score}/10</span>
                      })()}
                    </div>
                  )}
                  {contact.contact_score != null && (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-text-muted">Contact Score:</span>
                      <span className="text-sm font-medium text-text">{contact.contact_score}</span>
                    </div>
                  )}
                </div>

                {e.budget_signals && (
                  <MarkdownField label="Budget Signals" text={String(e.budget_signals)} />
                )}
                {e.buying_signals && (
                  <MarkdownField label="Buying Signals" text={String(e.buying_signals)} />
                )}
                {e.pain_indicators && (
                  <MarkdownField label="Pain Indicators" text={String(e.pain_indicators)} />
                )}
                {e.technology_interests && (
                  <div>
                    <h4 className="text-xs font-medium text-text-muted mb-1">Technology Interests</h4>
                    <div className="flex flex-wrap gap-1.5">
                      {(Array.isArray(e.technology_interests) ? e.technology_interests : String(e.technology_interests).split(',').map(s => s.trim())).filter(Boolean).map((tech, i) => (
                        <span key={i} className="px-2 py-0.5 text-xs bg-[#3B82F6]/10 text-[#3B82F6] rounded border border-[#3B82F6]/20">
                          {String(tech)}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </CollapsibleSection>
          )}

          {/* ---- Relationship Strategy (collapsible, only if data) ---- */}
          {hasRelationshipStrategy && (
            <CollapsibleSection title="Relationship Strategy">
              <div className="space-y-4">
                {e.personalization_angle && (
                  <MarkdownField label="Personalization Angle" text={String(e.personalization_angle)} />
                )}
                {e.connection_points && (
                  <div>
                    <h4 className="text-xs font-medium text-text-muted mb-1">Connection Points</h4>
                    {Array.isArray(e.connection_points) ? (
                      <ul className="list-disc list-outside ml-5 space-y-1 text-sm text-text">
                        {(e.connection_points as unknown[]).map((point, i) => (
                          <li key={i}>{typeof point === 'object' ? JSON.stringify(point) : String(point)}</li>
                        ))}
                      </ul>
                    ) : (
                      <MarkdownField text={String(e.connection_points)} />
                    )}
                  </div>
                )}
                {e.conversation_starters && (
                  <MarkdownField label="Conversation Starters" text={String(e.conversation_starters)} />
                )}
                {e.objection_prediction && (
                  <MarkdownField label="Objection Prediction" text={String(e.objection_prediction)} />
                )}
              </div>
            </CollapsibleSection>
          )}

          {/* ---- Enrichment Metadata ---- */}
          <div className="border-t border-border/40 pt-4 mt-4">
            <FieldGrid cols={3}>
              <Field label="Enrichment Cost" value={(e.enrichment_cost_usd ?? contact.enrichment_cost_usd) != null ? `${Math.round((e.enrichment_cost_usd ?? contact.enrichment_cost_usd ?? 0) * 1000)} credits` : undefined} />
              {e.enriched_at && (
                <Field label="Enriched At" value={new Date(e.enriched_at).toLocaleString()} />
              )}
            </FieldGrid>
          </div>

          {/* ---- Raw Research ---- */}
          <RawResearchSection
            title="Raw Research"
            data={e.raw_response}
            subtitle="Unstructured research data -- may contain additional insights not captured in structured fields above."
          />
        </div>
      ),
    })
  }

  // Messages tab (only if messages exist)
  if (contact.messages.length > 0) {
    tabs.push({
      id: 'messages',
      label: 'Messages',
      count: contact.messages.length,
      content: (
        <MiniTable
          columns={[
            { key: 'channel', label: 'Channel' },
            { key: 'sequence_step', label: 'Step' },
            { key: 'variant', label: 'Variant' },
            { key: 'subject', label: 'Subject' },
            { key: 'status', label: 'Status', render: (m) => <Badge variant="msgStatus" value={m.status as string} /> },
            { key: 'tone', label: 'Tone' },
          ]}
          data={contact.messages as unknown as Array<Record<string, unknown>>}
          emptyText="No messages"
        />
      ),
    })
  }

  // History tab — timeline + status flags + timestamps + errors merged
  tabs.push({
    id: 'history',
    label: 'History',
    content: (
      <div className="space-y-1">
        <SectionDivider title="Enrichment Timeline" />
        <EnrichmentTimeline entries={[
          { label: 'Created', timestamp: contact.created_at },
          ...(contact.stage_completions ?? []).map((sc) => ({
            label: sc.stage.toUpperCase(),
            timestamp: sc.completed_at,
            cost: sc.cost_usd,
            status: sc.status as 'completed' | 'failed' | 'skipped',
            error: sc.error,
          })),
        ]} />

        <SectionDivider title="Timestamps" />
        <FieldGrid cols={3}>
          <Field label="Created" value={contact.created_at ? new Date(contact.created_at).toLocaleString() : null} />
          <Field label="Updated" value={contact.updated_at ? new Date(contact.updated_at).toLocaleString() : null} />
          <Field label="Last Enriched" value={contact.last_enriched_at ? new Date(contact.last_enriched_at).toLocaleString() : null} />
        </FieldGrid>

        <SectionDivider title="Costs & Quality" />
        <FieldGrid cols={3}>
          <Field label="Enrichment Cost" value={contact.enrichment_cost_usd != null ? `${Math.round(contact.enrichment_cost_usd * 1000)} credits` : undefined} />
          <Field label="Contact Score" value={contact.contact_score} />
        </FieldGrid>

        {contact.error && (
          <>
            <SectionDivider title="Errors" />
            <div className="bg-error/10 border border-error/30 rounded-md p-3 text-sm text-error">
              {contact.error}
            </div>
          </>
        )}
      </div>
    ),
  })

  return (
    <div>
      {/* Header */}
      <div className="flex items-start gap-4 mb-4">
        {contact.profile_photo_url && (
          <img
            src={contact.profile_photo_url}
            alt={contact.full_name}
            className="w-14 h-14 rounded-full object-cover border border-border-solid"
          />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge variant="icp" value={contact.icp_fit} />
            <Badge variant="msgStatus" value={contact.message_status} />
            {contact.owner_name && <span className="text-xs text-text-muted">{contact.owner_name}</span>}
            {contact.tag_name && <span className="text-xs text-text-dim bg-surface-alt px-1.5 py-0.5 rounded">{contact.tag_name}</span>}
          </div>
          {contact.linkedin_url && (
            <a href={contact.linkedin_url} target="_blank" rel="noopener noreferrer" className="text-xs text-accent-cyan hover:underline mt-1 inline-block">
              LinkedIn Profile
            </a>
          )}
        </div>
      </div>

      {/* Tabbed content */}
      <Tabs tabs={tabs} />
    </div>
  )
}
