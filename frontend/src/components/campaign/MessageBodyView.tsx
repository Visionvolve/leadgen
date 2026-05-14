import { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'

interface MessageBodyViewProps {
  body: string
  /** Compact text-only preview (no iframe). Used inside dense grids. */
  compact?: boolean
  /** Optional minimum iframe height in px. */
  minHeight?: number
}

/**
 * Renders a message body intelligently:
 *  - HTML bodies (e.g. fixed-template invites) → sandboxed iframe so the
 *    markup renders the way a recipient will see it.
 *  - Plain / markdown bodies → ReactMarkdown.
 *
 * In `compact` mode (used inside dense table rows) the HTML is stripped
 * to a plain-text snippet so the row stays small; users open the full
 * PreviewModal to see the rendered email.
 *
 * Implementation note: we feed the HTML to the iframe via the `srcdoc`
 * attribute. The previous implementation populated the iframe imperatively
 * after mount which was fragile across Chromium versions (the iframe
 * could remain blank if paint occurred before the imperative write
 * landed). `srcDoc` is the standard, atomic, declarative way to embed
 * snippet HTML into a sandboxed frame.
 */
export function MessageBodyView({ body, compact = false, minHeight = 280 }: MessageBodyViewProps) {
  const looksHtml = isHtml(body)

  // Pre-compute the full HTML document so it's stable across renders and
  // React diff doesn't trigger needless srcdoc re-parses.
  const srcdoc = useMemo(() => {
    if (!looksHtml || compact) return ''
    return buildSrcdoc(body)
  }, [body, looksHtml, compact])

  if (compact) {
    if (!looksHtml) {
      return <span className="text-sm text-text-muted">{body}</span>
    }
    return (
      <span
        className="text-sm text-text-muted italic"
        title="HTML email — open Preview to see the rendered version"
      >
        {stripHtmlToSnippet(body)}
      </span>
    )
  }

  if (looksHtml) {
    return (
      <div className="rounded border border-border bg-white overflow-hidden">
        <iframe
          title="Rendered message body"
          // allow-same-origin is required so the CSS in srcdoc actually
          // applies; we do NOT add allow-scripts, so the iframe still
          // cannot execute JavaScript (the threat model for messages).
          sandbox="allow-same-origin"
          srcDoc={srcdoc}
          className="w-full bg-white"
          style={{ minHeight, height: minHeight }}
        />
      </div>
    )
  }

  return (
    <div className="text-sm text-text prose-sm-msg">
      <ReactMarkdown>{body}</ReactMarkdown>
    </div>
  )
}

function isHtml(body: string): boolean {
  return /<[a-z][\s\S]*>/i.test(body)
}

/**
 * Wrap a raw HTML body in a complete srcdoc document with our preview
 * styles. The body is interpolated verbatim — it's already trusted
 * server-rendered template HTML and the iframe sandbox blocks scripts.
 */
function buildSrcdoc(body: string): string {
  return `<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         font-size: 14px; color: #222; padding: 16px; line-height: 1.55; margin: 0;
         background: #ffffff; }
  a { color: #2563eb; }
  pre, code { white-space: pre-wrap; word-break: break-word; }
  img { max-width: 100%; }
  table { max-width: 100%; }
</style></head><body>${body}</body></html>`
}

/**
 * Reduce an HTML body to a short plain-text preview. We only need this
 * for compact table rows; everything else renders the iframe.
 */
function stripHtmlToSnippet(html: string, maxLen = 160): string {
  const text = html
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/\s+/g, ' ')
    .trim()
  if (text.length <= maxLen) return text || '(HTML email)'
  return text.slice(0, maxLen).trim() + '…'
}
