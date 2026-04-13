import { useState, useCallback } from 'react'

function readStorage<T>(key: string, initial: T): T {
  try {
    const stored = localStorage.getItem(key)
    return stored !== null ? (JSON.parse(stored) as T) : initial
  } catch {
    return initial
  }
}

/**
 * Persist a value in localStorage with a typed React state interface.
 * Falls back to `initial` if key is missing or JSON parse fails.
 * Reacts to key changes — re-reads value when key changes (e.g. namespace prefix).
 */
export function useLocalStorage<T>(key: string, initial: T): [T, (v: T | ((prev: T) => T)) => void] {
  // Store both key and value so we can detect key changes during render
  const [state, setState] = useState<{ key: string; value: T }>(() => ({
    key,
    value: readStorage(key, initial),
  }))

  // If the key changed (e.g. namespace switch), re-read from localStorage.
  // This is the React-recommended "derive state from props" pattern.
  let current = state.value
  if (state.key !== key) {
    current = readStorage(key, initial)
    setState({ key, value: current })
  }

  const set = useCallback(
    (v: T | ((prev: T) => T)) => {
      setState((prev) => {
        const next = typeof v === 'function' ? (v as (prev: T) => T)(prev.value) : v
        try {
          localStorage.setItem(key, JSON.stringify(next))
        } catch {
          // localStorage full or blocked — silently ignore
        }
        return { ...prev, value: next }
      })
    },
    [key],
  )

  return [current, set]
}
