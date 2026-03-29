import { useState, useCallback, useMemo } from 'react'
import { useParams, useSearchParams, useNavigate } from 'react-router'
import { useCampaign, useUpdateCampaign, useCloneCampaign, useCampaignContacts, useSaveAsTemplate } from '../../api/queries/useCampaigns'
import { useContact } from '../../api/queries/useContacts'
import { useCompany } from '../../api/queries/useCompanies'
import { useToast } from '../../components/ui/Toast'
import { Tabs, type Tab } from '../../components/ui/Tabs'
import { DetailModal } from '../../components/ui/DetailModal'
import { ContactDetail } from '../contacts/ContactDetail'
import { CompanyDetail } from '../companies/CompanyDetail'
import { EditableTextarea, FieldGrid, Field } from '../../components/ui/DetailField'
import { ContactsTab } from './tabs/ContactsTab'
import { MessageGenTab } from './tabs/MessageGenTab'
import { MessagesTab } from './tabs/MessagesTab'
import { OutreachTab } from './tabs/OutreachTab'
import { SettingsTab } from './tabs/SettingsTab'
import { StepsTab } from './tabs/StepsTab'
import { CampaignAnalytics } from '../../components/campaign/CampaignAnalytics'
import { useEntityStack } from '../../hooks/useEntityStack'
import { useReviewSummary } from '../../api/queries/useMessages'
import { OutreachApprovalDialog } from './OutreachApprovalDialog'

const STATUS_COLORS: Record<string, string> = {
  Draft: 'bg-[#8B92A0]/10 text-text-muted border-[#8B92A0]/20',
  Ready: 'bg-[#00B8CF]/15 text-[#00B8CF] border-[#00B8CF]/30',
  Generating: 'bg-accent/15 text-accent-hover border-accent/30',
  Review: 'bg-warning/15 text-warning border-warning/30',
  Approved: 'bg-success/15 text-success border-success/30',
  Exported: 'bg-[#2ecc71]/15 text-[#2ecc71] border-[#2ecc71]/30',
  Archived: 'bg-[#8B92A0]/10 text-text-dim border-[#8B92A0]/20',
}

const TAB_IDS = ['contacts', 'steps', 'generation', 'review', 'outreach', 'analytics', 'settings'] as const
type TabId = (typeof TAB_IDS)[number]

