/**
 * Centralized logger that replaces scattered console.error calls.
 * All error reporting goes through this module so we can later
 * plug in a remote error-tracking service if needed.
 */

const PREFIX = '[EmbyKeeper]'

export const logger = {
  error(message: string, context?: unknown): void {
    if (context !== undefined) {
      console.error(`${PREFIX} ${message}`, context)
    } else {
      console.error(`${PREFIX} ${message}`)
    }
  },

  warn(message: string, context?: unknown): void {
    if (context !== undefined) {
      console.warn(`${PREFIX} ${message}`, context)
    } else {
      console.warn(`${PREFIX} ${message}`)
    }
  },

  info(message: string): void {
    console.info(`${PREFIX} ${message}`)
  },

  /**
   * Extract a human-readable error message from an unknown catch value.
   */
  message(err: unknown, fallback = '未知错误'): string {
    if (err instanceof Error) return err.message
    if (typeof err === 'string') return err
    return fallback
  },
}
