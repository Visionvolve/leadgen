import { useEffect, useRef, useCallback } from 'react'

/**
 * Saves and restores scroll position for list pages when navigating
 * to a detail view and back. Uses sessionStorage so position survives
 * React re-mounts but not tab close.
 *
 * @param key - unique sessionStorage key per list page (e.g. 'contacts_scroll')
 * @param containerSelector - CSS selector for the scrollable container
 *   defaults to the DataTable's outer div: '[class*="overflow-auto"]'
 */
export function useScrollRestore(
  key: string,
  containerSelector = '.scrollbar-thin',
) {
  const restoredRef = useRef(false)

  /** Call this right before navigating away to save the current scroll offset. */
  const saveScrollPosition = useCallback(() => {
    const el = document.querySelector(containerSelector)
    if (el) {
      sessionStorage.setItem(key, String(el.scrollTop))
    }
  }, [key, containerSelector])

  /** Attempt to restore scroll position on mount (once data is rendered). */
  useEffect(() => {
    const saved = sessionStorage.getItem(key)
    if (!saved || restoredRef.current) return

    const scrollTo = parseInt(saved, 10)
    if (isNaN(scrollTo) || scrollTo <= 0) {
      sessionStorage.removeItem(key)
      return
    }

    // The DataTable uses virtual scrolling so we need to wait until rows
    // are rendered before restoring. Use a short rAF loop (max ~500ms).
    let attempts = 0
    const maxAttempts = 30 // ~500ms at 60fps

    const tryRestore = () => {
      const el = document.querySelector(containerSelector)
      if (!el) {
        if (++attempts < maxAttempts) {
          requestAnimationFrame(tryRestore)
        }
        return
      }

      el.scrollTop = scrollTo
      restoredRef.current = true
      sessionStorage.removeItem(key)
    }

    requestAnimationFrame(tryRestore)

    return () => {
      // If we never restored, leave the value for the next mount attempt
    }
  }, [key, containerSelector])

  return { saveScrollPosition }
}
