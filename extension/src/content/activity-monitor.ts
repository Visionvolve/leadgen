/**
 * Content script for LinkedIn messaging and network pages.
 *
 * Scrapes conversations, connection requests, and recent connections
 * for CRM sync. Sends events to the service worker for batched upload.
 *
 * Ported from ~/git/linkedin-lead-uploader/activity-monitor.js
 */

import { config, jitter } from '../common/config';
import type { ActivityEvent } from '../common/types';

// ============== LOGGING ==============
const LOG_PREFIX = '[VV Activity Monitor]';

const log = {
  info: (msg: string, ...args: unknown[]) => console.log(`${LOG_PREFIX} ${msg}`, ...args),
  success: (msg: string, ...args: unknown[]) => console.log(`${LOG_PREFIX} ${msg}`, ...args),
  warn: (msg: string, ...args: unknown[]) => console.warn(`${LOG_PREFIX} ${msg}`, ...args),
  error: (msg: string, ...args: unknown[]) => console.error(`${LOG_PREFIX} ${msg}`, ...args),
  debug: (msg: string, ...args: unknown[]) => console.debug(`${LOG_PREFIX} ${msg}`, ...args),
};

// ============== API CALL TRACKING ==============
let apiCallCount = 0;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ============== EXTERNAL ID GENERATION ==============

interface ExternalIdFields {
  type: string;
  contact: string | null;
  timestamp: string;
  conversationId: string | null;
}

/**
 * Generate deterministic external_id from stable event fields using SHA-256.
 * Same event will always produce the same ID (for deduplication).
 */
async function generateExternalId(
  eventData: Omit<ActivityEvent, 'external_id'>,
): Promise<string> {
  const stableFields: ExternalIdFields = {
    type: eventData.event_type,
    contact: eventData.contact_linkedin_url,
    timestamp: eventData.timestamp,
    conversationId: eventData.payload?.conversation_id || null,
  };

  const sortedJson = JSON.stringify(stableFields, Object.keys(stableFields).sort());

  const encoder = new TextEncoder();
  const data = encoder.encode(sortedJson);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);

  const hashArray = Array.from(new Uint8Array(hashBuffer));
  const hashHex = hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');

  return hashHex.substring(0, 24);
}

/**
 * Synchronous fallback for external_id generation.
 * Used when crypto.subtle is not available.
 */
function generateExternalIdSync(
  eventData: Omit<ActivityEvent, 'external_id'>,
): string {
  const stableFields: ExternalIdFields = {
    type: eventData.event_type,
    contact: eventData.contact_linkedin_url,
    timestamp: eventData.timestamp,
    conversationId: eventData.payload?.conversation_id || null,
  };

  const sortedJson = JSON.stringify(stableFields, Object.keys(stableFields).sort());

  let hash = 0;
  for (let i = 0; i < sortedJson.length; i++) {
    const char = sortedJson.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash; // Convert to 32bit integer
  }
  return 'ext_' + Math.abs(hash).toString(16).padStart(8, '0');
}

// ============== HELPERS ==============

