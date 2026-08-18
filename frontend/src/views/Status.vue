<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  ArrowPathIcon,
  CpuChipIcon,
  ChevronDownIcon,
  ExclamationTriangleIcon,
  PlayCircleIcon,
  StopCircleIcon,
} from '@heroicons/vue/24/outline'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import { useAuthStore } from '@/stores/auth'
import { useSSE } from '@/composables/useSSE'
import type { BackendStatus } from '@/types'
import { sameLogEntry, type LogEntryLike } from '@/utils/logDedup'
import { logger } from '@/utils/logger'

const auth = useAuthStore()
const backend = ref<BackendStatus>({ running: false, pid: null, target: '' })
const businessLogs = ref<LogEntryLike[]>([])
const loading = ref(true)
const actionLoading = ref<'start' | 'restart' | 'stop' | null>(null)
const error = ref('')
const lastUpdated = ref('')
const terminalRef = ref<HTMLElement | null>(null)
const isPinnedToBottom = ref(true)
const showScrollButton = ref(false)
const hasUnreadLogs = ref(false)

const statusEndpoint = ref<string | null>('/sse/status')
const businessLogsEndpoint = ref<string | null>(null)

const backendBadge = computed(() => backend.value.running ? 'success' : 'warning')
const backendLabel = computed(() => backend.value.running ? '运行中' : '已停止')
const statusHeadline = computed(() => 'Embykeeper')
const statusDescription = computed(() => backend.value.running ? '当前正在运行。' : '当前尚未启动。')
const backendOutput = computed<string[]>(() => (backend.value?.recent_output || []).filter((line: string) => !line.startsWith('$ ')))
const businessLogLines = computed<string[]>(() => {
  return businessLogs.value.map((item) => {
    const parts = []
    if (item.time) {
      parts.push(`[${new Date(item.time).toLocaleString('zh-CN')}]`)
    }
    if (item.level) {
      parts.push(`[${item.level}]`)
    }
    if (item.description) {
      parts.push(`${item.description}:`)
    }
    parts.push(item.message || '')
    return parts.filter(Boolean).join(' ')
  })
})
const activeTerminalLines = computed<string[]>(() => {
  if (!backendOutput.value.length) {
    return businessLogLines.value
  }

  if (!businessLogLines.value.length) {
    return backendOutput.value
  }

  return [...backendOutput.value, ...businessLogLines.value]
})
const coloredTerminalHtml = computed(() => {
  const escapeHtml = (value: string) => value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  return activeTerminalLines.value.map((line) => {
    const safe = escapeHtml(line)
    if (safe.includes(' ERROR ') || safe.startsWith('ERROR') || safe.includes('] ERROR')) {
      return `<span class="text-rose-300">${safe}</span>`
    }
    if (safe.includes(' WARNING ') || safe.startsWith('WARNING') || safe.includes('] WARNING')) {
      return `<span class="text-amber-300">${safe}</span>`
    }
    if (safe.includes(' INFO ') || safe.startsWith('INFO') || safe.includes('] INFO')) {
      return safe
        .replace(/INFO/g, '<span class="text-sky-300">INFO</span>')
        .replace(/Embykeeper/g, '<span class="text-emerald-300">Embykeeper</span>')
    }
    return safe.replace(/Embykeeper/g, '<span class="text-emerald-300">Embykeeper</span>')
  }).join('\n')
})

const updateScrollState = () => {
  const element = terminalRef.value
  if (!element) return
  const threshold = 24
  const pinned = element.scrollTop + element.clientHeight >= element.scrollHeight - threshold
  isPinnedToBottom.value = pinned
  showScrollButton.value = !pinned
  if (pinned) {
    hasUnreadLogs.value = false
  }
}

const scrollToBottom = async (behavior: ScrollBehavior = 'smooth') => {
  await nextTick()
  const element = terminalRef.value
  if (!element) return
  element.scrollTo({ top: element.scrollHeight, behavior })
  isPinnedToBottom.value = true
  showScrollButton.value = false
  hasUnreadLogs.value = false
}

