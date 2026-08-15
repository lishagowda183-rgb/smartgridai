import { useEffect } from "react";

/**
 * Calls `callback` every `intervalMs` while mounted. Always cleans up on
 * unmount so we never poll after a page is left. Pass `enabled=false` to pause.
 */
export function usePolling(callback, intervalMs = 60000, enabled = true) {
  useEffect(() => {
    if (!enabled || !intervalMs || intervalMs <= 0) return undefined;
    const id = setInterval(callback, intervalMs);
    return () => clearInterval(id);
  }, [callback, intervalMs, enabled]);
}