function getCsrfToken(): string | null {
  const csrfCookie = document.cookie
    .split('; ')
    .find((row) => row.startsWith('JSESSIONID='));
  return csrfCookie ? csrfCookie.split('=')[1].replace(/"/g, '') : null;
}

/**
 * Get current user's member ID from page data.
 * Tries multiple extraction methods from embedded JSON, scripts, and meta tags.
 */
function getCurrentUserId(): string | null {
  try {
    // Method 1: Try to get from code elements with embedded JSON
    const codeElements = document.querySelectorAll('code');
    for (const code of codeElements) {
      try {
        const data = JSON.parse(code.textContent || '') as Record<string, unknown>;
        const included = data?.included as Array<Record<string, unknown>> | undefined;
        if (included) {
          for (const item of included) {
            const itemType = item.$type as string | undefined;
            if (
              itemType?.includes('MiniProfile') &&
              (item as Record<string, unknown>).publicIdentifier
            ) {
              const entityUrn = item.entityUrn as string | undefined;
              if (entityUrn) {
                const memberId = entityUrn.split(':').pop();
                if (memberId) {
                  log.debug('Found potential user ID from code element: ' + memberId);
                }
              }
            }
          }
        }
      } catch {
        // Not JSON, skip
      }
    }

    // Method 2: Parse from script tags
    const scripts = document.querySelectorAll('script');
    for (const script of scripts) {
      const text = script.textContent || '';

      if (
        text.includes('"voyagerMessagingDashMemberIdentity"') ||
        text.includes('"fsd_profile:')
      ) {
        const profileMatch = text.match(/"fsd_profile:([^"]+)"/);
        if (profileMatch) {
          log.debug('Found user ID from fsd_profile: ' + profileMatch[1]);
          return profileMatch[1];
        }

        const memberMatch = text.match(/urn:li:fsd_profile:([A-Za-z0-9_-]+)/);
        if (memberMatch) {
          log.debug('Found user ID from fsd_profile URN: ' + memberMatch[1]);
          return memberMatch[1];
        }
      }

      if (text.includes('"plainId"')) {
        const match = text.match(/"plainId"\s*:\s*(\d+)/);
        if (match) {
          log.debug('Found user ID from plainId: ' + match[1]);
          return match[1];
        }
      }

      if (text.includes('urn:li:member:')) {
        const match = text.match(/urn:li:member:(\d+)/);
        if (match) {
          log.debug('Found user ID from member URN: ' + match[1]);
          return match[1];
        }
      }
    }

    // Method 3: From voyager-feed-identity element
    const codeElement = document.getElementById('voyager-feed-identity');
    if (codeElement) {
      const data = JSON.parse(codeElement.textContent || '') as {
        miniProfile?: { entityUrn?: string };
      };
      const id = data?.miniProfile?.entityUrn?.split(':').pop();
      if (id) {
        log.debug('Found user ID from voyager-feed-identity: ' + id);
        return id;
      }
    }

    // Method 4: From data-member-id attribute
    const memberIdElement = document.querySelector('[data-member-id]');
    if (memberIdElement) {
      const id = memberIdElement.getAttribute('data-member-id');
      if (id) {
        log.debug('Found user ID from data-member-id: ' + id);
        return id;
      }
    }
  } catch (e) {
    log.debug('Could not extract user ID: ' + String(e));
  }
  return null;
}

// ============== LINKEDIN API REQUEST ==============

