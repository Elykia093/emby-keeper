/**
 * Shared log-entry de-duplication helper.
 *
 * Several views (Status, Emby test-run) need to guard against the same
 * log line arriving twice via SSE + REST.  This helper provides a single
 * comparison function so the logic isn't duplicated.
 */

export interface LogEntryLike {
  time?: string | null
  level?: string | null
  message?: string | null
  description?: string | null
  run_id?: string | null
}

/**
 * Returns true when two log entries represent the same event.
 * Only compares fields that are stable across SSE re-deliveries.
 */
export function sameLogEntry(a: LogEntryLike | null | undefined, b: LogEntryLike | null | undefined): boolean {
  if (!a || !b) return false
  return (
    a.time === b.time &&
    a.level === b.level &&
    a.message === b.message &&
    (a.description ?? '') === (b.description ?? '') &&
    (a.run_id ?? '') === (b.run_id ?? '')
  )
}

/**
 * Prepend `item` to `list` if it isn't already the first entry.
 * Returns a new array (immutable update for Vue reactivity).
 */
export function dedupedPrepend<T extends LogEntryLike>(list: T[], item: T, max = 500): T[] {
  if (sameLogEntry(list[0], item)) return list
  return [item, ...list].slice(0, max)
}
