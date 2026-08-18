<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { ArrowPathIcon, MagnifyingGlassIcon, SignalIcon, SignalSlashIcon } from '@heroicons/vue/24/outline'
import UiCard from '@/components/ui/UiCard.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import { useAuthStore } from '@/stores/auth'
import { useSSE } from '@/composables/useSSE'
import type { RunLogEntry } from '@/types'
import { LOG_PAGE_LIMIT, LOG_MAX_IN_MEMORY } from '@/utils/constants'
import { dedupedPrepend } from '@/utils/logDedup'
import { logger } from '@/utils/logger'

const auth = useAuthStore()
const logs = ref<RunLogEntry[]>([])
const children = ref(true)
const autoScroll = ref(true)
const level = ref('')
const keyword = ref('')
const loading = ref(true)
const sseEndpoint = ref<string | null>(null)

const filteredLogCount = computed(() => logs.value.length)

const levelClass = (value: string) => {
  if (value === 'ERROR') return 'error'
  if (value === 'WARNING') return 'warning'
  if (value === 'INFO') return 'info'
  if (value === 'SUCCESS') return 'success'
  return 'default'
}

const formatTime = (time?: string | null) => time ? new Date(time).toLocaleString('zh-CN') : '-'

const fetchLogs = async () => {
  loading.value = true
  try {
    const params = new URLSearchParams({
      limit: String(LOG_PAGE_LIMIT),
      include_children: String(children.value),
    })
    if (level.value) params.set('level', level.value)
    if (keyword.value.trim()) params.set('keyword', keyword.value.trim())

    const data = await auth.request<{ logs: RunLogEntry[] }>(`/runinfo/logs?${params.toString()}`)
    logs.value = (data.logs || []).map((item) => ({
      ...item,
      displayTime: formatTime(item.time),
    }))
  } catch (err) {
    logger.error('Failed to fetch logs', err)
  } finally {
    loading.value = false
  }
}

const {
  isConnected: sseConnected,
  retryCount: sseRetryCount,
  connect: connectSSE,
  disconnect: disconnectSSE,
} = useSSE<RunLogEntry>(sseEndpoint, {
  onEvent: (event) => {
    if (event.type !== 'message') return
    logs.value = dedupedPrepend(logs.value, {
      ...event.data,
      displayTime: formatTime(event.data.time),
    }, LOG_MAX_IN_MEMORY)
    if (autoScroll.value) {
      requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: 'smooth' }))
    }
  },
})

const refreshStream = async () => {
  await fetchLogs()
  buildSseEndpoint()
  disconnectSSE()
  connectSSE()
}

const buildSseEndpoint = () => {
  const params = new URLSearchParams({ include_children: String(children.value) })
  if (level.value) params.set('level', level.value)
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  sseEndpoint.value = `/runinfo/logs/stream?${params.toString()}`
}

onMounted(async () => {
  await fetchLogs()
  buildSseEndpoint()
  connectSSE()
})
onBeforeUnmount(() => disconnectSSE())
</script>

