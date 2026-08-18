<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ChatBubbleLeftRightIcon, ChevronDownIcon, InformationCircleIcon, MagnifyingGlassIcon, PencilSquareIcon, PlusIcon, TrashIcon } from '@heroicons/vue/24/outline'
import UiCard from '@/components/ui/UiCard.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiDrawer from '@/components/ui/UiDrawer.vue'
import UiSelect, { type UiSelectOption } from '@/components/ui/UiSelect.vue'
import Switch from '@/components/Switch.vue'
import UiTooltip from '@/components/ui/UiTooltip.vue'
import { useAuthStore } from '@/stores/auth'
import { logger } from '@/utils/logger'

type TelegramAccountItem = {
  phone: string
  masked_phone: string
  enabled: boolean
  checkiner: boolean
  monitor: boolean
  messager: boolean
  registrar: boolean
  api_id?: string | null
  api_hash?: string | null
  session?: string | null
  site_override?: boolean
  checkiner_config_override?: boolean
  registrar_config_override?: boolean
  last_checkin_status?: 'success' | 'partial_failed' | 'failed' | null
  last_checkin_time?: string | null
}

type TelegramForm = {
  phone: string
  enabled: boolean
  checkiner: boolean
  monitor: boolean
  messager: boolean
  registrar: boolean
  api_id: string
  api_hash: string
  session: string
}

type TelegramSummary = {
  total: number
  enabled: number
  checkiner: number
  monitor: number
  messager: number
  registrar: number
  use_proxy: boolean
  checkiner_enabled: boolean
  monitor_enabled: boolean
  messager_enabled: boolean
  registrar_enabled: boolean
}

const auth = useAuthStore()
const accounts = ref<TelegramAccountItem[]>([])
const summary = ref<TelegramSummary>({
  total: 0,
  enabled: 0,
  checkiner: 0,
  monitor: 0,
  messager: 0,
  registrar: 0,
  use_proxy: true,
  checkiner_enabled: true,
  monitor_enabled: true,
  messager_enabled: true,
  registrar_enabled: true,
})
const loading = ref(true)
const saving = ref(false)
const moduleSaving = ref(false)
const deleting = ref<string | null>(null)
const search = ref('')
const statusFilter = ref<'all' | 'enabled' | 'disabled'>('all')
const checkinResultFilter = ref<'all' | 'success' | 'partial_failed' | 'failed'>('all')
const drawerOpen = ref(false)
const detailOpen = ref(false)
const currentAccount = ref<TelegramAccountItem | null>(null)
const formMode = ref<'create' | 'edit'>('create')
const formError = ref('')
const pageError = ref('')
const connectionInfoOpen = ref(false)
const form = ref<TelegramForm>({
  phone: '',
  enabled: true,
  checkiner: true,
  monitor: false,
  messager: false,
  registrar: false,
  api_id: '',
  api_hash: '',
  session: '',
})

const filteredAccounts = computed(() => {
  const keyword = search.value.trim().toLowerCase()

  return accounts.value.filter((account) => {
    if (statusFilter.value === 'enabled' && !account.enabled) return false
    if (statusFilter.value === 'disabled' && account.enabled) return false

    if (checkinResultFilter.value !== 'all' && account.last_checkin_status !== checkinResultFilter.value) return false

    if (!keyword) return true

    return [account.phone, account.masked_phone, account.api_id, account.api_hash]
      .some((value) => String(value || '').toLowerCase().includes(keyword))
  })
})

const drawerTitle = computed(() => formMode.value === 'create' ? '新增 Telegram 账号' : '编辑 Telegram 账号')
const statusFilterOptions: UiSelectOption[] = [
  { label: '全部状态', value: 'all' },
  { label: '仅启用', value: 'enabled' },
  { label: '仅停用', value: 'disabled' },
]
const checkinResultFilterOptions: UiSelectOption[] = [
  { label: '全部签到状态', value: 'all' },
  { label: '成功', value: 'success' },
  { label: '部分失败', value: 'partial_failed' },
  { label: '全部失败', value: 'failed' },
]

