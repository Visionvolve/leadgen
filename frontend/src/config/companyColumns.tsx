/* eslint-disable react-refresh/only-export-components */
import { Badge } from '../components/ui/Badge'
import type { CompanyListItem } from '../api/queries/useCompanies'
import { defineColumns } from './columns'
import { renderTagBadges } from './tagBadges'
import {
  TIER_DISPLAY, TIER_REVERSE,
  STATUS_DISPLAY, STATUS_REVERSE,
  BUYING_STAGE_DISPLAY, BUYING_STAGE_REVERSE,
  ENGAGEMENT_STATUS_DISPLAY, ENGAGEMENT_STATUS_REVERSE,
} from '../lib/display'

/** Enrichment stage dot/icon colors */
const STAGE_DOT: Record<string, { dot: string; label: string }> = {
  Imported:        { dot: 'bg-neutral-400', label: 'Imported' },
  Researched:      { dot: 'bg-blue-400', label: 'Researched' },
  Qualified:       { dot: 'bg-amber-400', label: 'Qualified' },
  Enriched:        { dot: 'bg-green-400', label: 'Enriched' },
  'Contacts Ready':{ dot: '', label: 'Contacts Ready' },
  Failed:          { dot: 'bg-red-400', label: 'Failed' },
  Disqualified:    { dot: '', label: 'Disqualified' },
}