<template>
  <div class="space-y-8">
    <UiCard>
      <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between mb-6">
        <div>
          <h2 class="text-lg font-semibold text-gray-900">实时日志</h2>
          <p class="mt-1 text-sm text-slate-500">支持按级别、关键词和是否包含子任务过滤。</p>
        </div>
        <div class="flex items-center gap-3">
          <UiBadge v-if="sseConnected" variant="success">
            <SignalIcon class="mr-1 h-3 w-3" aria-hidden="true" />实时更新
          </UiBadge>
          <UiBadge v-else variant="warning">
            <SignalSlashIcon class="mr-1 h-3 w-3" aria-hidden="true" />
            {{ sseRetryCount > 0 ? `重连中 (${sseRetryCount})…` : '未连接' }}
          </UiBadge>
          <UiBadge variant="default">{{ filteredLogCount }} 条</UiBadge>
        </div>
      </div>

      <div class="mb-6 grid gap-3 md:grid-cols-[minmax(0,1fr)_180px_auto_auto_auto]">
        <div class="relative">
          <label for="logs-search" class="sr-only">搜索日志</label>
          <div class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
            <MagnifyingGlassIcon class="h-5 w-5 text-gray-400" aria-hidden="true" />
          </div>
          <input id="logs-search" v-model="keyword" type="text" placeholder="搜索消息、任务 ID、描述" class="block w-full rounded-[18px] border-0 bg-slate-50 py-3 pl-10 pr-4 text-slate-900 ring-1 ring-inset ring-slate-200 placeholder:text-slate-400 focus:ring-2 focus:ring-primary-600" />
        </div>
        <div>
          <label for="logs-level" class="sr-only">日志级别</label>
          <select id="logs-level" v-model="level" class="block w-full rounded-[18px] border-0 bg-slate-50 px-4 py-3 text-slate-900 ring-1 ring-inset ring-slate-200 focus:ring-2 focus:ring-primary-600">
            <option value="">全部级别</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>
        </div>
        <label class="flex items-center gap-2 rounded-[18px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
          <input type="checkbox" v-model="children" class="h-4 w-4 rounded border-slate-300 text-primary-600 focus:ring-primary-600" />
          <span>包含子任务</span>
        </label>
        <label class="flex items-center gap-2 rounded-[18px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
          <input type="checkbox" v-model="autoScroll" class="h-4 w-4 rounded border-slate-300 text-primary-600 focus:ring-primary-600" />
          <span>自动滚动</span>
        </label>
        <UiButton variant="secondary" :loading="loading" @click="refreshStream">
          <ArrowPathIcon class="mr-2 h-4 w-4" />
          刷新
        </UiButton>
      </div>

      <div v-if="loading && logs.length === 0" class="space-y-3">
        <div v-for="i in 6" :key="i" class="h-16 animate-pulse rounded-[20px] bg-slate-100"></div>
      </div>

      <div v-else-if="logs.length === 0" class="text-center py-12 text-gray-500">
        <p>暂无日志</p>
      </div>

      <div v-else class="overflow-hidden rounded-[24px] border border-slate-200 bg-white shadow-[0_10px_24px_-18px_rgba(15,23,42,0.28)]">
        <div class="overflow-x-auto">
          <table class="min-w-full divide-y divide-slate-200" role="grid" aria-label="实时日志列表">
            <thead class="bg-slate-50/90 sticky top-0 z-10">
              <tr>
                <th scope="col" class="py-3.5 pl-4 pr-3 text-left text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 sm:pl-6">时间</th>
                <th scope="col" class="px-3 py-3.5 text-left text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">级别</th>
                <th scope="col" class="px-3 py-3.5 text-left text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">任务</th>
                <th scope="col" class="px-3 py-3.5 text-left text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">消息</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 bg-white">
              <tr
                v-for="(log, index) in logs"
                :key="`${log.run_id || 'global'}-${log.time || index}-${index}`"
                class="transition-colors hover:bg-slate-50/80 focus-within:bg-slate-50 focus-within:ring-2 focus-within:ring-inset focus-within:ring-primary-400"
                :tabindex="0"
                :aria-label="`${log.displayTime} ${log.level} ${log.message}`"
              >
                <td class="whitespace-nowrap py-4 pl-4 pr-3 text-sm text-slate-600 sm:pl-6">{{ log.displayTime }}</td>
                <td class="whitespace-nowrap px-3 py-4 text-sm text-slate-600">
                  <UiBadge :variant="levelClass(log.level)">{{ log.level || 'INFO' }}</UiBadge>
                </td>
                <td class="px-3 py-4 text-sm text-slate-600">
                  <div class="font-mono text-xs text-slate-500">{{ log.run_id || '-' }}</div>
                  <div class="mt-1 text-sm text-slate-900">{{ log.description || '-' }}</div>
                </td>
                <td class="px-3 py-4 text-sm leading-6 text-slate-900">{{ log.message }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </UiCard>
  </div>
</template>
