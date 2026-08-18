/**
 * Shared TypeScript interfaces used across multiple views.
 * Keep this file focused on data-shapes that cross component boundaries.
 */

// --- Runinfo / Logs ---

export interface RunLogEntry {
  level: string
  message: string
  time?: string | null
  timestamp?: string | null
  description?: string | null
  run_id?: string | null
  displayTime?: string
}

export interface RunSummary {
  id: string
  parent_ids?: string[]
  description?: string | null
  status: string
  status_code?: number | null
  status_info?: string | null
  duration?: number | null
  start_time?: string | null
  end_time?: string | null
  next_time?: string | null
  reschedule?: boolean
  has_next_time?: boolean
  is_reschedule?: boolean
  child_count?: number
}

export interface RunDetail {
  run: RunSummary
}

export interface RunBundle {
  run: RunSummary
  logs: RunLogEntry[]
}

// --- Emby ---

export interface EmbyAccountItem {
  id?: string
  key?: string
  url: string
  username: string
  name?: string | null
  enabled: boolean
  use_proxy: boolean
  allow_stream: boolean
  cf_challenge: boolean
  allow_multiple: boolean
  play_id?: string | null
  time: number[]
  interval_days?: string | null
  time_range?: string | null
  watch_history?: EmbyWatchRecord[]
  device_cache?: EmbyDeviceCache | null
  has_error?: boolean
  error_message?: string | null
}

export interface EmbyWatchRecord {
  status: 'success' | 'failed'
  time: string
}

export interface EmbyDeviceCache {
  device_name?: string
  last_check?: string
}

export interface EmbyRunItem {
  id: string
  status: string
  status_info?: string
  start_time?: string
  end_time?: string
  description?: string
}

export interface EmbyRunLog {
  level: string
  message: string
  time?: string | null
  run_id?: string | null
}

export interface EmbyModuleSummary {
  total: number
  enabled: number
  use_proxy: number
  concurrency: number
  time_range: string
  interval_days: string
  module_enabled: boolean
}

// --- Subsonic ---

export interface SubsonicAccountItem {
  id: string
  url: string
  username: string
  name?: string | null
  enabled: boolean
  use_proxy: boolean
  time: number[]
  interval_days?: string | null
  time_range?: string | null
}

// --- Telegram ---

export interface TelegramAccountItem {
  id: string
  phone: string
  enabled: boolean
}

// --- Status ---

export interface BackendStatus {
  running: boolean
  pid: number | null
  target: string
  recent_output?: string[]
  exit_code?: number | null
  last_error?: string
}