interface LinkedInApiResponse {
  elements?: Array<Record<string, unknown>>;
  included?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

/**
 * Make authenticated LinkedIn API request with rate limiting protection.
 * Enforces a hard cap on total API calls per sync.
 */
async function apiRequest(
  url: string,
  params: Record<string, string | number | boolean> = {},
): Promise<LinkedInApiResponse> {
  if (apiCallCount >= config.maxApiCallsPerSync) {
    throw new Error(
      `API call limit reached (${config.maxApiCallsPerSync}). Stopping to protect account.`,
    );
  }
  apiCallCount++;

  const csrfToken = getCsrfToken();
  if (!csrfToken) throw new Error('No CSRF token');

  const queryString = new URLSearchParams(
    Object.fromEntries(
      Object.entries(params).map(([k, v]) => [k, String(v)]),
    ),
  ).toString();
  const fullUrl = queryString ? `${url}?${queryString}` : url;

  log.info(`API call ${apiCallCount}/${config.maxApiCallsPerSync}: ${fullUrl}`);

  // Rate limiting delay with jitter
  await sleep(jitter(config.activityApiDelay));

  const response = await fetch(fullUrl, {
    headers: {
      'csrf-token': csrfToken,
      'x-restli-protocol-version': '2.0.0',
    },
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error(`API ${response.status}: ${response.statusText}`);
  }

  return (await response.json()) as LinkedInApiResponse;
}

// ============== PROFILE EXTRACTION HELPERS ==============

interface ProfileInfo {
  name: string;
  publicId: string | null;
  headline?: string;
}

interface ParticipantInfo {
  memberId: string;
  name: string;
  publicId: string | null;
  linkedinUrl: string | null;
}

/**
 * Build a profile map from LinkedIn API 'included' data.
 * Maps member IDs and entity URNs to profile info.
 */
function buildProfileMap(
  included: Array<Record<string, unknown>>,
): Record<string, ProfileInfo> {
  const profileMap: Record<string, ProfileInfo> = {};

  for (const item of included) {
    const itemType = item.$type as string | undefined;
    if (
      itemType &&
      (itemType.includes('MiniProfile') || itemType.includes('Profile'))
    ) {
      const entityUrn = item.entityUrn as string | undefined;
      const memberId = entityUrn ? entityUrn.split(':').pop() : null;
      if (memberId) {
        const profile: ProfileInfo = {
          name: (
            ((item.firstName as string) || '') +
            ' ' +
            ((item.lastName as string) || '')
          ).trim(),
          publicId: (item.publicIdentifier as string) || null,
          headline: (item.occupation as string) || '',
        };
        profileMap[memberId] = profile;
        if (entityUrn) {
          profileMap[entityUrn] = profile;
        }
      }
    }
  }

  return profileMap;
}

// ============== MESSAGING SCRAPER ==============

type PartialActivityEvent = Omit<ActivityEvent, 'external_id'>;

async function scrapeConversations(
  lastSyncTime: string | null,
): Promise<PartialActivityEvent[]> {
  log.info('Scraping conversations...');
  const events: PartialActivityEvent[] = [];
  const currentUserId = getCurrentUserId();
  const lastSyncTimestamp = lastSyncTime ? new Date(lastSyncTime).getTime() : 0;

  log.info('Current user ID: ' + (currentUserId || 'unknown'));

  try {
    // Get conversations list using LEGACY_INBOX endpoint
    const data = await apiRequest(
      'https://www.linkedin.com/voyager/api/messaging/conversations',
      { keyVersion: 'LEGACY_INBOX', count: config.maxConversationsPerSync },
    );

    const conversations = data.elements || [];
    log.info('Found ' + conversations.length + ' conversations');

    // Build global profile map from conversations list included data
    const globalProfileMap = buildProfileMap(data.included || []);
    log.debug(
      'Built global profile map with ' +
        Object.keys(globalProfileMap).length +
        ' profiles',
    );

    // Process each conversation
    let processedCount = 0;
    for (const convo of conversations) {
      if (processedCount >= config.maxConversationsPerSync) break;
      if (apiCallCount >= config.maxApiCallsPerSync - 2) {
        log.warn('Approaching API limit, stopping conversation processing');
        break;
      }

      const convoUrn =
        (convo.entityUrn as string) || (convo.dashEntityUrn as string);
      if (!convoUrn) continue;

      const conversationId = convoUrn.split(':').pop() || '';
      const lastActivity = (convo.lastActivityAt as number) || 0;

      // Skip old conversations
      if (lastActivity && lastActivity < lastSyncTimestamp) continue;

      // Find the OTHER participant in this conversation
      let otherParticipant: ParticipantInfo | null = null;
      const participants = (convo.participants ||
        convo['*participants'] ||
        []) as Array<Record<string, unknown>>;

      for (const participant of participants) {
        let participantData = participant;

        // Unwrap MessagingMember wrapper
        const messagingMember = participant[
          'com.linkedin.voyager.messaging.MessagingMember'
        ] as Record<string, unknown> | undefined;
        if (messagingMember) {
          participantData = messagingMember;
        }

        const miniProfile = (participantData.miniProfile ||
          participantData) as Record<string, unknown>;
        const memberUrn =
          (miniProfile?.entityUrn as string) ||
          (participantData?.entityUrn as string);
        const memberId = memberUrn ? memberUrn.split(':').pop() || null : null;

        // Skip current user
        if (memberId && currentUserId && memberId === currentUserId) {
          continue;
        }

        const publicId =
          (miniProfile?.publicIdentifier as string) ||
          (participantData?.publicIdentifier as string) ||
          null;
        const firstName =
          (miniProfile?.firstName as string) ||
          (participantData?.firstName as string) ||
          '';
        const lastName =
          (miniProfile?.lastName as string) ||
          (participantData?.lastName as string) ||
          '';

        if (publicId || memberId) {
          otherParticipant = {
            memberId: memberId || '',
            name: (firstName + ' ' + lastName).trim() || 'Unknown',
            publicId,
            linkedinUrl: publicId
              ? 'https://www.linkedin.com/in/' + publicId + '/'
              : null,
          };
          break;
        }
      }

      log.debug(
        'Conversation ' +
          conversationId +
          ' other participant: ' +
          (otherParticipant?.name || 'not found'),
      );

      processedCount++;
      log.info('Processing conversation ' + processedCount + ': ' + conversationId);

      try {
        // Fetch conversation events (messages)
        const convoData = await apiRequest(
          'https://www.linkedin.com/voyager/api/messaging/conversations/' +
            conversationId +
            '/events',
        );

        // Merge profile maps
        const profileMap = {
          ...globalProfileMap,
          ...buildProfileMap(convoData.included || []),
        };

        // Try to find participant from profile map if not found yet
        if (!otherParticipant || !otherParticipant.linkedinUrl) {
          for (const [key, profile] of Object.entries(profileMap)) {
            const memberId = key.includes(':') ? key.split(':').pop() || '' : key;
            if (memberId !== currentUserId && profile.publicId) {
              otherParticipant = {
                memberId,
                name: profile.name,
                publicId: profile.publicId,
                linkedinUrl:
                  'https://www.linkedin.com/in/' + profile.publicId + '/',
              };
              break;
            }
          }
        }

        // Process message events
        const messageEvents = convoData.elements || [];
        for (const item of messageEvents) {
          const eventContent = (item.eventContent || item) as Record<
            string,
            unknown
          >;
          if (!eventContent) continue;

          const timestamp =
            (item.createdAt as number) ||
            (item.deliveredAt as number) ||
            (eventContent.createdAt as number) ||
            0;
          if (timestamp < lastSyncTimestamp) continue;

          // Get sender info
          const senderUrn =
            (item.from as string) ||
            (item['*from'] as string) ||
            (eventContent.from as string) ||
            (eventContent['*from'] as string);
          let senderId: string | null = null;
          let senderProfile: ProfileInfo | undefined;

          if (senderUrn) {
            senderId =
              typeof senderUrn === 'string'
                ? senderUrn.split(':').pop() || null
                : null;
            senderProfile =
              profileMap[senderUrn] || (senderId ? profileMap[senderId] : undefined);
          }

          // Determine direction
          let isSentByContact = false;

          if (otherParticipant && senderId) {
            isSentByContact = senderId === otherParticipant.memberId;
          } else if (currentUserId && senderId) {
            isSentByContact = senderId !== currentUserId;
          } else if (senderProfile && otherParticipant) {
            isSentByContact =
              senderProfile.publicId === otherParticipant.publicId;
          }

          const direction: 'sent' | 'received' = isSentByContact
            ? 'received'
            : 'sent';

          // Get message text
          let messageText = '';
          const msgCreate = (eventContent[
            'com.linkedin.voyager.messaging.event.MessageEvent'
          ] || eventContent) as Record<string, unknown>;
          if (msgCreate) {
            const body = msgCreate.attributedBody || msgCreate.body;
            if (body && typeof body === 'object' && 'text' in body) {
              messageText = (body as { text: string }).text || '';
            } else if (typeof body === 'string') {
              messageText = body;
            }
          }

          // Skip empty messages
          if (!messageText) continue;

          const contactUrl = otherParticipant?.linkedinUrl || null;
          const contactName = otherParticipant?.name || 'Unknown';

          events.push({
            event_type: direction === 'sent' ? 'message_sent' : 'message_received',
            timestamp: new Date(timestamp).toISOString(),
            contact_linkedin_url: contactUrl,
            payload: {
              contact_name: contactName,
              message: messageText,
              conversation_id: conversationId,
              sender_id: senderId,
              direction,
            },
          });
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        log.warn('Error processing conversation ' + conversationId + ': ' + msg);
      }
    }

    log.success(
      'Scraped ' +
        events.length +
        ' message events from ' +
        processedCount +
        ' conversations',
    );
    return events;
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    log.error('Conversations API failed: ' + msg);
    return [];
  }
}

// ============== CONNECTION REQUESTS SCRAPER ==============

async function scrapeConnectionRequests(
  lastSyncTime: string | null,
): Promise<PartialActivityEvent[]> {
  log.info('Scraping connection requests...');
  const events: PartialActivityEvent[] = [];
  const lastSyncTimestamp = lastSyncTime ? new Date(lastSyncTime).getTime() : 0;

  try {
    const data = await apiRequest(
      'https://www.linkedin.com/voyager/api/relationships/invitationViews',
      { q: 'receivedInvitation', count: 50, includeInsights: true },
    );

    const elements = data.elements || [];
    log.info('Found ' + elements.length + ' invitation elements');

    // Build profile map from included data
    const profileMap = buildProfileMap(data.included || []);

    // Process invitations
    for (const element of elements) {
      const inv = (element.invitation || element) as Record<string, unknown>;
      const timestamp = (inv.sentTime as number) || (inv.createdAt as number) || 0;
      if (timestamp < lastSyncTimestamp) continue;

      const fromUrn =
        (inv.fromMember as string) || (inv['*fromMember'] as string);
      const profile = fromUrn ? profileMap[fromUrn] : null;

      if (!profile || !profile.publicId) {
        log.debug('Skipping invitation - no profile found for: ' + fromUrn);
        continue;
      }

      events.push({
        event_type: 'connection_request_received',
        timestamp: new Date(timestamp).toISOString(),
        contact_linkedin_url:
          'https://www.linkedin.com/in/' + profile.publicId + '/',
        payload: {
          contact_name: profile.name,
          contact_headline: profile.headline,
          message: (inv.message as string) || null,
        },
      });
    }

    log.success('Scraped ' + events.length + ' connection request events');
    return events;
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    log.warn('Connection requests API failed: ' + msg + ' - skipping');
    return [];
  }
}

// ============== RECENT CONNECTIONS (ACCEPTED) ==============

async function scrapeRecentConnections(
  lastSyncTime: string | null,
): Promise<PartialActivityEvent[]> {
  log.info('Scraping recent connections...');
  const events: PartialActivityEvent[] = [];
  const lastSyncTimestamp = lastSyncTime ? new Date(lastSyncTime).getTime() : 0;

  try {
    const data = await apiRequest(
      'https://www.linkedin.com/voyager/api/relationships/connections',
      { count: 50, sortType: 'RECENTLY_ADDED', start: 0 },
    );

    const connections = data.elements || [];

    for (const conn of connections) {
      const miniProfile = (conn.miniProfile || conn) as Record<string, unknown>;
      const publicId =
        (miniProfile.publicIdentifier as string) ||
        (conn.publicIdentifier as string);

      if (!publicId) continue;

      const timestamp =
        (conn.createdAt as number) ||
        (conn.connectedAt as number) ||
        (miniProfile.createdAt as number) ||
        Date.now();
      if (timestamp < lastSyncTimestamp) continue;

      events.push({
        event_type: 'connection_accepted',
        timestamp: new Date(timestamp).toISOString(),
        contact_linkedin_url: `https://www.linkedin.com/in/${publicId}/`,
        payload: {
          contact_name: `${(miniProfile.firstName as string) || (conn.firstName as string) || ''} ${(miniProfile.lastName as string) || (conn.lastName as string) || ''}`.trim(),
          contact_headline:
            (miniProfile.occupation as string) ||
            (conn.headline as string) ||
            '',
        },
      });
    }

    log.success(`Scraped ${events.length} recent connection events`);
    return events;
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    log.error(`Recent connections scrape failed: ${msg}`);
    return [];
  }
}

// ============== MAIN SYNC FUNCTION ==============

interface SyncResult {
  events: ActivityEvent[];
  wasPartial: boolean;
}

async function runActivitySync(lastSyncTime: string | null): Promise<SyncResult> {
  // Reset API call counter for this sync
  apiCallCount = 0;
  let wasPartial = false;

  log.info(`Running activity sync (last sync: ${lastSyncTime || 'never'})`);
  log.info(
    `Rate limits: ${config.maxApiCallsPerSync} API calls max, ${config.activityApiDelay}ms delay, ${config.maxConversationsPerSync} conversations max`,
  );

  const allEvents: PartialActivityEvent[] = [];

  // Scrape sources SEQUENTIALLY to respect rate limits
  log.info('--- Starting conversations scrape ---');
  const conversations = await scrapeConversations(lastSyncTime);
  allEvents.push(...conversations);

  if (apiCallCount >= config.maxApiCallsPerSync - 2) {
    log.warn(
      'Rate limit approaching after conversations, marking sync as partial',
    );
    wasPartial = true;
  }

  if (!wasPartial) {
    log.info('--- Starting connection requests scrape ---');
    const connectionRequests = await scrapeConnectionRequests(lastSyncTime);
    allEvents.push(...connectionRequests);

    if (apiCallCount >= config.maxApiCallsPerSync - 1) {
      log.warn(
        'Rate limit approaching after connection requests, marking sync as partial',
      );
      wasPartial = true;
    }
  }

  if (!wasPartial) {
    log.info('--- Starting recent connections scrape ---');
    const recentConnections = await scrapeRecentConnections(lastSyncTime);
    allEvents.push(...recentConnections);
  }

  if (apiCallCount >= config.maxApiCallsPerSync) {
    wasPartial = true;
  }

  // Dedupe by event_type + contact_linkedin_url + timestamp (rounded to minute)
  const seen = new Set<string>();
  const dedupedEvents = allEvents.filter((e) => {
    const key = `${e.event_type}|${e.contact_linkedin_url}|${e.timestamp?.slice(0, 16)}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  // Sort by timestamp (oldest first)
  dedupedEvents.sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
  );

  // Add external_id to each event for deduplication
  const eventsWithIds: ActivityEvent[] = await Promise.all(
    dedupedEvents.map(async (event) => {
      let external_id: string;
      try {
        external_id = await generateExternalId(event);
      } catch {
        external_id = generateExternalIdSync(event);
      }
      return { external_id, ...event } as ActivityEvent;
    }),
  );

  log.success(
    `Sync complete: ${eventsWithIds.length} events (partial: ${wasPartial}, API calls: ${apiCallCount}/${config.maxApiCallsPerSync})`,
  );

  return { events: eventsWithIds, wasPartial };
}

// ============== MESSAGE HANDLER ==============

chrome.runtime.onMessage.addListener(
  (
    request: { action?: string; type?: string; lastSyncTime?: string },
    _sender: chrome.runtime.MessageSender,
    sendResponse: (response: unknown) => void,
  ): boolean | void => {
    if (request.action === 'runActivitySync' || request.type === 'run_activity_sync') {
      log.info('Activity sync requested');
      runActivitySync(request.lastSyncTime || null)
        .then((result) =>
          sendResponse({
            success: true,
            events: result.events,
            wasPartial: result.wasPartial,
          }),
        )
        .catch((error: unknown) =>
          sendResponse({
            success: false,
            error: error instanceof Error ? error.message : String(error),
          }),
        );
      return true; // Keep channel open for async response
    }

    if (request.action === 'getActivityStatus' || request.type === 'get_activity_status') {
      sendResponse({
        ready: true,
        url: window.location.href,
        isMessaging: window.location.href.includes('/messaging'),
        isNetwork: window.location.href.includes('/mynetwork'),
      });
      return true;
    }

    return false;
  },
);

// ============== AUTO-NOTIFY ON PAGE LOAD ==============

setTimeout(() => {
  chrome.runtime.sendMessage({
    type: 'linkedin_page_loaded',
    url: window.location.href,
  }).catch(() => {
    // Extension context invalidated - ignore
  });
}, 1000);

log.success('Activity monitor loaded');
log.info(`Page: ${window.location.href}`);
