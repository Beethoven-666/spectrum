import * as React from "react"

const MOBILE_BREAKPOINT = 768
const MOBILE_QUERY = `(max-width: ${MOBILE_BREAKPOINT - 1}px)`

function getSnapshot(): boolean {
  return window.matchMedia(MOBILE_QUERY).matches
}

function getServerSnapshot(): boolean {
  return false
}

function subscribe(onStoreChange: () => void): () => void {
  const mql = window.matchMedia(MOBILE_QUERY)
  mql.addEventListener("change", onStoreChange)
  return () => mql.removeEventListener("change", onStoreChange)
}

export function useIsMobile(): boolean {
  return React.useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}