export function CampaignDetailPage() {
  const { campaignId } = useParams<{ campaignId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const { toast } = useToast()
  const updateCampaign = useUpdateCampaign()
  const cloneCampaign = useCloneCampaign()

  // Active tab from URL
  const rawTab = searchParams.get('tab')
  const activeTab: TabId = TAB_IDS.includes(rawTab as TabId) ? (rawTab as TabId) : 'contacts'

  const handleTabChange = useCallback((tabId: string) => {
    setSearchParams({ tab: tabId }, { replace: true })
  }, [setSearchParams])

  // Campaign data
  const { data: campaign, isLoading } = useCampaign(campaignId ?? null)
  const { data: contactsData } = useCampaignContacts(campaignId ?? '')
  const contactCount = contactsData?.contacts?.length ?? 0

  // Review summary for outreach approval
  const isReviewStatus = campaign?.status === 'Review'
  const { data: reviewSummary } = useReviewSummary(isReviewStatus ? (campaignId ?? null) : null)
  const [showOutreachDialog, setShowOutreachDialog] = useState(false)

  // Save as template
  const saveAsTemplate = useSaveAsTemplate()
  const [showSaveTemplate, setShowSaveTemplate] = useState(false)
  const [templateName, setTemplateName] = useState('')
  const [templateDesc, setTemplateDesc] = useState('')

  const canSaveAsTemplate = (campaign?.template_config?.length ?? 0) > 0

  const handleSaveAsTemplate = async () => {
    if (!campaign || !templateName.trim()) return
    try {
      await saveAsTemplate.mutateAsync({
        campaignId: campaign.id,
        name: templateName.trim(),
        description: templateDesc.trim() || undefined,
      })
      toast('Template saved', 'success')
      setShowSaveTemplate(false)
      setTemplateName('')
      setTemplateDesc('')
    } catch {
      toast('Failed to save template', 'error')
    }
  }

  // Editable state
  const isEditable = campaign?.status === 'Draft' || campaign?.status === 'Ready'
  const [edits, setEdits] = useState<Record<string, unknown>>({})
  const hasChanges = Object.keys(edits).length > 0

  const handleFieldChange = useCallback((name: string, value: unknown) => {
    setEdits((prev) => ({ ...prev, [name]: value }))
  }, [])

  const handleClone = useCallback(async () => {
    if (!campaign) return
    try {
      const result = await cloneCampaign.mutateAsync(campaign.id)
      toast(`Campaign cloned as '${result.name}'`, 'success')
      navigate(`../${result.id}`, { relative: 'path' })
    } catch {
      toast('Failed to clone campaign', 'error')
    }
  }, [campaign, cloneCampaign, toast, navigate])

  const handleSave = async () => {
    if (!campaign) return
    try {
      await updateCampaign.mutateAsync({ id: campaign.id, data: edits })
      toast('Campaign updated', 'success')
      setEdits({})
    } catch {
      toast('Failed to save changes', 'error')
    }
  }

  // Cross-entity modal (contacts/companies clicked from within tabs)
  const stack = useEntityStack('contact')
  const isContactOpen = stack.current?.type === 'contact'
  const isCompanyOpen = stack.current?.type === 'company'

  const { data: contactDetail, isLoading: contactLoading } = useContact(
    isContactOpen ? stack.current!.id : null,
  )
  const { data: companyDetail, isLoading: companyLoading } = useCompany(
    isCompanyOpen ? stack.current!.id : null,
  )

  const handleNavigate = useCallback((type: 'company' | 'contact', id: string) => {
    stack.open(type, id)
  }, [stack])

  const modalTitle = isContactOpen
    ? (contactDetail?.full_name ?? 'Contact')
    : isCompanyOpen
      ? (companyDetail?.name ?? 'Company')
      : ''

  const modalSubtitle = isContactOpen
    ? (contactDetail?.job_title ?? undefined)
    : isCompanyOpen
      ? (companyDetail?.domain ?? undefined)
      : undefined

  const modalLoading = isContactOpen ? contactLoading : companyLoading

  // Tab definitions
  const tabs: Tab[] = useMemo(() => [
    { id: 'contacts', label: 'Contacts', badge: contactCount || undefined },
    { id: 'steps', label: 'Steps' },
    { id: 'generation', label: 'Generation' },
    { id: 'review', label: 'Messages', badge: campaign?.generated_count || undefined },
    { id: 'outreach', label: 'Outreach' },
    { id: 'analytics', label: 'Analytics' },
    { id: 'settings', label: 'Settings' },
  ], [contactCount, campaign?.generated_count])

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-border border-t-accent rounded-full animate-spin" />
      </div>
    )
  }

  if (!campaign) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3">
        <p className="text-sm text-text-muted">Campaign not found</p>
        <button
          onClick={() => navigate('..', { relative: 'path' })}
          className="text-sm text-accent-cyan hover:underline bg-transparent border-none cursor-pointer"
        >
          Back to campaigns
        </button>
      </div>
    )
  }

  const statusColors = STATUS_COLORS[campaign.status] ?? STATUS_COLORS.Draft

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border">
        {/* Back link */}
        <button
          onClick={() => navigate('..', { relative: 'path' })}
          className="flex items-center gap-1 text-xs text-text-muted hover:text-accent-cyan mb-3 bg-transparent border-none cursor-pointer p-0 transition-colors"
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M7.5 2.5L4 6l3.5 3.5" />
          </svg>
          Back to Campaigns
        </button>

        {/* Title row */}
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <h1 className="text-lg font-semibold text-text truncate">{campaign.name}</h1>
            <span className={`inline-flex items-center px-2.5 py-0.5 text-xs font-medium rounded border whitespace-nowrap ${statusColors}`}>
              {campaign.status}
            </span>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {canSaveAsTemplate && (
              <button
                onClick={() => {
                  setTemplateName(campaign.name)
                  setTemplateDesc('')
                  setShowSaveTemplate(true)
                }}
                className="px-3 py-1 text-xs font-medium rounded bg-transparent text-text-muted border border-border cursor-pointer hover:text-text hover:border-accent transition-colors"
              >
                Save as Template
              </button>
            )}
            {isReviewStatus && reviewSummary?.can_approve_outreach && (
              <button
                onClick={() => setShowOutreachDialog(true)}
                className="px-3 py-1 text-xs font-medium rounded bg-success text-white border-none cursor-pointer hover:bg-success/90 transition-colors"
              >
                Approve Outreach
              </button>
            )}
            {isReviewStatus && reviewSummary && !reviewSummary.can_approve_outreach && reviewSummary.pending_reason && (
              <span className="text-xs text-warning">{reviewSummary.pending_reason}</span>
            )}
            <button
              onClick={handleClone}
              disabled={cloneCampaign.isPending}
              className="flex items-center gap-1 px-3 py-1 text-xs font-medium rounded bg-transparent text-text-muted border border-border cursor-pointer hover:text-text hover:border-text-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title="Clone campaign"
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <rect x="5.5" y="5.5" width="9" height="9" rx="1.5" />
                <path d="M3 10.5H2.5a1 1 0 01-1-1v-7a1 1 0 011-1h7a1 1 0 011 1V3" />
              </svg>
              {cloneCampaign.isPending ? 'Cloning...' : 'Clone'}
            </button>
            {hasChanges && (
              <button
                onClick={handleSave}
                disabled={updateCampaign.isPending}
                className="px-3 py-1 text-xs font-medium rounded bg-accent text-white border-none cursor-pointer hover:bg-accent-hover transition-colors disabled:opacity-50"
              >
                {updateCampaign.isPending ? 'Saving...' : 'Save Changes'}
              </button>
            )}
          </div>
        </div>

        {/* Description (editable) */}
        <div className="mt-3">
          {isEditable ? (
            <EditableTextarea
              label=""
              name="description"
              value={(edits.description as string) ?? campaign.description ?? ''}
              onChange={handleFieldChange}
              rows={2}
            />
          ) : campaign.description ? (
            <p className="text-sm text-text-muted">{campaign.description}</p>
          ) : null}
        </div>

        {/* Stats */}
        <div className="mt-3">
          <FieldGrid>
            <Field label="Contacts" value={campaign.total_contacts} />
            <Field label="Generated" value={`${campaign.generated_count}/${campaign.total_contacts}`} />
            <Field label="Cost" value={campaign.generation_cost > 0 ? `${Math.round(campaign.generation_cost * 1000)} credits` : '-'} />
            <Field label="Owner" value={campaign.owner_name} />
          </FieldGrid>
        </div>
      </div>

      {/* Tabs */}
      <Tabs tabs={tabs} activeTab={activeTab} onChange={handleTabChange} />

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto px-6 py-5">
        {activeTab === 'contacts' && (
          <ContactsTab
            campaignId={campaign.id}
            isEditable={isEditable}
            onNavigate={handleNavigate}
          />
        )}
        {activeTab === 'steps' && (
          <StepsTab campaignId={campaign.id} isEditable={isEditable} />
        )}
        {activeTab === 'generation' && (
          <MessageGenTab campaign={campaign} isEditable={isEditable} />
        )}
        {activeTab === 'review' && (
          <MessagesTab campaignId={campaign.id} onNavigate={handleNavigate} />
        )}
        {activeTab === 'outreach' && <OutreachTab campaign={campaign} />}
        {activeTab === 'analytics' && <CampaignAnalytics campaignId={campaign.id} />}
        {activeTab === 'settings' && <SettingsTab campaign={campaign} isEditable={isEditable} />}
      </div>

      {/* Cross-entity detail modal */}
      <DetailModal
        isOpen={!!stack.current}
        onClose={stack.close}
        title={modalTitle}
        subtitle={modalSubtitle}
        isLoading={modalLoading}
        canGoBack={stack.depth > 1}
        onBack={stack.pop}
        breadcrumb={stack.depth > 1 ? 'Back' : undefined}
      >
        {isContactOpen && contactDetail && (
          <ContactDetail contact={contactDetail} onNavigate={stack.push} />
        )}
        {isCompanyOpen && companyDetail && (
          <CompanyDetail company={companyDetail} onNavigate={stack.push} />
        )}
      </DetailModal>

      {showOutreachDialog && campaignId && (
        <OutreachApprovalDialog
          campaignId={campaignId}
          onClose={() => setShowOutreachDialog(false)}
          onApproved={() => { setShowOutreachDialog(false) }}
        />
      )}

      {/* Save as Template dialog */}
      {showSaveTemplate && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
          onClick={(e) => { if (e.target === e.currentTarget) setShowSaveTemplate(false) }}
        >
          <div className="bg-surface border border-border rounded-lg p-5 w-full max-w-md shadow-lg">
            <h2 className="text-sm font-semibold text-text mb-4">Save as Template</h2>
            <div className="flex flex-col gap-3">
              <div>
                <label className="text-xs text-text-muted mb-1 block">Template name</label>
                <input
                  type="text"
                  value={templateName}
                  onChange={(e) => setTemplateName(e.target.value)}
                  className="w-full px-3 py-1.5 text-sm rounded border border-border bg-surface text-text outline-none focus:border-accent"
                  autoFocus
                />
              </div>
              <div>
                <label className="text-xs text-text-muted mb-1 block">Description (optional)</label>
                <textarea
                  value={templateDesc}
                  onChange={(e) => setTemplateDesc(e.target.value)}
                  rows={2}
                  className="w-full px-3 py-1.5 text-sm rounded border border-border bg-surface text-text outline-none focus:border-accent resize-none"
                />
              </div>
              <div className="flex gap-2 justify-end mt-1">
                <button
                  onClick={() => setShowSaveTemplate(false)}
                  className="px-4 py-1.5 text-sm rounded bg-transparent text-text-muted border border-border cursor-pointer hover:text-text transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSaveAsTemplate}
                  disabled={!templateName.trim() || saveAsTemplate.isPending}
                  className="px-4 py-1.5 text-sm font-medium rounded bg-accent text-white border-none cursor-pointer hover:bg-accent-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {saveAsTemplate.isPending ? 'Saving...' : 'Save Template'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