const sameBusinessLog = (left: LogEntryLike | null | undefined, right: LogEntryLike | null | undefined) => {
  return sameLogEntry(left, right)
}

const appendBusinessLog = (item: LogEntryLike) => {
  const lastLog = businessLogs.value[businessLogs.value.length - 1]
  if (sameBusinessLog(lastLog, item)) {
    return
  }

  businessLogs.value = [...businessLogs.value, item].slice(-240)

  if (isPinnedToBottom.value) {
    scrollToBottom('auto')
  } else {
    hasUnreadLogs.value = true
    showScrollButton.value = true
  }
}

const syncBusinessLogsStream = () => {
  const nextEndpoint = backend.value.running ? '/runinfo/logs/stream?include_children=true' : null

  if (!nextEndpoint) {
    if (businessLogsEndpoint.value) {
      disconnectBusinessLogsStream()
      businessLogsEndpoint.value = null
    }
    businessLogs.value = []
    return
  }

  if (businessLogsEndpoint.value !== nextEndpoint) {
    businessLogs.value = []
    businessLogsEndpoint.value = nextEndpoint
    connectBusinessLogsStream()
    return
  }

  if (!businessLogsConnected.value) {
    connectBusinessLogsStream()
  }
}

const { connect: connectStatusStream, disconnect: disconnectStatusStream } = useSSE<BackendStatus>(statusEndpoint, {
  onEvent: (event) => {
    if (event.type !== 'status') return
    const previousLogCount = backendOutput.value.length
    backend.value = {
      ...backend.value,
      ...event.data,
    }
    lastUpdated.value = new Date().toLocaleTimeString('zh-CN')
    syncBusinessLogsStream()
    const currentLogCount = (event.data?.recent_output || []).filter((line: string) => !line.startsWith('$ ')).length
    if (currentLogCount > previousLogCount) {
      if (isPinnedToBottom.value) {
        scrollToBottom('auto')
      } else {
        hasUnreadLogs.value = true
        showScrollButton.value = true
      }
    }
  },
})

const {
  isConnected: businessLogsConnected,
  connect: connectBusinessLogsStream,
  disconnect: disconnectBusinessLogsStream,
} = useSSE<LogEntryLike>(businessLogsEndpoint, {
  onEvent: (event) => {
    if (event.type !== 'message') return
    appendBusinessLog(event.data)
  },
  onError: (streamError) => {
    if (backend.value.running) {
      logger.error('Failed to stream business logs', streamError)
    }
  },
})

const fetchStatus = async () => {
  loading.value = true
  error.value = ''

  try {
    backend.value = await auth.request<BackendStatus>('/pm/status')
    lastUpdated.value = new Date().toLocaleTimeString('zh-CN')
    syncBusinessLogsStream()

    if (!backend.value.running) {
      error.value = backend.value.last_error || ''
      return
    }
  } catch (err) {
    logger.error('Failed to fetch status', err)
    error.value = logger.message(err, '状态信息加载失败')
  } finally {
    loading.value = false
  }
}

const handleAction = async (action: 'start' | 'restart' | 'stop') => {
  actionLoading.value = action
  try {
    await auth.request(`/pm/${action}`, { method: 'POST' })
    await fetchStatus()
  } catch (err) {
    logger.error('Action failed', err)
    await fetchStatus()
    if (!error.value) {
      error.value = logger.message(err, '操作未完成，请稍后重试')
    }
  } finally {
    actionLoading.value = null
  }
}

onMounted(async () => {
  await fetchStatus()
  connectStatusStream()
  nextTick(() => scrollToBottom('auto'))
})

onBeforeUnmount(() => {
  disconnectStatusStream()
  disconnectBusinessLogsStream()
})
</script>

