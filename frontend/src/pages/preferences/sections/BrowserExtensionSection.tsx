/**
 * BrowserExtensionSection -- self-serve download for the VisionVolve Leads
 * Chrome extension plus install instructions (BL-1209).
 *
 * - Any authenticated user can download the prod build.
 * - Only super_admins can download the staging build (filtered server-side too).
 */

import { useState } from 'react'
import { apiDownload, ApiError } from '../../../api/client'
import { useAuth } from '../../../hooks/useAuth'

type DownloadEnv = 'prod' | 'staging'

interface DownloadState {
  loading: DownloadEnv | null
  error: string | null
  lastDownloaded: DownloadEnv | null
}

export function BrowserExtensionSection() {
  const { user } = useAuth()
  const isSuperAdmin = user?.is_super_admin ?? false

  const [state, setState] = useState<DownloadState>({
    loading: null,
    error: null,
    lastDownloaded: null,
  })
  const [showInstructions, setShowInstructions] = useState(false)

  async function handleDownload(env: DownloadEnv) {
    setState({ loading: env, error: null, lastDownloaded: null })
    try {
      await apiDownload('/extension/download', { env })
      setState({ loading: null, error: null, lastDownloaded: env })
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Download failed'
      setState({ loading: null, error: message, lastDownloaded: null })
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="bg-surface border border-border rounded-lg p-5">
        <h2 className="font-title text-[1rem] font-semibold tracking-tight mb-2">
          Browser Extension
        </h2>
        <p className="text-text-muted text-sm mb-4">
          The VisionVolve Leads Chrome extension lets you import contacts from
          LinkedIn Sales Navigator, track activity on LinkedIn, and validate
          profiles against your CRM data.
        </p>

        <div className="flex flex-wrap gap-3 mb-3">
          <button
            type="button"
            onClick={() => handleDownload('prod')}
            disabled={state.loading !== null}
            className="px-4 py-2 text-sm font-medium rounded-md bg-accent text-white hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {state.loading === 'prod'
              ? 'Preparing…'
              : 'Download Production Extension'}
          </button>

          {isSuperAdmin && (
            <button
              type="button"
              onClick={() => handleDownload('staging')}
              disabled={state.loading !== null}
              className="px-4 py-2 text-sm font-medium rounded-md border border-border text-text bg-surface hover:bg-surface-alt disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              title="Staging build is restricted to super admins"
            >
              {state.loading === 'staging'
                ? 'Preparing…'
                : 'Download Staging Extension'}
            </button>
          )}
        </div>

        {state.error && (
          <p className="text-error text-sm mt-1" role="alert">
            {state.error}
          </p>
        )}

        {state.lastDownloaded && (
          <p className="text-text-muted text-sm mt-1">
            Downloaded {state.lastDownloaded} build. See install instructions
            below.
          </p>
        )}
      </div>

      <div className="bg-surface border border-border rounded-lg">
        <button
          type="button"
          onClick={() => setShowInstructions((v) => !v)}
          aria-expanded={showInstructions}
          aria-controls="extension-install-instructions"
          className="w-full flex items-center justify-between gap-3 p-5 text-left hover:bg-surface-alt/40 transition-colors rounded-lg"
        >
          <span className="font-title text-[0.95rem] font-semibold tracking-tight">
            Install instructions
          </span>
          <span
            className="text-text-muted text-sm"
            aria-hidden="true"
          >
            {showInstructions ? '−' : '+'}
          </span>
        </button>

        {showInstructions && (
          <div
            id="extension-install-instructions"
            className="px-5 pb-5 text-sm text-text"
          >
            <ol className="list-decimal pl-5 space-y-2">
              <li>Unzip the downloaded file to a folder you will keep around.</li>
              <li>
                Open <code className="bg-surface-alt px-1.5 py-0.5 rounded text-[0.82rem]">chrome://extensions</code>{' '}
                in Chrome (or any Chromium-based browser).
              </li>
              <li>
                Enable <strong>Developer mode</strong> using the toggle in the
                top right.
              </li>
              <li>
                Click <strong>Load unpacked</strong> and select the unzipped
                folder.
              </li>
              <li>
                Pin the extension to the toolbar so you can open it quickly.
              </li>
              <li>
                Click the extension icon to open the side panel, then log in
                with your VisionVolve credentials.
              </li>
            </ol>
            <p className="text-text-muted text-[0.82rem] mt-3">
              See the full guide in{' '}
              <a
                href="https://github.com/michallicko/leadgen-pipeline/blob/main/docs/extension-setup.md"
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent underline hover:no-underline"
              >
                docs/extension-setup.md
              </a>{' '}
              including troubleshooting tips for connection errors.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
