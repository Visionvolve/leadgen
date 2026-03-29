/**
 * useEnrichPipeline — manages pipeline lifecycle: start, poll status, stop.
 * Polls GET /api/pipeline/dag-status while running.
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { apiFetch } from '../../api/client'
import type { DagMode, StageProgress, EnrichFilters } from './StageCard.types'

interface DagStatusResponse {
  pipeline: {
    run_id: string
    status: string
    cost: number
    config: Record<string, unknown>
    started_at: string | null
    completed_at: string | null
  }
  stages: Record<string, {
    run_id: string
    status: string
    total: number
    done: number
    failed: number
    cost: number
    current_item?: { name: string; status: string }
  }>
  completions: Record<string, Record<string, number>>
}

interface DagRunConfig {
  tag_name?: string
  owner?: string
  tier_filter?: string[]
  stages: string[]
  soft_deps?: Record<string, boolean>
  sample_size?: number
  entity_ids?: string[]
  re_enrich?: Record<string, { enabled: boolean; horizon: string | null }>
  boost?: Record<string, boolean>
}

const POLL_INTERVAL = 5000

export function useEnrichPipeline(filters: EnrichFilters) {
  const [dagMode, setDagMode] = useState<DagMode>('configure')
  const [pipelineRunId, setPipelineRunId] = useState<string | null>(null)
  const [stageProgress, setStageProgress] = useState<Record<string, StageProgress>>({})
  const [totalCost, setTotalCost] = useState(0)
  const pollTimer = useRef<ReturnType<typeof setInterval> | undefined>(undefined)

  // Reset pipeline state when tag changes to prevent cross-tag/namespace leakage.
  // Uses render-time key comparison to avoid cascading renders from useEffect.
  // The poll interval is cleaned up by the useEffect below (its cleanup runs on tag change).
  const [prevTag, setPrevTag] = useState(filters.tag)
  if (prevTag !== filters.tag) {
    setPrevTag(filters.tag)
    setDagMode('configure')
    setStageProgress({})
    setTotalCost(0)
    setPipelineRunId(null)
  }

  // Poll for status
  const poll = useCallback(async () => {
    try {
      const params: Record<string, string> = {}
      if (filters.tag) params.tag_name = filters.tag
      const data = await apiFetch<DagStatusResponse>('/pipeline/dag-status', {
        params,
      })

      if (!data.pipeline) return

      // Update progress from stage runs
      const newProgress: Record<string, StageProgress> = {}
      for (const [code, stage] of Object.entries(data.stages)) {
        newProgress[code] = {
          status: stage.status as StageProgress['status'],
          total: stage.total,
          done: stage.done,
          failed: stage.failed,
          cost: stage.cost,
          current_item: stage.current_item,
        }
      }
      setStageProgress(newProgress)
      setTotalCost(data.pipeline.cost)
      setPipelineRunId(data.pipeline.run_id)

      // Check terminal states
      const pipelineStatus = data.pipeline.status
      if (pipelineStatus === 'completed' || pipelineStatus === 'failed' || pipelineStatus === 'stopped') {
        setDagMode('completed')
        clearInterval(pollTimer.current)
      }
    } catch {
      // Silently ignore poll errors (404 = no pipeline yet)
    }
  }, [filters.tag])

  // Start pipeline
  const start = useCallback(async (config: DagRunConfig) => {
    const body: Record<string, unknown> = {
      stages: config.stages,
    }
    if (config.tag_name) body.tag_name = config.tag_name
    if (config.owner) body.owner = config.owner
    if (config.tier_filter?.length) body.tier_filter = config.tier_filter
    if (config.soft_deps) body.soft_deps = config.soft_deps
    if (config.sample_size) body.sample_size = config.sample_size
    if (config.entity_ids?.length) body.entity_ids = config.entity_ids
    if (config.re_enrich) body.re_enrich = config.re_enrich
    if (config.boost) body.boost = config.boost

    const result = await apiFetch<{ pipeline_run_id: string }>('/pipeline/dag-run', {
      method: 'POST',
      body,
    })

    setPipelineRunId(result.pipeline_run_id)
    setDagMode('running')
    setStageProgress({})
    setTotalCost(0)

    // Start polling
    pollTimer.current = setInterval(poll, POLL_INTERVAL)
    // Immediate first poll
    setTimeout(poll, 500)
  }, [poll])

  // Stop pipeline
  const stop = useCallback(async () => {
    if (!pipelineRunId) return

    await apiFetch('/pipeline/dag-stop', {
      method: 'POST',
      body: { pipeline_run_id: pipelineRunId },
    })

    clearInterval(pollTimer.current)
    setDagMode('completed')
  }, [pipelineRunId])

  // Reset to configure mode
  const reset = useCallback(() => {
    clearInterval(pollTimer.current)
    setDagMode('configure')
    setStageProgress({})
    setTotalCost(0)
    setPipelineRunId(null)
  }, [])

  // Check for existing running pipeline when tag changes.
  // State reset is handled above in the render-time comparison.
  useEffect(() => {
    async function checkExisting() {
      try {
        const params: Record<string, string> = {}
        if (filters.tag) params.tag_name = filters.tag
        const data = await apiFetch<DagStatusResponse>('/pipeline/dag-status', {
          params,
        })
        if (data.pipeline?.status === 'running') {
          setPipelineRunId(data.pipeline.run_id)
          setDagMode('running')
          // Start polling
          pollTimer.current = setInterval(poll, POLL_INTERVAL)
          poll()
        }
      } catch {
        // No existing pipeline — stay in configure mode
      }
    }

    checkExisting()

    return () => clearInterval(pollTimer.current)
  }, [filters.tag, poll])

  return {
    dagMode,
    setDagMode,
    pipelineRunId,
    stageProgress,
    totalCost,
    start,
    stop,
    reset,
  }
}
