<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { MagnifyingGlassIcon, MusicalNoteIcon, PencilSquareIcon, PlusIcon, TrashIcon } from '@heroicons/vue/24/outline'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiDrawer from '@/components/ui/UiDrawer.vue'
import UiSelect, { type UiSelectOption } from '@/components/ui/UiSelect.vue'
import UiScheduleIntervalOverride from '@/components/ui/UiScheduleIntervalOverride.vue'
import UiScheduleTimeOverride from '@/components/ui/UiScheduleTimeOverride.vue'
import Switch from '@/components/Switch.vue'
import { useAuthStore } from '@/stores/auth'
import { formatScheduleConcurrency, formatScheduleInterval, formatScheduleTimeRange } from '@/utils/schedulerDisplay'
import { logger } from '@/utils/logger'

type SubsonicAccountItem = {
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

type SubsonicForm = {
  url: string
  username: string
  password: string
  name: string
  enabled: boolean
  use_proxy: boolean
  time_start: number
  time_end: number
  interval_days: string
  time_range: string
}

type SubsonicSummary = {
  total: number
  enabled: number
  use_proxy: number
  concurrency: number
  time_range: string | null
  interval_days: string | null
  module_enabled: boolean
}

const auth = useAuthStore()
const accounts = ref<SubsonicAccountItem[]>([])
const summary = ref<SubsonicSummary>({ total: 0, enabled: 0, use_proxy: 0, concurrency: 1, time_range: '', interval_days: '', module_enabled: true })
const loading = ref(true)
const saving = ref(false)
const moduleSaving = ref(false)
const deleting = ref<string | null>(null)
const search = ref('')
const statusFilter = ref<'all' | 'enabled' | 'disabled'>('all')
const featureFilter = ref<'all' | 'use_proxy' | 'interval_days' | 'time_range'>('all')
const drawerOpen = ref(false)
const detailOpen = ref(false)
const currentAccount = ref<SubsonicAccountItem | null>(null)
const formMode = ref<'create' | 'edit'>('create')
const formError = ref('')
const pageError = ref('')
const form = ref<SubsonicForm>({
  url: '',
  username: '',
  password: '',
  name: '',
  enabled: true,
  use_proxy: true,
  time_start: 300,
  time_end: 600,
  interval_days: '',
  time_range: '',
})

const filteredAccounts = computed(() => {
  const keyword = search.value.trim().toLowerCase()

  return accounts.value.filter((account) => {
    if (statusFilter.value === 'enabled' && !account.enabled) return false
    if (statusFilter.value === 'disabled' && account.enabled) return false
    if (featureFilter.value !== 'all' && !account[featureFilter.value]) return false

    if (!keyword) return true

    return [account.username, account.url, account.name]
      .some((value) => String(value || '').toLowerCase().includes(keyword))
  })
})

const drawerTitle = computed(() => formMode.value === 'create' ? '新增 Subsonic 账号' : '编辑 Subsonic 账号')
const currentAccountKey = computed(() => currentAccount.value?.id || '')
const accountKey = (account: SubsonicAccountItem) => account.id
const statusFilterOptions: UiSelectOption[] = [
  { label: '全部状态', value: 'all' },
  { label: '仅启用', value: 'enabled' },
  { label: '仅停用', value: 'disabled' },
]
const featureFilterOptions: UiSelectOption[] = [
  { label: '全部特性', value: 'all' },
  { label: '使用代理', value: 'use_proxy' },
  { label: '单独间隔', value: 'interval_days' },
  { label: '单独时段', value: 'time_range' },
]
const summaryDisplay = computed(() => ({
  timeRange: formatScheduleTimeRange(summary.value.time_range),
  interval: formatScheduleInterval(summary.value.interval_days),
  concurrency: formatScheduleConcurrency(summary.value.concurrency),
}))
const accountDetailItems = computed(() => {
  if (!currentAccount.value) {
    return []
  }

  return [
    { label: '用户名', value: currentAccount.value.username },
    { label: '服务地址', value: currentAccount.value.url },
    { label: '显示名称', value: currentAccount.value.name || '-' },
    { label: '播放时长', value: Array.isArray(currentAccount.value.time) ? `${currentAccount.value.time[0]} - ${currentAccount.value.time[1]} 秒` : '-' },
    { label: '单独间隔', value: formatScheduleInterval(currentAccount.value.interval_days) },
    { label: '单独时段', value: formatScheduleTimeRange(currentAccount.value.time_range) },
    { label: '使用代理', value: currentAccount.value.use_proxy ? '是' : '否' },
  ]
})

const applyForm = (account?: SubsonicAccountItem | null) => {
  const time = Array.isArray(account?.time) && account?.time.length >= 2 ? account.time : [300, 600]
  form.value = {
    url: account?.url || '',
    username: account?.username || '',
    password: '',
    name: account?.name || '',
    enabled: account?.enabled ?? true,
    use_proxy: account?.use_proxy ?? true,
    time_start: Number(time[0] || 300),
    time_end: Number(time[1] || 600),
    interval_days: account?.interval_days || '',
    time_range: account?.time_range || '',
  }
}

const fetchAccounts = async () => {
  loading.value = true
  pageError.value = ''
  try {
    const data = await auth.request<{ accounts: SubsonicAccountItem[], summary: SubsonicSummary }>('/subsonic/accounts')
    accounts.value = data.accounts || []
    summary.value = data.summary || summary.value
  } catch (error) {
    logger.error('Failed to fetch subsonic accounts', error)
    pageError.value = logger.message(error, '账号列表加载失败')
  } finally {
    loading.value = false
  }
}

const saveSubsonicModuleSetting = async (enabled: boolean) => {
  moduleSaving.value = true
  pageError.value = ''
  try {
    await auth.request('/subsonic/settings', {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    })
    await fetchAccounts()
  } catch (error) {
    logger.error('Failed to save subsonic module setting', error)
    pageError.value = logger.message(error, '全局保活设置保存失败')
    await fetchAccounts()
  } finally {
    moduleSaving.value = false
  }
}

const openCreateDrawer = () => {
  formMode.value = 'create'
  currentAccount.value = null
  formError.value = ''
  applyForm(null)
  drawerOpen.value = true
}

const openEditDrawer = (account: SubsonicAccountItem) => {
  formMode.value = 'edit'
  currentAccount.value = account
  formError.value = ''
  applyForm(account)
  drawerOpen.value = true
}

const openDetailDrawer = async (account: SubsonicAccountItem) => {
  pageError.value = ''
  try {
    const data = await auth.request<{ account: SubsonicAccountItem }>(`/subsonic/accounts/detail?key=${encodeURIComponent(accountKey(account))}`)
    currentAccount.value = data.account
    detailOpen.value = true
  } catch (error) {
    logger.error('Failed to fetch subsonic account detail', error)
    pageError.value = logger.message(error, '账号详情加载失败')
  }
}

const submitForm = async () => {
  saving.value = true
  formError.value = ''

  if (!form.value.url.trim()) {
    formError.value = '请输入服务地址'
    saving.value = false
    return
  }

  if (!form.value.username.trim()) {
    formError.value = '请输入用户名'
    saving.value = false
    return
  }

  if (formMode.value === 'create' && !form.value.password) {
    formError.value = '创建账号时必须填写密码'
    saving.value = false
    return
  }

  if (form.value.time_start <= 0 || form.value.time_end <= 0 || form.value.time_end < form.value.time_start) {
    formError.value = '播放时长范围无效'
    saving.value = false
    return
  }

  const payload = {
    url: form.value.url,
    username: form.value.username,
    password: form.value.password,
    name: form.value.name || null,
    enabled: form.value.enabled,
    use_proxy: form.value.use_proxy,
    time: [form.value.time_start, form.value.time_end],
    interval_days: form.value.interval_days || null,
    time_range: form.value.time_range || null,
  }

  try {
    if (formMode.value === 'create') {
      await auth.request('/subsonic/accounts', { method: 'POST', body: JSON.stringify(payload) })
    } else {
      await auth.request(`/subsonic/accounts?key=${encodeURIComponent(currentAccountKey.value)}`, { method: 'PUT', body: JSON.stringify(payload) })
    }
    drawerOpen.value = false
    await fetchAccounts()
  } catch (error) {
    logger.error('Failed to save subsonic account', error)
    formError.value = logger.message(error, '保存账号失败')
  } finally {
    saving.value = false
  }
}

const deleteAccount = async (account: SubsonicAccountItem) => {
  const key = accountKey(account)
  deleting.value = key
  pageError.value = ''
  try {
    await auth.request(`/subsonic/accounts?key=${encodeURIComponent(key)}`, { method: 'DELETE' })
    if (currentAccountKey.value === key) {
      currentAccount.value = null
      detailOpen.value = false
    }
    await fetchAccounts()
  } catch (error) {
    logger.error('Failed to delete subsonic account', error)
    pageError.value = logger.message(error, '删除账号失败')
  } finally {
    deleting.value = null
  }
}

onMounted(() => {
  fetchAccounts()
})
</script>

<template>
  <div class="space-y-8">
    <section class="overflow-hidden rounded-[30px] border border-orange-200/70 bg-gradient-to-br from-orange-50 via-white to-amber-50 shadow-[0_24px_80px_-40px_rgba(217,119,6,0.28)]">
      <div class="px-6 py-7 sm:px-8">
        <div class="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
        <div class="space-y-3">
          <div class="inline-flex items-center gap-2 rounded-full bg-orange-100 px-3 py-1 text-xs font-semibold uppercase tracking-[0.22em] text-orange-700 ring-1 ring-orange-200">
            <MusicalNoteIcon class="h-4 w-4" aria-hidden="true" />
            Subsonic
          </div>
          <div>
            <h1 class="text-2xl font-semibold tracking-tight text-slate-950 sm:text-3xl">Subsonic</h1>
            <p class="mt-2 max-w-2xl text-sm leading-6 text-slate-600">管理账号与全局播放调度策略。</p>
          </div>
        </div>
        <div class="inline-flex items-center gap-3 self-start rounded-full border border-white/80 bg-white/85 px-4 py-2 shadow-sm ring-1 ring-orange-100 sm:mt-1 sm:self-auto">
          <span class="text-sm font-medium text-slate-900">启用</span>
          <Switch :model-value="summary.module_enabled" :disabled="moduleSaving" size="sm" @change="saveSubsonicModuleSetting" />
        </div>
        </div>
        <div class="mt-6 rounded-[24px] border border-white/80 bg-white/80 px-5 py-4 shadow-sm ring-1 ring-orange-100">
          <p class="text-xs uppercase tracking-[0.18em] text-slate-400">运行时间</p>
          <div class="mt-4 grid gap-3 sm:grid-cols-3 sm:gap-4">
            <div>
              <p class="text-xs font-medium uppercase tracking-[0.14em] text-slate-400">时段</p>
              <p class="mt-1 text-sm font-semibold text-slate-950">{{ summaryDisplay.timeRange }}</p>
            </div>
            <div>
              <p class="text-xs font-medium uppercase tracking-[0.14em] text-slate-400">间隔</p>
              <p class="mt-1 text-sm font-semibold text-slate-950">{{ summaryDisplay.interval }}</p>
            </div>
            <div>
              <p class="text-xs font-medium uppercase tracking-[0.14em] text-slate-400">并发</p>
              <p class="mt-1 text-sm font-semibold text-slate-950">{{ summaryDisplay.concurrency }}</p>
            </div>
          </div>
        </div>
      </div>
    </section>

    <UiCard class="overflow-hidden border-slate-200/70 bg-white/90">
      <template #header>
        <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 class="text-lg font-semibold tracking-tight text-slate-950">账号列表</h2>
            <p class="mt-1 text-sm text-slate-500">按账号查看播放时长、代理与调度覆盖。</p>
          </div>
          <div class="flex items-center gap-3">
            <div class="inline-flex items-center rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-500 ring-1 ring-slate-200">
              共 {{ filteredAccounts.length }} / {{ accounts.length }} 个账号
            </div>
            <UiButton size="sm" @click="openCreateDrawer">
              <PlusIcon class="mr-2 h-4 w-4" />
              新增账号
            </UiButton>
          </div>
        </div>
      </template>

      <div class="rounded-[26px] border border-slate-200/70 bg-slate-50/80 p-5 sm:p-6">
        <div class="mb-5 grid gap-3 md:grid-cols-[minmax(0,1fr)_180px_200px]">
          <div class="relative">
            <label for="subsonic-search" class="sr-only">搜索账号</label>
            <div class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
              <MagnifyingGlassIcon class="h-5 w-5 text-gray-400" />
            </div>
            <input id="subsonic-search" v-model="search" type="text" placeholder="搜索用户名、域名" class="block w-full rounded-[18px] border-0 bg-white py-3 pl-10 pr-4 text-slate-900 ring-1 ring-inset ring-slate-200 placeholder:text-slate-400 focus:ring-2 focus:ring-primary-600" />
          </div>
          <UiSelect v-model="statusFilter" :options="statusFilterOptions" class="w-full" />
          <UiSelect v-model="featureFilter" :options="featureFilterOptions" class="w-full" />
        </div>

        <div v-if="pageError" class="mb-4 rounded-[20px] border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {{ pageError }}
        </div>

        <div v-if="loading" class="rounded-[24px] border border-dashed border-slate-300 bg-white/70 px-6 py-16 text-center">
          <div class="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-orange-50 text-orange-500 ring-1 ring-orange-100">
            <div class="h-7 w-7 animate-spin rounded-full border-2 border-orange-200 border-t-orange-500"></div>
          </div>
          <p class="mt-5 text-base font-medium text-slate-700">正在加载 Subsonic 账号</p>
          <p class="mt-2 text-sm text-slate-500">请稍候，列表准备好后会直接显示在这里。</p>
        </div>

        <div v-else-if="filteredAccounts.length === 0" class="rounded-[24px] border border-dashed border-slate-300 bg-white/70 px-6 py-16 text-center">
          <MusicalNoteIcon class="mx-auto mb-4 h-16 w-16 text-orange-200" />
          <p class="text-base font-medium text-slate-700">没有符合条件的 Subsonic 账号</p>
          <p class="mt-2 text-sm text-slate-500">调整筛选条件或新增账号后再试。</p>
        </div>

        <div v-else class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <UiCard v-for="account in filteredAccounts" :key="accountKey(account)" hover>
            <div class="mb-4 flex items-start justify-between gap-4">
              <div class="flex items-center gap-3">
                <div class="flex h-12 w-12 items-center justify-center rounded-[20px] bg-gradient-to-br from-orange-500 to-amber-500 shadow-lg shadow-orange-500/20">
                  <MusicalNoteIcon class="h-6 w-6 text-white" />
                </div>
                <div>
                  <div class="font-semibold text-slate-900">{{ account.username }}</div>
                  <div class="mt-0.5 max-w-[200px] truncate text-xs text-slate-500">{{ account.url }}</div>
                </div>
              </div>
              <UiBadge :variant="account.enabled ? 'success' : 'default'">
                {{ account.enabled ? '启用' : '停用' }}
              </UiBadge>
            </div>

            <div class="flex flex-wrap gap-2">
              <UiBadge :variant="account.use_proxy ? 'info' : 'default'">代理</UiBadge>
              <UiBadge :variant="account.interval_days ? 'warning' : 'default'">单独间隔</UiBadge>
              <UiBadge :variant="account.time_range ? 'success' : 'default'">单独时段</UiBadge>
            </div>

            <div class="mt-5 flex flex-wrap gap-2">
              <UiButton size="sm" variant="ghost" @click="openDetailDrawer(account)">查看</UiButton>
              <UiButton size="sm" variant="secondary" @click="openEditDrawer(account)">
                <PencilSquareIcon class="mr-2 h-4 w-4" />
                编辑
              </UiButton>
              <UiButton size="sm" variant="danger" :loading="deleting === accountKey(account)" @click="deleteAccount(account)">
                <TrashIcon class="mr-2 h-4 w-4" />
                删除
              </UiButton>
            </div>
          </UiCard>
        </div>
      </div>
    </UiCard>

    <UiDrawer v-model="drawerOpen" :title="drawerTitle">
      <div class="space-y-6">
        <div v-if="formError" class="rounded-[20px] border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {{ formError }}
        </div>

        <UiCard>
          <div class="grid gap-4 sm:grid-cols-2">
            <label class="space-y-2 text-sm text-slate-600 sm:col-span-2">
              <span class="font-medium text-slate-900">服务地址</span>
              <input v-model="form.url" type="text" placeholder="https://demo.example.com" class="block w-full rounded-[18px] border-0 bg-slate-50 px-4 py-3 text-slate-900 ring-1 ring-inset ring-slate-200 focus:ring-2 focus:ring-primary-600" />
            </label>
            <label class="space-y-2 text-sm text-slate-600">
              <span class="font-medium text-slate-900">用户名</span>
              <input v-model="form.username" type="text" class="block w-full rounded-[18px] border-0 bg-slate-50 px-4 py-3 text-slate-900 ring-1 ring-inset ring-slate-200 focus:ring-2 focus:ring-primary-600" />
            </label>
            <label class="space-y-2 text-sm text-slate-600">
              <span class="font-medium text-slate-900">密码</span>
              <input v-model="form.password" type="password" :placeholder="formMode === 'edit' ? '留空则保持原密码' : ''" class="block w-full rounded-[18px] border-0 bg-slate-50 px-4 py-3 text-slate-900 ring-1 ring-inset ring-slate-200 focus:ring-2 focus:ring-primary-600" />
            </label>
            <label class="space-y-2 text-sm text-slate-600 sm:col-span-2">
              <span class="font-medium text-slate-900">显示名称</span>
              <input v-model="form.name" type="text" placeholder="可选" class="block w-full rounded-[18px] border-0 bg-slate-50 px-4 py-3 text-slate-900 ring-1 ring-inset ring-slate-200 focus:ring-2 focus:ring-primary-600" />
            </label>
          </div>
        </UiCard>

        <UiCard>
          <div class="grid gap-3 sm:grid-cols-2">
            <label class="flex items-center justify-between gap-3 rounded-[18px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              <span>启用账号</span>
              <input v-model="form.enabled" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-primary-600 focus:ring-primary-600" />
            </label>
            <label class="flex items-center justify-between gap-3 rounded-[18px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              <span>使用代理</span>
              <input v-model="form.use_proxy" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-primary-600 focus:ring-primary-600" />
            </label>
          </div>
        </UiCard>

        <UiCard>
          <h3 class="text-base font-semibold text-slate-950">播放与调度</h3>
          <div class="mt-4 space-y-6">
            <div class="space-y-4">
              <div class="space-y-1.5">
                <p class="text-sm font-medium text-slate-900">播放时长随机范围</p>
                <p class="text-xs leading-5 text-slate-400">系统会在这个秒数区间内随机选择本次需要补足的播放时长。</p>
              </div>
              <div class="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] sm:items-end">
                <label class="space-y-2 text-sm text-slate-600">
                  <span class="text-xs font-medium text-slate-500">起始时长</span>
                  <input v-model.number="form.time_start" type="number" min="1" class="block w-full rounded-[16px] border-0 bg-white px-4 py-3 text-sm text-slate-900 ring-1 ring-inset ring-slate-200 focus:ring-2 focus:ring-primary-600" />
                </label>
                <div class="pb-3 text-center text-lg font-semibold text-slate-300">~</div>
                <label class="space-y-2 text-sm text-slate-600">
                  <span class="text-xs font-medium text-slate-500">结束时长</span>
                  <input v-model.number="form.time_end" type="number" min="1" class="block w-full rounded-[16px] border-0 bg-white px-4 py-3 text-sm text-slate-900 ring-1 ring-inset ring-slate-200 focus:ring-2 focus:ring-primary-600" />
                </label>
              </div>
            </div>
            <div class="border-t border-slate-200 pt-5">
              <UiScheduleIntervalOverride v-model="form.interval_days" variant="plain" label="单独间隔天数" helper-text="可让当前账号沿用全局间隔，或单独指定固定天数 / 区间天数。" />
            </div>
            <div class="border-t border-slate-200 pt-5">
              <UiScheduleTimeOverride v-model="form.time_range" variant="plain" label="单独执行时段" helper-text="可让当前账号沿用全局时段，或单独指定每天固定时间 / 时间范围。" />
            </div>
          </div>
        </UiCard>

        <div class="flex justify-end gap-3">
          <UiButton variant="outline" @click="drawerOpen = false">取消</UiButton>
          <UiButton :loading="saving" @click="submitForm">保存账号</UiButton>
        </div>
      </div>
    </UiDrawer>

    <UiDrawer v-model="detailOpen" title="账号详情">
      <div v-if="currentAccount" class="space-y-6">
        <UiCard>
          <div class="flex items-start justify-between gap-4">
            <div>
              <h3 class="text-lg font-semibold text-slate-950">{{ currentAccount.username }}</h3>
              <p class="mt-1 break-all text-sm text-slate-500">{{ currentAccount.url }}</p>
            </div>
            <UiBadge :variant="currentAccount.enabled ? 'success' : 'default'">
              {{ currentAccount.enabled ? '启用' : '停用' }}
            </UiBadge>
          </div>
          <div class="mt-5 flex flex-wrap gap-2">
            <UiBadge :variant="currentAccount.use_proxy ? 'info' : 'default'">代理</UiBadge>
            <UiBadge :variant="currentAccount.interval_days ? 'warning' : 'default'">单独间隔</UiBadge>
            <UiBadge :variant="currentAccount.time_range ? 'success' : 'default'">单独时段</UiBadge>
          </div>
        </UiCard>

        <UiCard>
          <div class="grid gap-4 sm:grid-cols-2">
            <div v-for="item in accountDetailItems" :key="item.label" class="rounded-[18px] border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">{{ item.label }}</p>
              <p class="mt-2 break-all text-sm font-medium text-slate-900">{{ item.value }}</p>
            </div>
          </div>
        </UiCard>

        <div class="flex justify-end gap-3">
          <UiButton variant="secondary" @click="openEditDrawer(currentAccount)">
            <PencilSquareIcon class="mr-2 h-4 w-4" />
            编辑
          </UiButton>
        </div>
      </div>
    </UiDrawer>
  </div>
</template>
