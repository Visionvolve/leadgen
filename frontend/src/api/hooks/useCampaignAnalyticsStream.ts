/**
 * useCampaignAnalyticsStream — SSE consumer for
 * `GET /api/campaigns/:id/analytics/stream` (BL-1039).
 *
 * Why not EventSource?
 *   EventSource has no way to set an `Authorization` header, which the
 *   leadgen API requires (JWT bearer + `X-Namespace`). So we use
 *   `fetch()` + `ReadableStream.getReader()` and parse SSE frames by
 *   hand (the backend only emits `event:` / `data:` / `:comment`
 *   lines, so a ~30-line parser is sufficient).
 *
 * Event shape (matches `_analytics_stream_gen` in
 * `api/routes/campaign_routes.py`):
 *   - `event: snapshot` — full metrics payload on connect.
 *       data = { campaign_id, metrics: CampaignAnalyticsData }
 *   - `event: update`   — partial delta of changed counters.
 *       data = { campaign_id, delta: Partial<CampaignAnalyticsData>, timestamp }
 *   - `event: error`    — fatal server-side stream error; stream ends.
 *       data = { campaign_id?, message }
 *   - `:heartbeat`      — SSE comment; ignored (keeps proxies alive).
 *
 * The hook is additive: existing `useCampaignAnalytics` polling still
 * runs as a fallback in the call sites, so a disconnected or erroring
 * stream never blanks the UI.
 */

import { useEffect, useRef, useState } from 'react'
import { resolveApiBase, buildHeaders } from '../client'
import { getAccessToken, isTokenExpired } from '../../lib/auth'

// ---- Public types -------------------------------------------------

export interface AnalyticsStreamState<T> {
  /** Latest metrics as merged from snapshot + deltas. `null` until first snapshot arrives. */
  metrics: T | null
  /** True once the response headers have been received and we are reading events. */
  connected: boolean
  /** Non-null on network / parse / server error; cleared when a new snapshot arrives. */
  error: string | null
}

// ---- Helpers ------------------------------------------------------

/**
 * Deep-merge an SSE delta into an existing metrics object.
 *
 * The backend's `_compute_analytics_delta` emits deltas keyed by the
 * same parent paths as the snapshot (e.g. `engagement`, `messages`,
 * `sending.email` — which arrives as `{"sending": {"email": {...}}}`),
 * so a recursive shallow merge at each level produces the correct
 * merged snapshot without us needing per-path logic.
 *
 * Arrays and primitives are replaced wholesale; plain objects are
 * merged recursively.
 */
function deepMerge<T>(base: T, patch: Record<string, unknown>): T {
  if (base === null || base === undefined) {
    return patch as unknown as T
  }
  const out: Record<string, unknown> = {
    ...(base as unknown as Record<string, unknown>),
  }
  for (const key of Object.keys(patch)) {
    const nextVal = patch[key]
    const prevVal = (base as unknown as Record<string, unknown>)[key]
    if (
      nextVal &&
      typeof nextVal === 'object' &&
      !Array.isArray(nextVal) &&
      prevVal &&
      typeof prevVal === 'object' &&
      !Array.isArray(prevVal)
    ) {
      out[key] = deepMerge(prevVal, nextVal as Record<string, unknown>)
    } else {
      out[key] = nextVal
    }
  }
  return out as unknown as T
}

/** Parse a single SSE frame (text between `\n\n` delimiters). */
function parseFrame(raw: string): { event: string; data: string } | null {
  let event = 'message'
  let data = ''
  for (const line of raw.split('\n')) {
    if (!line || line.startsWith(':')) continue // comment / heartbeat
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      // SSE spec: multi-line data concatenates with newlines, but the
      // backend only emits single-line JSON so simple concat is fine.
      data += line.slice(5).trim()
    }
  }
  if (!data) return null
  return { event, data }
}

// ---- Hook ---------------------------------------------------------

/**
 * Subscribe to the live analytics SSE stream for a campaign.
 *
 * Returns the latest merged metrics snapshot and a `connected` flag
 * that call sites can use to drive a "Live" indicator and/or to gate
 * the polling fallback (e.g. `enabled: !connected`).
 *
 * The stream tears down automatically on unmount or `campaignId`
 * change via `AbortController`. There is no automatic reconnect:
 * call sites opt into polling fallback when `connected === false`.
 */