<template>
  <div class="space-y-6">
    <section class="overflow-hidden rounded-[30px] border border-slate-200/80 bg-[radial-gradient(circle_at_top_left,_rgba(99,102,241,0.28),_transparent_32%),linear-gradient(135deg,_#0f172a_0%,_#111827_44%,_#1e293b_100%)] shadow-[0_28px_90px_-40px_rgba(15,23,42,0.7)]">
      <div class="space-y-6 px-6 py-7 sm:px-8">
        <div class="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.22em] text-primary-100 backdrop-blur-sm">
          <CpuChipIcon class="h-4 w-4" aria-hidden="true" />
          Embykeeper
        </div>

        <div class="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div class="space-y-4 text-white">
            <h1 class="text-3xl font-semibold tracking-tight sm:text-4xl">{{ statusHeadline }}</h1>
            <p class="max-w-2xl text-sm leading-6 text-slate-300">{{ statusDescription }}</p>
            <div class="flex flex-wrap items-center gap-3 text-sm text-slate-200">
              <UiBadge :variant="backendBadge" size="lg">{{ backendLabel }}</UiBadge>
              <span>更新时间 {{ lastUpdated || '-' }}</span>
            </div>
          </div>

          <div class="flex flex-wrap gap-3.5 mt-4 md:mt-0">
            <UiButton
              v-if="!backend.running"
              :loading="actionLoading === 'start'"
              @click="handleAction('start')"
            >
              <PlayCircleIcon class="mr-2 h-4 w-4" aria-hidden="true" />
              启动 Embykeeper
            </UiButton>
            <template v-else>
              <UiButton
                variant="secondary"
                :loading="actionLoading === 'restart'"
                @click="handleAction('restart')"
              >
                <ArrowPathIcon class="mr-2 h-4 w-4" aria-hidden="true" />
                重启 Embykeeper
              </UiButton>
              <UiButton
                variant="danger"
                :loading="actionLoading === 'stop'"
                @click="handleAction('stop')"
              >
                <StopCircleIcon class="mr-2 h-4 w-4" aria-hidden="true" />
                停止 Embykeeper
              </UiButton>
            </template>
            <UiButton variant="outline" :loading="loading" @click="fetchStatus">
              <ArrowPathIcon class="mr-2 h-4 w-4" aria-hidden="true" />
              {{ loading ? '刷新中...' : '立即刷新' }}
            </UiButton>
          </div>
        </div>
      </div>
    </section>

    <div v-if="error" class="rounded-[24px] border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900">
      <div class="flex items-start gap-2">
        <ExclamationTriangleIcon class="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
        <span>{{ error }}</span>
      </div>
    </div>

    <section class="relative overflow-hidden rounded-[30px] bg-[#020617] shadow-[0_28px_90px_-40px_rgba(2,6,23,0.9)]">
      <div class="border-b border-white/5 px-5 py-4 sm:px-7">
        <h2 class="text-lg font-semibold tracking-tight text-white">最近日志</h2>
      </div>

      <div
        ref="terminalRef"
        class="ek-terminal relative h-[420px] overflow-auto px-5 py-5 sm:px-7 sm:py-6"
        @scroll="updateScrollState"
      >
        <pre
          v-if="activeTerminalLines.length"
          class="min-h-full whitespace-pre-wrap break-words font-mono text-xs leading-6 text-slate-100"
          v-html="coloredTerminalHtml"
        ></pre>

        <div v-else class="flex h-full items-center justify-center text-sm text-slate-500">
          暂无可显示的日志。
        </div>
      </div>

      <button
        v-if="showScrollButton"
        type="button"
        class="absolute bottom-5 right-5 inline-flex h-12 w-12 items-center justify-center rounded-full border border-white/10 bg-white/10 text-white shadow-[0_18px_32px_-18px_rgba(15,23,42,0.8)] backdrop-blur-md transition hover:bg-white/15"
        @click="scrollToBottom()"
      >
        <span v-if="hasUnreadLogs" class="pointer-events-none absolute inset-0 rounded-full border border-sky-300/60 ek-log-ripple"></span>
        <ChevronDownIcon class="h-5 w-5" aria-hidden="true" />
      </button>
    </section>
  </div>
</template>
