/**
 * Shared composable for account CRUD management views (Emby, Subsonic, Telegram).
 * Eliminates the repeated fetch → drawer → submit → delete → refresh pattern.
 */

import { computed, onMounted, ref, type Ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { logger } from '@/utils/logger'

export interface AccountManagerOptions<T extends { enabled?: boolean }> {
  /** API base path, e.g. '/emby/accounts' */
  apiPath: string
  /** Callback after successful fetch to transform items if needed */
  onFetched?: (items: T[]) => T[]
}

export function useAccountManager<T extends { enabled?: boolean }>(options: AccountManagerOptions<T>) {
  const auth = useAuthStore()

  const accounts = ref<T[]>([]) as Ref<T[]>
  const loading = ref(true)
  const saving = ref(false)
  const deleting = ref<string | null>(null)
  const pageError = ref('')
  const drawerOpen = ref(false)
  const formMode = ref<'create' | 'edit'>('create')
  const formError = ref('')
  const search = ref('')

  const filteredAccounts = computed(() => {
    const keyword = search.value.trim().toLowerCase()
    if (!keyword) return accounts.value
    return accounts.value.filter((account) =>
      Object.values(account as Record<string, unknown>).some((v) =>
        String(v ?? '').toLowerCase().includes(keyword),
      ),
    )
  })

  async function fetchAccounts() {
    loading.value = true
    pageError.value = ''
    try {
      const data = await auth.request<{ accounts: T[] }>(options.apiPath)
      accounts.value = options.onFetched?.(data.accounts || []) || (data.accounts || [])
    } catch (err) {
      pageError.value = logger.message(err, '账号列表加载失败')
      logger.error('Failed to fetch accounts', err)
    } finally {
      loading.value = false
    }
  }

  async function deleteAccount(key: string) {
    deleting.value = key
    pageError.value = ''
    try {
      await auth.request(`${options.apiPath}?key=${encodeURIComponent(key)}`, { method: 'DELETE' })
      await fetchAccounts()
    } catch (err) {
      pageError.value = logger.message(err, '删除账号失败')
      logger.error('Failed to delete account', err)
    } finally {
      deleting.value = null
    }
  }

  onMounted(() => fetchAccounts())

  return {
    accounts,
    loading,
    saving,
    deleting,
    pageError,
    drawerOpen,
    formMode,
    formError,
    search,
    filteredAccounts,
    fetchAccounts,
    deleteAccount,
  }
}
