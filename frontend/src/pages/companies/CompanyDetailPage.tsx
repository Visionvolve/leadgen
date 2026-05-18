import { useParams, useNavigate, useLocation } from 'react-router'
import { useCompany, useUpdateCompany } from '../../api/queries/useCompanies'
import { EntityDetailPage } from '../../components/layout/EntityDetailPage'
import { EditableHeading } from '../../components/ui/DetailField'
import { useToast } from '../../components/ui/Toast'
import { useCompanyDuplicateGate } from '../../hooks/useCompanyDuplicateGate'
import { DuplicateCompanyModal } from '../../components/companies/DuplicateCompanyModal'
import { CompanyDetail } from './CompanyDetail'
import { withRev } from '../../lib/revision'

export function CompanyDetailPage() {
  const { namespace, companyId } = useParams<{ namespace: string; companyId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const { toast } = useToast()
  const mutation = useUpdateCompany()
  // BL-1203 / Phase 12: mount the shared duplicate-gate hook on the detail
  // page too, so a rename collision opens the same modal here.
  const { pendingDuplicate } = useCompanyDuplicateGate()

  const origin = (location.state as { origin?: string } | null)?.origin ?? withRev(`/${namespace}/companies`)
  const { data: company, isLoading } = useCompany(companyId ?? null)

  const handleNavigate = (type: 'company' | 'contact', id: string) => {
    const path = type === 'company'
      ? `/${namespace}/companies/${id}`
      : `/${namespace}/contacts/${id}`
    navigate(withRev(path), { state: { origin } })
  }

  const handleRenameSave = async (newValue: string) => {
    if (!company) return
    try {
      await mutation.mutateAsync({ id: company.id, data: { name: newValue } })
      toast('Name saved', 'success')
    } catch (err) {
      const apiErr = err as {
        status?: number
        code?: string
        details?: { matches?: Array<Record<string, unknown>> }
      }
      // 409 → dispatch the shared duplicate event (same wire format as
      // useInlineEdit). The Promise resolves when the modal callback fires.
      if (apiErr?.status === 409 && apiErr.code === 'duplicate_company_name') {
        const matches = apiErr.details?.matches ?? []
        await new Promise<void>((resolve, reject) => {
          window.dispatchEvent(
            new CustomEvent('leadgen:company-duplicate', {
              detail: {
                editedCompanyId: company.id,
                attemptedName: newValue,
                matches,
                retryWithKeepBoth: async () => {
                  await mutation.mutateAsync({
                    id: company.id,
                    data: { name: newValue },
                    params: { confirm_duplicate: 'keep_both' },
                  })
                  toast('Name saved', 'success')
                  resolve()
                },
                revertInput: () => reject(new Error('Cancelled')),
                afterMerge: () => resolve(),
              },
            }),
          )
        })
        return
      }
      throw err
    }
  }

  return (
    <EntityDetailPage
      closeTo={withRev(`/${namespace}/companies`)}
      title={company?.name ?? 'Company'}
      subtitle={company?.domain ?? undefined}
      isLoading={isLoading}
      titleSlot={
        company ? (
          <EditableHeading
            name="name"
            value={company.name || ''}
            onSave={handleRenameSave}
            placeholder="Company name"
          />
        ) : undefined
      }
    >
      {company && <CompanyDetail company={company} onNavigate={handleNavigate} />}
      {/* BL-1203 / Phase 12: render the duplicate-resolution modal. */}
      {pendingDuplicate && (
        <DuplicateCompanyModal
          ctx={pendingDuplicate}
          currentOwnerId={null}
        />
      )}
    </EntityDetailPage>
  )
}
