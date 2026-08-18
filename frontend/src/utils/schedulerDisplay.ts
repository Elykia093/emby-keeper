export const normalizeClockValue = (value: string): string | null => {
  const trimmed = String(value || '').trim()
  if (!trimmed) return null

  const matched = trimmed.match(/^(\d{1,2})(?::(\d{2}))?\s*([AaPp][Mm])?$/)
  if (!matched) return null

  let hour = Number(matched[1])
  const minute = Number(matched[2] ?? '00')
  const meridiem = matched[3]?.toUpperCase()

  if (Number.isNaN(hour) || Number.isNaN(minute) || minute < 0 || minute > 59) return null

  if (meridiem) {
    if (hour < 1 || hour > 12) return null
    if (hour === 12) hour = meridiem === 'AM' ? 0 : 12
    else if (meridiem === 'PM') hour += 12
  } else if (hour < 0 || hour > 23) {
    return null
  }

  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
}

export const parseTimeRangeValue = (value?: string | null) => {
  const trimmed = String(value || '').trim()
  if (!trimmed) return null

  const rangeMatch = trimmed.match(/^<\s*(.*?)\s*,\s*(.*?)\s*>$/)
  if (rangeMatch) {
    const start = normalizeClockValue(rangeMatch[1])
    const end = normalizeClockValue(rangeMatch[2])
    if (start && end) {
      return { mode: 'range' as const, start, end }
    }
  }

  const single = normalizeClockValue(trimmed)
  if (single) {
    return { mode: 'single' as const, start: single, end: single }
  }

  return null
}

export const parseIntervalValue = (value?: string | null) => {
  const trimmed = String(value || '').trim()
  if (!trimmed) return null

  const rangeMatch = trimmed.match(/^<\s*(\d+)\s*,\s*(\d+)\s*>$/)
  if (rangeMatch) {
    const start = Number(rangeMatch[1])
    const end = Number(rangeMatch[2])
    if (Number.isInteger(start) && Number.isInteger(end) && start > 0 && end > 0) {
      return { mode: 'range' as const, start, end }
    }
  }

  const single = Number(trimmed)
  if (Number.isInteger(single) && single > 0) {
    return { mode: 'single' as const, start: single, end: single }
  }

  return null
}

export const formatScheduleTimeRange = (value?: string | null) => {
  const parsed = parseTimeRangeValue(value)
  if (!parsed) return '-'
  return parsed.mode === 'single' ? `每天 ${parsed.start}` : `${parsed.start} - ${parsed.end}`
}

export const formatScheduleInterval = (value?: string | null) => {
  const parsed = parseIntervalValue(value)
  if (!parsed) return '-'
  return parsed.mode === 'single' ? `每 ${parsed.start} 天` : `${parsed.start} 至 ${parsed.end} 天`
}

export const formatScheduleConcurrency = (value?: number | null) => {
  const concurrency = Number(value)
  if (!Number.isFinite(concurrency) || concurrency <= 0) return '-'
  return `${concurrency} 个任务`
}

export const formatTimeRangeValue = (mode: 'single' | 'range', start: string, end: string) => {
  return mode === 'single' ? start : `<${start},${end}>`
}

export const formatIntervalValue = (mode: 'single' | 'range', single: string, start: string, end: string) => {
  return mode === 'single' ? single : `<${start},${end}>`
}