const accountDetailItems = computed(() => {
  if (!currentAccount.value) {
    return []
  }

  return [
    { label: '手机号', value: currentAccount.value.phone },
    { label: '状态', value: currentAccount.value.enabled ? '启用' : '停用' },
    { label: 'API ID', value: currentAccount.value.api_id || '-' },
    { label: 'API Hash', value: currentAccount.value.api_hash || '-' },
    { label: '会话串', value: currentAccount.value.session ? '已填写' : '未填写' },
    {
      label: '上次签到状态',
      value: currentAccount.value.last_checkin_status === 'success'
        ? '成功'
        : currentAccount.value.last_checkin_status === 'partial_failed'
          ? '部分失败'
          : currentAccount.value.last_checkin_status === 'failed'
            ? '全部失败'
            : '-',
    },
    { label: '单独站点设置', value: currentAccount.value.site_override ? '已设置' : '未设置' },
    { label: '单独签到设置', value: currentAccount.value.checkiner_config_override ? '已设置' : '未设置' },
    { label: '单独抢注设置', value: currentAccount.value.registrar_config_override ? '已设置' : '未设置' },
  ]
})

const applyForm = (account?: TelegramAccountItem | null) => {
  form.value = {
    phone: account?.phone || '',
    enabled: account?.enabled ?? true,
    checkiner: account?.checkiner ?? true,
    monitor: account?.monitor ?? false,
    messager: account?.messager ?? false,
    registrar: account?.registrar ?? false,
    api_id: account?.api_id || '',
    api_hash: account?.api_hash || '',
    session: account?.session || '',
  }
  connectionInfoOpen.value = Boolean(account?.api_id || account?.api_hash || account?.session)
}

const syncConnectionInfoOpen = (event: Event) => {
  connectionInfoOpen.value = (event.currentTarget as HTMLDetailsElement).open
}

const fetchAccounts = async () => {
  loading.value = true
  pageError.value = ''
  try {
    const data = await auth.request<{ accounts: TelegramAccountItem[], summary: TelegramSummary }>('/telegram/accounts')
    accounts.value = data.accounts || []
    summary.value = data.summary || summary.value
  } catch (error) {
    logger.error('Failed to fetch accounts', error)
    pageError.value = logger.message(error, '账号列表加载失败')
  } finally {
    loading.value = false
  }
}

const saveTelegramModuleSettings = async (nextSummary = summary.value) => {
  moduleSaving.value = true
  pageError.value = ''
  try {
    await auth.request('/telegram/settings', {
      method: 'POST',
      body: JSON.stringify({
        checkiner_enabled: nextSummary.checkiner_enabled,
        monitor_enabled: nextSummary.monitor_enabled,
        messager_enabled: nextSummary.messager_enabled,
        registrar_enabled: nextSummary.registrar_enabled,
      }),
    })
    await fetchAccounts()
  } catch (error) {
    logger.error('Failed to save telegram module settings', error)
    pageError.value = logger.message(error, '模块设置保存失败')
    await fetchAccounts()
  } finally {
    moduleSaving.value = false
  }
}

const updateTelegramModule = (
  key: 'checkiner_enabled' | 'monitor_enabled' | 'messager_enabled' | 'registrar_enabled',
  checked: boolean,
) => {
  const nextSummary = { ...summary.value, [key]: checked }
  summary.value = nextSummary
  saveTelegramModuleSettings(nextSummary)
}

const openCreateDrawer = () => {
  formMode.value = 'create'
  formError.value = ''
  applyForm(null)
  drawerOpen.value = true
}

const openEditDrawer = (account: TelegramAccountItem) => {
  formMode.value = 'edit'
  formError.value = ''
  currentAccount.value = account
  applyForm(account)
  drawerOpen.value = true
}