export function useCampaignAnalyticsStream<T>(
  campaignId: string | null,
): AnalyticsStreamState<T> {
  const [state, setState] = useState<AnalyticsStreamState<T>>({
    metrics: null,
    connected: false,
    error: null,
  })

  // Latest snapshot is held in a ref so `update` deltas can merge
  // against the most recent value without pulling `state` into the
  // effect dependency array (which would re-create the stream).
  const metricsRef = useRef<T | null>(null)

  useEffect(() => {
    if (!campaignId) {
      metricsRef.current = null
      setState({ metrics: null, connected: false, error: null })
      return
    }

    const controller = new AbortController()
    let cancelled = false

    const run = async () => {
      // Bail quietly if we have no (or an expired) access token. The
      // polling fallback will pick up auth handling via `apiFetch`'s
      // refresh flow — SSE won't retry on 401 so we simply skip.
      const token = getAccessToken()
      if (!token || isTokenExpired(token)) {
        return
      }

      const url = `${resolveApiBase()}/campaigns/${campaignId}/analytics/stream`
      const headers: Record<string, string> = {
        ...buildHeaders(token),
        Accept: 'text/event-stream',
      }
      // Content-Type is irrelevant for GET but buildHeaders sets it;
      // leaving it in doesn't matter to fetch.

      let resp: Response
      try {
        resp = await fetch(url, {
          method: 'GET',
          headers,
          signal: controller.signal,
          // Keep-alive isn't a browser fetch option, but
          // cache:'no-store' avoids any HTTP cache weirdness.
          cache: 'no-store',
        })
      } catch (e: unknown) {
        if ((e as DOMException)?.name === 'AbortError') return
        if (!cancelled) {
          setState((s) => ({
            ...s,
            connected: false,
            error: e instanceof Error ? e.message : 'Stream connection failed',
          }))
        }
        return
      }

      if (!resp.ok || !resp.body) {
        if (!cancelled) {
          setState((s) => ({
            ...s,
            connected: false,
            error: `Stream request failed (${resp.status})`,
          }))
        }
        return
      }

      if (cancelled) {
        // Aborted while the promise was in flight; swallow the body.
        try {
          resp.body.cancel()
        } catch {
          /* ignore */
        }
        return
      }

      setState((s) => ({ ...s, connected: true, error: null }))

      const reader = resp.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      try {
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })

          let splitIdx
          while ((splitIdx = buffer.indexOf('\n\n')) !== -1) {
            const rawFrame = buffer.slice(0, splitIdx)
            buffer = buffer.slice(splitIdx + 2)
            const frame = parseFrame(rawFrame)
            if (!frame) continue

            let payload: Record<string, unknown>
            try {
              payload = JSON.parse(frame.data) as Record<string, unknown>
            } catch {
              // Malformed frame — log and continue, don't blow up the stream.
              console.warn('useCampaignAnalyticsStream: bad JSON payload', frame.data)
              continue
            }

            if (frame.event === 'snapshot') {
              const next = payload.metrics as T
              metricsRef.current = next
              if (!cancelled) {
                setState({ metrics: next, connected: true, error: null })
              }
            } else if (frame.event === 'update') {
              const delta = payload.delta as Record<string, unknown> | undefined
              if (delta && metricsRef.current !== null) {
                const merged = deepMerge(metricsRef.current, delta)
                metricsRef.current = merged
                if (!cancelled) {
                  setState({ metrics: merged, connected: true, error: null })
                }
              }
            } else if (frame.event === 'error') {
              if (!cancelled) {
                const message =
                  (payload.message as string | undefined) ?? 'Stream error'
                setState((s) => ({
                  ...s,
                  connected: false,
                  error: message,
                }))
              }
              // Server indicated the stream is ending; stop reading.
              return
            }
            // Unknown event types (including `message`) are ignored.
          }
        }
      } catch (e: unknown) {
        if ((e as DOMException)?.name === 'AbortError') return
        if (!cancelled) {
          setState((s) => ({
            ...s,
            connected: false,
            error: e instanceof Error ? e.message : 'Stream read error',
          }))
        }
      } finally {
        if (!cancelled) {
          setState((s) => ({ ...s, connected: false }))
        }
      }
    }

    void run()

    return () => {
      cancelled = true
      try {
        controller.abort()
      } catch {
        /* ignore */
      }
    }
  }, [campaignId])

  return state
}
