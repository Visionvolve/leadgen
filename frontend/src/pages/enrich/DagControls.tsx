/**
 * DagControls — top bar with tag info, total cost, config manager, and run/stop buttons.
 */

import type { DagMode } from './StageCard.types'
import { ConfigManager } from './ConfigManager'
import { useTokenBudget } from '../../hooks/useTokenBudget'

interface DagControlsProps {
  mode: DagMode
  tagName: string
  estimatedCost: number
  runningCost: number
  enabledCount: number
  onRun: () => void
  onStop: () => void
  isLoading: boolean
  estimateError?: boolean
  onLoadConfig?: (config: Record<string, unknown>) => void
  getConfigSnapshot?: () => Record<string, unknown>
}

/** Convert USD cost to credits (1 credit = $0.001) */
function toCredits(usd: number): number {
  return Math.ceil(usd / 0.001)
}

function fmtCredits(usd: number): string {
  const credits = toCredits(usd)
  if (credits === 0) return '0 credits'
  return `${credits.toLocaleString()} credits`
}

export function DagControls({
  mode,
  tagName,
  estimatedCost,
  runningCost,
  enabledCount,
  onRun,
  onStop,
  isLoading,
  estimateError,
  onLoadConfig,
  getConfigSnapshot,
}: DagControlsProps) {
  const { budget } = useTokenBudget()
  const remaining = budget?.remaining_credits ?? null
  const estimatedCredits = toCredits(estimatedCost)
  const willExceedBudget = remaining !== null && estimatedCredits > remaining

  return (
    <div className="flex items-center justify-between mb-4 px-1">
      {/* Left: tag info + cost */}
      <div className="flex items-center gap-4">
        {tagName && (
          <span className="text-sm text-text">
            <span className="text-text-muted">Tag:</span>{' '}
            <span className="font-medium">{tagName}</span>
          </span>
        )}

        {mode === 'configure' && estimatedCost > 0 && (
          <span className="text-sm text-text-muted">
            Est. cost:{' '}
            <span className={`font-medium ${willExceedBudget ? 'text-error' : 'text-text'}`}>
              {fmtCredits(estimatedCost)}
            </span>
            {remaining !== null && (
              <span className="text-text-dim ml-1.5">
                / {remaining.toLocaleString()} remaining
              </span>
            )}
            {willExceedBudget && (
              <span className="text-error ml-1.5 text-xs">(exceeds budget)</span>
            )}
          </span>
        )}

        {(mode === 'running' || mode === 'completed') && (
          <span className="text-sm text-text-muted">
            Cost: <span className="font-medium text-text">{fmtCredits(runningCost)}</span>
          </span>
        )}
      </div>

      {/* Right: action buttons */}
      <div className="flex items-center gap-2">
        {mode === 'configure' && (
          <>
            {onLoadConfig && getConfigSnapshot && (
              <ConfigManager onLoad={onLoadConfig} getSnapshot={getConfigSnapshot} />
            )}
            <button
              onClick={onRun}
              disabled={enabledCount === 0}
              className="px-4 py-1.5 text-sm font-medium rounded-md bg-accent text-white hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {isLoading ? (
                <span className="flex items-center gap-1.5">
                  <span className="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Estimating...
                </span>
              ) : (
                `Run ${enabledCount} stage${enabledCount !== 1 ? 's' : ''}`
              )}
            </button>
            {estimateError && !isLoading && (
              <span className="text-xs text-warning">Cost estimate unavailable</span>
            )}
          </>
        )}

        {mode === 'running' && (
          <>
            <span className="flex items-center gap-2 text-sm text-accent-cyan">
              <span className="inline-block w-3 h-3 border-2 border-accent-cyan border-t-transparent rounded-full animate-spin" />
              Pipeline running...
            </span>
            <button
              onClick={onStop}
              className="px-3 py-1.5 text-sm font-medium rounded-md border border-error text-error hover:bg-error/10 transition-colors"
            >
              Stop All
            </button>
          </>
        )}
      </div>
    </div>
  )
}