/** All available company columns with visibility defaults. */
export const COMPANY_COLUMNS = defineColumns<CompanyListItem>([
  {
    key: 'name',
    label: 'Name',
    sortKey: 'name',
    minWidth: '140px',
    defaultVisible: true,
    editable: true,
    editType: 'text',
  },
  {
    key: 'domain',
    label: 'Domain',
    sortKey: 'domain',
    minWidth: '100px',
    defaultVisible: true,
    editable: true,
    editType: 'text',
    render: (c) =>
      c.domain ? (
        <a
          href={`https://${c.domain}`}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="text-accent-cyan hover:underline truncate block"
        >
          {c.domain}
        </a>
      ) : (
        '-'
      ),
  },
  {
    key: 'enrichment_stage',
    label: 'Stage',
    sortKey: 'enrichment_stage',
    minWidth: '120px',
    shrink: false,
    defaultVisible: true,
    render: (c) => {
      const val = c.enrichment_stage
      if (!val) return <span className="text-text-dim">-</span>
      const info = STAGE_DOT[val]
      if (!info) return <span className="text-xs text-text-muted">{val}</span>
      // Contacts Ready: green checkmark icon
      if (val === 'Contacts Ready') {
        return (
          <span className="inline-flex items-center gap-1.5 text-xs">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="text-green-400 flex-shrink-0">
              <path d="M2 6.5L4.5 9L10 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="text-text-muted">{info.label}</span>
          </span>
        )
      }
      // Disqualified: gray line-through text
      if (val === 'Disqualified') {
        return <span className="text-xs text-text-dim line-through">{info.label}</span>
      }
      // Default: colored dot + label
      return (
        <span className="inline-flex items-center gap-1.5 text-xs">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${info.dot}`} />
          <span className="text-text-muted">{info.label}</span>
        </span>
      )
    },
  },
  {
    key: 'tier',
    label: 'Tier',
    sortKey: 'tier',
    minWidth: '110px',
    shrink: false,
    defaultVisible: true,
    editable: true,
    editType: 'select',
    editOptions: TIER_DISPLAY,
    editReverse: TIER_REVERSE,
    render: (c) => <Badge variant="tier" value={c.tier} />,
  },
  {
    key: 'score',
    label: 'Score',
    sortKey: 'triage_score',
    minWidth: '55px',
    defaultVisible: true,
    render: (c) => (c.score != null ? c.score.toFixed(1) : '-'),
  },
  {
    key: 'company_size',
    label: 'Size',
    minWidth: '80px',
    defaultVisible: true,
  },
  {
    key: 'geo_region',
    label: 'Region',
    minWidth: '80px',
    defaultVisible: true,
  },
  {
    key: 'industry',
    label: 'Industry',
    minWidth: '90px',
    defaultVisible: true,
  },
  {
    key: 'owner_name',
    label: 'Owner',
    minWidth: '70px',
    defaultVisible: true,
  },
  // --- Hidden by default ---
  {
    key: 'status',
    label: 'Status',
    sortKey: 'status',
    minWidth: '110px',
    shrink: false,
    defaultVisible: false,
    editable: true,
    editType: 'select',
    editOptions: STATUS_DISPLAY,
    editReverse: STATUS_REVERSE,
    render: (c) => <Badge variant="status" value={c.status} />,
  },
  {
    key: 'tag_names',
    label: 'Tags',
    minWidth: '90px',
    defaultVisible: false,
    render: (c) => renderTagBadges((c as unknown as Record<string, unknown>).tag_names as string[] | undefined),
  },
  {
    key: 'triage_score',
    label: 'Triage Score',
    sortKey: 'triage_score',
    minWidth: '55px',
    defaultVisible: false,
    render: (c) => (c.triage_score != null ? c.triage_score.toFixed(1) : '-'),
  },
  {
    key: 'revenue_range',
    label: 'Revenue',
    minWidth: '80px',
    defaultVisible: false,
  },
  {
    key: 'contact_count',
    label: 'Contacts',
    sortKey: 'contact_count',
    minWidth: '55px',
    defaultVisible: false,
  },
  {
    key: 'hq_country',
    label: 'HQ',
    sortKey: 'hq_country',
    minWidth: '40px',
    defaultVisible: false,
  },
  {
    key: 'business_model',
    label: 'Business Model',
    minWidth: '100px',
    defaultVisible: false,
  },
  {
    key: 'ownership_type',
    label: 'Ownership',
    minWidth: '90px',
    defaultVisible: false,
  },
  {
    key: 'buying_stage',
    label: 'Buying Stage',
    minWidth: '100px',
    defaultVisible: false,
    editable: true,
    editType: 'select',
    editOptions: BUYING_STAGE_DISPLAY,
    editReverse: BUYING_STAGE_REVERSE,
  },
  {
    key: 'engagement_status',
    label: 'Engagement',
    minWidth: '90px',
    defaultVisible: false,
    editable: true,
    editType: 'select',
    editOptions: ENGAGEMENT_STATUS_DISPLAY,
    editReverse: ENGAGEMENT_STATUS_REVERSE,
  },
  {
    key: 'ai_adoption',
    label: 'AI Adoption',
    minWidth: '80px',
    defaultVisible: false,
  },
  {
    key: 'verified_employees',
    label: 'Employees',
    sortKey: 'verified_employees',
    minWidth: '70px',
    defaultVisible: false,
    render: (c) =>
      c.verified_employees != null
        ? c.verified_employees.toLocaleString()
        : '-',
  },
  {
    key: 'verified_revenue_eur_m',
    label: 'Revenue (EUR M)',
    sortKey: 'verified_revenue_eur_m',
    minWidth: '90px',
    defaultVisible: false,
    render: (c) =>
      c.verified_revenue_eur_m != null
        ? `${c.verified_revenue_eur_m.toFixed(1)}M`
        : '-',
  },
  {
    key: 'credibility_score',
    label: 'Credibility',
    sortKey: 'credibility_score',
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
    key: 'website_url',
    label: 'Website',
    minWidth: '80px',
    defaultVisible: false,
    render: (c) =>
      c.website_url ? (
        <a
          href={c.website_url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="text-accent-cyan hover:underline truncate block"
        >
          Website
        </a>
      ) : (
        '-'
      ),
  },
  {
    key: 'data_quality_score',
    label: 'Data Quality',
    sortKey: 'data_quality_score',
    minWidth: '70px',
    defaultVisible: false,
  },
  {
    key: 'last_enriched_at',
    label: 'Last Enriched',
    minWidth: '100px',
    defaultVisible: false,
    render: (c) =>
      c.last_enriched_at
        ? new Date(c.last_enriched_at).toLocaleDateString()
        : '-',
  },
])

/** Column keys that cannot be hidden. */
export const COMPANY_ALWAYS_VISIBLE = ['name']
