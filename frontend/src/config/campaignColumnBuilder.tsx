import type { ColumnDef } from './columns'
import type { ContactListItem } from '../api/queries/useContacts'
import type { Campaign } from '../api/queries/useCampaigns'
import { CampaignCheckboxCell } from '../components/ui/CampaignCheckboxCell'

/**
 * Build dynamic ColumnDef[] for campaign checkbox columns.
 * Each campaign gets one column that renders a CampaignCheckboxCell.
 */
export function buildCampaignColumns(
  campaigns: Campaign[],
  membershipMap: Map<string, Set<string>>,
  toggle: (campaignId: string, contactId: string, isMember: boolean) => Promise<void>,
): ColumnDef<ContactListItem>[] {
  return campaigns.map((campaign) => {
    const truncatedName = campaign.name.length > 14
      ? campaign.name.slice(0, 14) + '...'
      : campaign.name

    return {
      key: `campaign_${campaign.id}`,
      label: truncatedName,
      width: '80px',
      minWidth: '80px',
      shrink: false,
      defaultVisible: true,
      render: (item: ContactListItem) => {
        const members = membershipMap.get(campaign.id)
        const isMember = members ? members.has(item.id) : false
        return (
          <CampaignCheckboxCell
            contactId={item.id}
            isMember={isMember}
            onToggle={(contactId, currentlyMember) => toggle(campaign.id, contactId, currentlyMember)}
          />
        )
      },
    }
  })
}
