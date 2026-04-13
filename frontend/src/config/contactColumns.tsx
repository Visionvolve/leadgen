/* eslint-disable react-refresh/only-export-components */
import { Badge } from '../components/ui/Badge'
import type { ContactListItem } from '../api/queries/useContacts'
import { defineColumns } from './columns'
import { renderTagBadges } from './tagBadges'
import {
  ICP_FIT_DISPLAY, ICP_FIT_REVERSE,
  SENIORITY_DISPLAY, SENIORITY_REVERSE,
  DEPARTMENT_DISPLAY, DEPARTMENT_REVERSE,
  MESSAGE_STATUS_DISPLAY, MESSAGE_STATUS_REVERSE,
  LANGUAGE_DISPLAY, LANGUAGE_REVERSE,
  CONTACT_SOURCE_DISPLAY, CONTACT_SOURCE_REVERSE,
} from '../lib/display'

/** All available contact columns with visibility defaults. */
export const CONTACT_COLUMNS = defineColumns<ContactListItem>([
  {
    key: 'full_name',
    label: 'Name',
    sortKey: 'last_name',
    minWidth: '130px',
    defaultVisible: true,
    render: (c) => {
      const ns = window.location.pathname.split('/')[1]
      return (
        <a
          href={`/${ns}/contacts/${c.id}`}
          onClick={(e) => {
            e.preventDefault()
            window.dispatchEvent(new CustomEvent('leadgen:navigate', { detail: `/${ns}/contacts/${c.id}` }))
          }}
          className="text-accent-cyan hover:underline cursor-pointer truncate block"
        >
          {c.full_name || '-'}
        </a>
      )
    },
  },
  {
    key: 'job_title',
    label: 'Title',
    sortKey: 'job_title',
    minWidth: '120px',
    defaultVisible: true,
    editable: true,
    editType: 'text',
  },
  {
    key: 'company_name',
    label: 'Company',
    minWidth: '120px',
    defaultVisible: true,
    render: (c) =>
      c.company_name ? (
        <span className="inline-flex items-center gap-1 min-w-0">
          <span className="truncate">{c.company_name}</span>
          {c.company_id && (
            <a
              href={`companies/${c.company_id}`}
              onClick={(e) => {
                e.stopPropagation()
                e.preventDefault()
                // Navigate via relative path — the page component handles routing
                const ns = window.location.pathname.split('/')[1]
                window.location.href = `/${ns}/companies/${c.company_id}`
              }}
              className="flex-shrink-0 text-text-dim hover:text-accent-cyan transition-colors"
              title="Open company"
            >
              <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 9v4a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h4" />
                <path d="M9 2h5v5" />
                <path d="M14 2L7 9" />
              </svg>
            </a>
          )}
        </span>
      ) : (
        <span className="text-text-dim">-</span>
      ),
  },
  {
    key: 'email_address',
    label: 'Email',
    sortKey: 'email_address',
    minWidth: '140px',
    defaultVisible: true,
    editable: true,
    editType: 'text',
    render: (c) =>
      c.email_address ? (
        <a
          href={`mailto:${c.email_address}`}
          onClick={(e) => e.stopPropagation()}
          className="text-accent-cyan hover:underline truncate block"
        >
          {c.email_address}
        </a>
      ) : (
        '-'
      ),
  },
  {
    key: 'seniority_level',
    label: 'Seniority',
    sortKey: 'seniority_level',
    minWidth: '90px',
    defaultVisible: true,
    editable: true,
    editType: 'select',
    editOptions: SENIORITY_DISPLAY,
    editReverse: SENIORITY_REVERSE,
  },
  {
    key: 'icp_fit',
    label: 'ICP Fit',
    sortKey: 'icp_fit',
    minWidth: '100px',
    shrink: false,
    defaultVisible: true,
    editable: true,
    editType: 'select',
    editOptions: ICP_FIT_DISPLAY,
    editReverse: ICP_FIT_REVERSE,
    render: (c) => <Badge variant="icp" value={c.icp_fit} />,
  },
  {
    key: 'score',
    label: 'Score',
    sortKey: 'contact_score',
    minWidth: '55px',
    defaultVisible: true,
    render: (c) => {
      if (c.score == null) return <span className="text-text-dim">-</span>
      const val = Math.round(c.score)
      return (
        <span className="inline-flex items-center gap-1.5 text-xs tabular-nums">
          <span className="w-8 h-1.5 rounded-full bg-surface-alt overflow-hidden">
            <span
              className="block h-full rounded-full bg-accent-cyan"
              style={{ width: `${Math.min(val, 100)}%` }}
            />
          </span>
          {val}
        </span>
      )
    },
  },
  {
    key: 'message_status',
    label: 'Msg Status',
    sortKey: 'message_status',
    minWidth: '100px',
    shrink: false,
    defaultVisible: true,
    editable: true,
    editType: 'select',
    editOptions: MESSAGE_STATUS_DISPLAY,
    editReverse: MESSAGE_STATUS_REVERSE,
    render: (c) => <Badge variant="msgStatus" value={c.message_status} />,
  },
  {
    key: 'owner_name',
    label: 'Owner',
    minWidth: '70px',
    defaultVisible: true,
  },
  // --- Enrichment summary columns (BL-180) ---
  {
    key: 'company_tier',
    label: 'Co. Tier',
    minWidth: '100px',
    shrink: false,
    defaultVisible: false,
    render: (c) => <Badge variant="tier" value={c.company_tier} />,
  },
  {
    key: 'enrichment_status',
    label: 'Enrichment',
    minWidth: '85px',
    shrink: false,
    defaultVisible: false,
    render: (c) => <Badge variant="enrichment" value={c.enrichment_status} />,
  },
  // --- Hidden by default ---
  {
    key: 'contact_score',
    label: 'Contact Score',
    sortKey: 'contact_score',
    minWidth: '55px',
    defaultVisible: false,
  },
  {
    key: 'tag_names',
    label: 'Tags',
    minWidth: '90px',
    defaultVisible: false,
    render: (c) => renderTagBadges((c as unknown as Record<string, unknown>).tag_names as string[] | undefined),
  },
  {
    key: 'department',
    label: 'Department',
    sortKey: 'department',
    minWidth: '90px',
    defaultVisible: false,
    editable: true,
    editType: 'select',
    editOptions: DEPARTMENT_DISPLAY,
    editReverse: DEPARTMENT_REVERSE,
  },
  {
    key: 'location_city',
    label: 'City',
    minWidth: '80px',
    defaultVisible: false,
  },
  {
    key: 'location_country',
    label: 'Country',
    minWidth: '70px',
    defaultVisible: false,
  },
  {
    key: 'linkedin_url',
    label: 'LinkedIn',
    minWidth: '80px',
    defaultVisible: false,
    render: (c) =>
      c.linkedin_url ? (
        <a
          href={c.linkedin_url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="text-accent-cyan hover:underline truncate block"
        >
          LinkedIn
        </a>
      ) : (
        '-'
      ),
  },
  {
    key: 'phone_number',
    label: 'Phone',
    minWidth: '100px',
    defaultVisible: false,
  },
  {
    key: 'ai_champion_score',
    label: 'AI Champion',
    sortKey: 'ai_champion_score',
    minWidth: '70px',
    defaultVisible: false,
  },
  {
    key: 'authority_score',
    label: 'Authority',
    sortKey: 'authority_score',
    minWidth: '65px',
    defaultVisible: false,
  },
  {
    key: 'linkedin_activity_level',
    label: 'LinkedIn Activity',
    sortKey: 'linkedin_activity_level',
    minWidth: '100px',
    defaultVisible: false,
  },
  {
    key: 'language',
    label: 'Language',
    minWidth: '70px',
    defaultVisible: false,
    editable: true,
    editType: 'select',
    editOptions: LANGUAGE_DISPLAY,
    editReverse: LANGUAGE_REVERSE,
  },
  {
    key: 'contact_source',
    label: 'Source',
    minWidth: '70px',
    defaultVisible: false,
    editable: true,
    editType: 'select',
    editOptions: CONTACT_SOURCE_DISPLAY,
    editReverse: CONTACT_SOURCE_REVERSE,
  },
  {
    key: 'company_status',
    label: 'Co. Status',
    minWidth: '100px',
    defaultVisible: false,
    render: (c) => <Badge variant="status" value={c.company_status} />,
  },
  {
    key: 'last_enriched_at',
    label: 'Enriched At',
    sortKey: 'last_enriched_at',
    minWidth: '100px',
    defaultVisible: false,
    render: (c) => {
      if (!c.last_enriched_at) return <span className="text-text-dim">-</span>
      const d = new Date(c.last_enriched_at)
      return (
        <span className="text-xs text-text-muted tabular-nums">
          {d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
        </span>
      )
    },
  },
])

/** Column keys that cannot be hidden. */
export const CONTACT_ALWAYS_VISIBLE = ['full_name']
