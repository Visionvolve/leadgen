import { useEffect, useRef } from 'react'
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
 */
export function MessageBodyView({ body, compact = false, minHeight = 280 }: MessageBodyViewProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const looksHtml = isHtml(body)

  // Render HTML into the sandboxed iframe whenever the body changes.
  useEffect(() => {
    if (compact) return
    if (!looksHtml) return
    const iframe = iframeRef.current
    if (!iframe) return
    const doc = iframe.contentDocument
    if (!doc) return
    const html = `<!doctype html><html><head><meta charset="utf-8"><style>
      body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
             font-size: 14px; color: #222; padding: 16px; line-height: 1.55; margin: 0; }
      a { color: #2563eb; }
      pre, code { white-space: pre-wrap; word-break: break-word; }
      img { max-width: 100%; }
      table { max-width: 100%; }
    </style></head><body>${body}</body></html>`
    doc.open()
    doc.write(html)
    doc.close()
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
          ref={iframeRef}
          title="Rendered message body"
          sandbox=""
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
