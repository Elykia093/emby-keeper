<template>
  <div class="relative" ref="selectRef">
    <button
      type="button"
      @click="isOpen = !isOpen"
      class="w-full flex items-center justify-between gap-2 px-3 py-2 text-sm text-left bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl shadow-sm hover:border-gray-300 dark:hover:border-gray-600 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
      :class="{ 'ring-2 ring-primary/20 border-primary': isOpen }"
    >
      <span class="flex items-center gap-2 truncate">
        <span v-if="selectedOption?.color" class="w-2 h-2 rounded-full" :class="selectedOption.color"></span>
        <span :class="selectedOption ? 'text-gray-900 dark:text-gray-100' : 'text-gray-400 dark:text-gray-500'">
          {{ selectedOption?.label || placeholder }}
        </span>
      </span>
      <svg class="w-4 h-4 text-gray-400 dark:text-gray-500 transition-transform" :class="{ 'rotate-180': isOpen }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M6 9l6 6 6-6" />
      </svg>
    </button>

    <Transition
      enter-active-class="transition duration-100 ease-out"
      enter-from-class="transform scale-95 opacity-0"
      enter-to-class="transform scale-100 opacity-100"
      leave-active-class="transition duration-75 ease-in"
      leave-from-class="transform scale-100 opacity-100"
      leave-to-class="transform scale-95 opacity-0"
    >
      <div
        v-if="isOpen"
        class="absolute z-50 w-full mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl shadow-lg overflow-hidden"
      >
        <div class="max-h-60 overflow-auto py-1">
          <button
            v-for="option in options"
            :key="option.value"
            type="button"
            @click="selectOption(option)"
            class="w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
            :class="{ 'bg-primary/5 dark:bg-primary/10': modelValue === option.value }"
          >
            <span v-if="option.color" class="w-2 h-2 rounded-full flex-shrink-0" :class="option.color"></span>
            <span class="flex-1 min-w-0" :class="modelValue === option.value ? 'text-primary font-medium' : 'text-gray-700 dark:text-gray-200'">
              {{ option.label }}<span v-if="option.description" class="text-gray-400 dark:text-gray-500 font-normal"> · {{ option.description }}</span>
            </span>
            <svg v-if="modelValue === option.value" class="w-4 h-4 text-primary flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M20 6L9 17l-5-5" />
            </svg>
          </button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'

export interface SelectOption {
  value: string
  label: string
  color?: string
  description?: string
}

const props = defineProps<{
  modelValue: string
  options: SelectOption[]
  placeholder?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const isOpen = ref(false)
const selectRef = ref<HTMLElement | null>(null)

const selectedOption = computed(() =>
  props.options.find(o => o.value === props.modelValue)
)

function selectOption(option: SelectOption) {
  emit('update:modelValue', option.value)
  isOpen.value = false
}

function handleClickOutside(event: MouseEvent) {
  if (selectRef.value && !selectRef.value.contains(event.target as Node)) {
    isOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>