const openDetailDrawer = async (account: TelegramAccountItem) => {
  pageError.value = ''
  try {
    const data = await auth.request<{ account: TelegramAccountItem }>(`/telegram/accounts/${encodeURIComponent(account.phone)}`)
    currentAccount.value = data.account
    detailOpen.value = true
  } catch (error) {
    logger.error('Failed to fetch account detail', error)
    pageError.value = logger.message(error, '账号详情加载失败')
  }
}

const submitForm = async () => {
  saving.value = true
  formError.value = ''

  if (!form.value.phone.trim()) {
    formError.value = '请输入手机号'
    saving.value = false
    return
  }

  if (!form.value.checkiner && !form.value.monitor && !form.value.messager && !form.value.registrar) {
    formError.value = '至少启用一个功能开关'
    saving.value = false
    return
  }

  const payload = {
    ...form.value,
    api_id: form.value.api_id || null,
    api_hash: form.value.api_hash || null,
    session: form.value.session || null,
  }

  try {
    if (formMode.value === 'create') {
      await auth.request('/telegram/accounts', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
    } else {
      await auth.request(`/telegram/accounts/${encodeURIComponent(currentAccount.value?.phone || form.value.phone)}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      })
    }

    drawerOpen.value = false
    currentAccount.value = null
    await fetchAccounts()
  } catch (error) {
    logger.error('Failed to save telegram account', error)
    formError.value = logger.message(error, '保存账号失败')
  } finally {
    saving.value = false
  }
}

const deleteAccount = async (account: TelegramAccountItem) => {
  deleting.value = account.phone
  pageError.value = ''

  try {
    await auth.request(`/telegram/accounts/${encodeURIComponent(account.phone)}`, { method: 'DELETE' })
    if (currentAccount.value?.phone === account.phone) {
      currentAccount.value = null
      detailOpen.value = false
    }
    await fetchAccounts()
  } catch (error) {
    logger.error('Failed to delete telegram account', error)
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
    <section class="overflow-hidden rounded-[30px] border border-sky-200/70 bg-gradient-to-br from-sky-50 via-white to-cyan-50 shadow-[0_24px_80px_-40px_rgba(14,116,144,0.35)]">
      <div class="flex flex-col gap-8 px-6 py-7 sm:px-8 md:flex-row md:items-end md:justify-between">
        <div class="space-y-3">
          <div class="inline-flex items-center gap-2 rounded-full bg-sky-100 px-3 py-1 text-xs font-semibold uppercase tracking-[0.22em] text-sky-700 ring-1 ring-sky-200">
            <ChatBubbleLeftRightIcon class="h-4 w-4" aria-hidden="true" />
            Telegram
          </div>
          <div>
            <h1 class="text-2xl font-semibold tracking-tight text-slate-950 sm:text-3xl">Telegram 账号</h1>
            <p class="mt-2 max-w-2xl text-sm leading-6 text-slate-600">管理签到、监控、水群和抢注相关的 Telegram 账号。</p>
          </div>
        </div>
        <div class="grid min-w-[320px] gap-4 md:min-w-[640px] md:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
          <div class="rounded-[24px] border border-white/80 bg-white/80 px-5 py-4 shadow-sm ring-1 ring-sky-100">
            <div class="flex items-center justify-between gap-3">
              <div>
                <p class="text-xs uppercase tracking-[0.18em] text-slate-400">全局功能开关</p>
                <p class="mt-2 text-sm text-slate-500">分别控制签到、监控、水群和抢注是否参与运行。</p>
              </div>
              <p class="text-sm text-slate-500">共 {{ summary.total }} 个账号</p>
            </div>
            <div class="mt-4 grid gap-3 sm:grid-cols-2">
              <div class="flex items-center justify-between gap-3 rounded-[18px] bg-white px-4 py-3 ring-1 ring-slate-200">
                <div>
                  <p class="text-sm font-medium text-slate-900">签到</p>
                  <p class="mt-1 text-xs text-slate-500">控制 Telegram 签到任务是否执行</p>
                </div>
                <Switch :model-value="summary.checkiner_enabled" :disabled="moduleSaving" size="sm" @change="updateTelegramModule('checkiner_enabled', $event)" />
              </div>
              <div class="flex items-center justify-between gap-3 rounded-[18px] bg-white px-4 py-3 ring-1 ring-slate-200">
                <div>
                  <p class="text-sm font-medium text-slate-900">监控</p>
                  <p class="mt-1 text-xs text-slate-500">控制监控消息与自动处理逻辑</p>
                </div>
                <Switch :model-value="summary.monitor_enabled" :disabled="moduleSaving" size="sm" @change="updateTelegramModule('monitor_enabled', $event)" />
              </div>
              <div class="flex items-center justify-between gap-3 rounded-[18px] bg-white px-4 py-3 ring-1 ring-slate-200">
                <div>
                  <p class="text-sm font-medium text-slate-900">水群</p>
                  <p class="mt-1 text-xs text-slate-500">控制消息发送任务是否参与调度</p>
                </div>
                <Switch :model-value="summary.messager_enabled" :disabled="moduleSaving" size="sm" @change="updateTelegramModule('messager_enabled', $event)" />
              </div>
              <div class="flex items-center justify-between gap-3 rounded-[18px] bg-white px-4 py-3 ring-1 ring-slate-200">
                <div>
                  <p class="text-sm font-medium text-slate-900">抢注</p>
                  <p class="mt-1 text-xs text-slate-500">控制用户名抢注任务是否启用</p>
                </div>
                <Switch :model-value="summary.registrar_enabled" :disabled="moduleSaving" size="sm" @change="updateTelegramModule('registrar_enabled', $event)" />
              </div>
            </div>
          </div>
          <div class="rounded-[24px] border border-white/80 bg-white/80 px-5 py-4 shadow-sm ring-1 ring-sky-100">
            <p class="text-xs uppercase tracking-[0.18em] text-slate-400">运行概览</p>
            <div class="mt-4 grid gap-3 sm:grid-cols-2">
              <div>
                <p class="text-xs font-medium uppercase tracking-[0.14em] text-slate-400">已启用账号</p>
                <p class="mt-1 text-2xl font-semibold text-slate-950">{{ summary.enabled }}</p>
              </div>
              <div>
                <p class="text-xs font-medium uppercase tracking-[0.14em] text-slate-400">统一代理</p>
                <p class="mt-1 text-sm font-semibold text-slate-950">{{ summary.use_proxy ? '已启用' : '未启用' }}</p>
              </div>
            </div>
            <div class="mt-4 grid gap-3 sm:grid-cols-2">
              <div>
                <p class="text-xs font-medium uppercase tracking-[0.14em] text-slate-400">签到账号</p>
                <p class="mt-1 text-sm font-semibold text-slate-950">{{ summary.checkiner }}</p>
              </div>
              <div>
                <p class="text-xs font-medium uppercase tracking-[0.14em] text-slate-400">监控账号</p>
                <p class="mt-1 text-sm font-semibold text-slate-950">{{ summary.monitor }}</p>
              </div>
              <div>
                <p class="text-xs font-medium uppercase tracking-[0.14em] text-slate-400">水群账号</p>
                <p class="mt-1 text-sm font-semibold text-slate-950">{{ summary.messager }}</p>
              </div>
              <div>
                <p class="text-xs font-medium uppercase tracking-[0.14em] text-slate-400">抢注账号</p>
                <p class="mt-1 text-sm font-semibold text-slate-950">{{ summary.registrar }}</p>
              </div>
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
            <p class="mt-1 text-sm text-slate-500">按账号查看当前启用模块。</p>
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

    <div class="mb-5 grid gap-3 md:grid-cols-[minmax(0,1fr)_180px_180px]">
      <div class="relative">
        <label for="telegram-search" class="sr-only">搜索账号</label>
        <div class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
          <MagnifyingGlassIcon class="h-5 w-5 text-gray-400" />
        </div>
        <input id="telegram-search" v-model="search" type="text" placeholder="搜索手机号、API ID" class="block w-full rounded-[18px] border-0 bg-white py-3 pl-10 pr-4 text-slate-900 ring-1 ring-inset ring-slate-200 placeholder:text-slate-400 focus:ring-2 focus:ring-primary-600" />
      </div>
      <UiSelect v-model="statusFilter" :options="statusFilterOptions" class="w-full" />
      <UiSelect v-model="checkinResultFilter" :options="checkinResultFilterOptions" class="w-full" />
    </div>

    <div v-if="pageError" class="mb-4 rounded-[20px] border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
      {{ pageError }}
    </div>

    <div v-if="loading" class="rounded-[24px] border border-dashed border-slate-300 bg-white/70 px-6 py-16 text-center">
      <div class="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-sky-50 text-sky-500 ring-1 ring-sky-100">
        <div class="h-7 w-7 animate-spin rounded-full border-2 border-sky-200 border-t-sky-500"></div>
      </div>
      <p class="mt-5 text-base font-medium text-slate-700">正在加载 Telegram 账号</p>
      <p class="mt-2 text-sm text-slate-500">请稍候，列表准备好后会直接显示在这里。</p>
    </div>

    <div v-else-if="filteredAccounts.length === 0" class="rounded-[24px] border border-dashed border-slate-300 bg-white/70 px-6 py-16 text-center">
      <ChatBubbleLeftRightIcon class="mx-auto mb-4 h-16 w-16 text-sky-200" />
      <p class="text-base font-medium text-slate-700">没有符合条件的 Telegram 账号</p>
      <p class="mt-2 text-sm text-slate-500">调整筛选条件或新增账号后再试。</p>
    </div>

    <div v-else class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      <UiCard v-for="account in filteredAccounts" :key="account.phone" hover>
        <div class="flex items-start justify-between gap-4 mb-4">
          <div class="flex items-center gap-3">
            <div class="flex h-12 w-12 items-center justify-center rounded-[20px] bg-gradient-to-br from-sky-500 to-cyan-500 shadow-lg shadow-sky-500/20">
              <ChatBubbleLeftRightIcon class="w-6 h-6 text-white" />
            </div>
            <div>
              <div class="font-semibold text-slate-900">{{ account.masked_phone || account.phone }}</div>
              <div class="mt-0.5 text-xs text-slate-500">Telegram</div>
            </div>
          </div>
          <UiBadge :variant="account.enabled ? 'success' : 'default'">
            {{ account.enabled ? '启用' : '停用' }}
          </UiBadge>
        </div>

        <div class="flex flex-wrap gap-2">
          <UiBadge :variant="account.checkiner ? 'success' : 'default'">签到</UiBadge>
          <UiBadge :variant="account.monitor ? 'info' : 'default'">监控</UiBadge>
          <UiBadge :variant="account.messager ? 'warning' : 'default'">水群</UiBadge>
          <UiBadge :variant="account.registrar ? 'error' : 'default'">抢注</UiBadge>
          <UiBadge
            v-if="account.last_checkin_status"
            :variant="account.last_checkin_status === 'success' ? 'success' : account.last_checkin_status === 'partial_failed' ? 'warning' : 'error'"
          >
            {{ account.last_checkin_status === 'success' ? '签到成功' : account.last_checkin_status === 'partial_failed' ? '部分失败' : '全部失败' }}
          </UiBadge>
        </div>

        <div class="mt-5 flex flex-wrap gap-2">
          <UiButton size="sm" variant="ghost" @click="openDetailDrawer(account)">
            查看
          </UiButton>
          <UiButton size="sm" variant="secondary" @click="openEditDrawer(account)">
            <PencilSquareIcon class="mr-2 h-4 w-4" />
            编辑
          </UiButton>
          <UiButton size="sm" variant="danger" :loading="deleting === account.phone" @click="deleteAccount(account)">
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
              <span class="flex items-center gap-1.5 font-medium text-slate-900">
                <span>手机号</span>
                <UiTooltip text="用于识别这个 Telegram 账号，请填写带国家区号的完整手机号，例如 +86 13800000000。" width-class="w-72">
                  <button type="button" class="inline-flex h-4 w-4 items-center justify-center rounded-full text-slate-400 transition hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-600 focus-visible:ring-offset-2" aria-label="查看手机号填写说明">
                    <InformationCircleIcon class="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                </UiTooltip>
              </span>
              <input v-model="form.phone" type="text" placeholder="+8613800000000" class="block w-full rounded-[18px] border-0 bg-slate-50 px-4 py-3 text-slate-900 ring-1 ring-inset ring-slate-200 focus:ring-2 focus:ring-primary-600" />
            </label>
            <label class="flex items-center justify-between gap-3 rounded-[18px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              <span class="flex items-center gap-1.5">
                <span>启用账号</span>
                <UiTooltip text="关闭后，这个账号不会参与签到、监控、水群或抢注任务。" width-class="w-64">
                  <button type="button" class="inline-flex h-4 w-4 items-center justify-center rounded-full text-slate-400 transition hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-600 focus-visible:ring-offset-2" aria-label="查看启用账号说明">
                    <InformationCircleIcon class="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                </UiTooltip>
              </span>
              <input v-model="form.enabled" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-primary-600 focus:ring-primary-600" />
            </label>
          </div>
        </UiCard>

        <UiCard>
          <h3 class="text-base font-semibold text-slate-950">功能开关</h3>
          <div class="mt-4 grid gap-3 sm:grid-cols-2">
            <label class="flex items-center justify-between gap-3 rounded-[18px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              <span class="flex items-center gap-1.5">
                <span>签到</span>
                <UiTooltip text="开启后，这个账号会参与机器人签到任务。" width-class="w-56">
                  <button type="button" class="inline-flex h-4 w-4 items-center justify-center rounded-full text-slate-400 transition hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-600 focus-visible:ring-offset-2" aria-label="查看签到功能说明">
                    <InformationCircleIcon class="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                </UiTooltip>
              </span>
              <input v-model="form.checkiner" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-primary-600 focus:ring-primary-600" />
            </label>
            <label class="flex items-center justify-between gap-3 rounded-[18px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              <span class="flex items-center gap-1.5">
                <span>监控</span>
                <UiTooltip text="开启后，这个账号会参与群组监控、抢邀请码和答题等任务。" width-class="w-64">
                  <button type="button" class="inline-flex h-4 w-4 items-center justify-center rounded-full text-slate-400 transition hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-600 focus-visible:ring-offset-2" aria-label="查看监控功能说明">
                    <InformationCircleIcon class="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                </UiTooltip>
              </span>
              <input v-model="form.monitor" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-primary-600 focus:ring-primary-600" />
            </label>
            <label class="flex items-center justify-between gap-3 rounded-[18px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              <span class="flex items-center gap-1.5">
                <span>水群</span>
                <UiTooltip text="开启后，这个账号会参与自动发言任务，使用前请确认风险。" width-class="w-64">
                  <button type="button" class="inline-flex h-4 w-4 items-center justify-center rounded-full text-slate-400 transition hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-600 focus-visible:ring-offset-2" aria-label="查看水群功能说明">
                    <InformationCircleIcon class="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                </UiTooltip>
              </span>
              <input v-model="form.messager" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-primary-600 focus:ring-primary-600" />
            </label>
            <label class="flex items-center justify-between gap-3 rounded-[18px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              <span class="flex items-center gap-1.5">
                <span>抢注</span>
                <UiTooltip text="开启后，这个账号会参与用户名、名额或邀请资格相关的抢注任务。" width-class="w-64">
                  <button type="button" class="inline-flex h-4 w-4 items-center justify-center rounded-full text-slate-400 transition hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-600 focus-visible:ring-offset-2" aria-label="查看抢注功能说明">
                    <InformationCircleIcon class="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                </UiTooltip>
              </span>
              <input v-model="form.registrar" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-primary-600 focus:ring-primary-600" />
            </label>
          </div>
        </UiCard>

        <UiCard>
          <details :open="connectionInfoOpen" class="group" @toggle="syncConnectionInfoOpen">
            <summary class="flex cursor-pointer list-none items-start justify-between gap-4 rounded-[18px] bg-slate-50 px-4 py-4 [&::-webkit-details-marker]:hidden">
              <div>
                <h3 class="text-base font-semibold text-slate-950">连接信息</h3>
                <p class="mt-1 text-sm text-slate-500">API ID、API Hash 和 Session 按需填写，不需要时可以保持收起。</p>
              </div>
              <span class="inline-flex items-center gap-2 text-sm font-medium text-slate-500">
                <span>{{ connectionInfoOpen ? '收起' : '展开' }}</span>
                <ChevronDownIcon class="h-5 w-5 transition duration-200" :class="connectionInfoOpen ? 'rotate-180' : ''" aria-hidden="true" />
              </span>
            </summary>

            <div class="mt-4 grid gap-4 sm:grid-cols-2">
              <label class="space-y-2 text-sm text-slate-600">
                <span class="font-medium text-slate-900">API ID</span>
                <input v-model="form.api_id" type="text" placeholder="可选" class="block w-full rounded-[18px] border-0 bg-slate-50 px-4 py-3 text-slate-900 ring-1 ring-inset ring-slate-200 focus:ring-2 focus:ring-primary-600" />
              </label>
              <label class="space-y-2 text-sm text-slate-600">
                <span class="font-medium text-slate-900">API Hash</span>
                <input v-model="form.api_hash" type="text" placeholder="可选" class="block w-full rounded-[18px] border-0 bg-slate-50 px-4 py-3 text-slate-900 ring-1 ring-inset ring-slate-200 focus:ring-2 focus:ring-primary-600" />
              </label>
              <label class="space-y-2 text-sm text-slate-600 sm:col-span-2">
                <span class="font-medium text-slate-900">Session</span>
                <textarea v-model="form.session" rows="4" placeholder="可选，如已有 Session 可直接粘贴" class="block w-full rounded-[18px] border-0 bg-slate-50 px-4 py-3 text-slate-900 ring-1 ring-inset ring-slate-200 focus:ring-2 focus:ring-primary-600"></textarea>
              </label>
            </div>
          </details>
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
              <h3 class="text-lg font-semibold text-slate-950">{{ currentAccount.masked_phone || currentAccount.phone }}</h3>
              <p class="mt-1 text-sm text-slate-500">查看账号状态、用途与连接信息。</p>
            </div>
            <UiBadge :variant="currentAccount.enabled ? 'success' : 'default'">
              {{ currentAccount.enabled ? '启用' : '停用' }}
            </UiBadge>
          </div>

          <div class="mt-5 flex flex-wrap gap-2">
            <UiBadge :variant="currentAccount.checkiner ? 'success' : 'default'">签到</UiBadge>
            <UiBadge :variant="currentAccount.monitor ? 'info' : 'default'">监控</UiBadge>
            <UiBadge :variant="currentAccount.messager ? 'warning' : 'default'">水群</UiBadge>
            <UiBadge :variant="currentAccount.registrar ? 'error' : 'default'">抢注</UiBadge>
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
