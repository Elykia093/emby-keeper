<template>
  <label class="block">
    <div v-if="label" :class="['font-semibold text-gray-900 dark:text-gray-100 mb-1.5', labelSizeClass]">
      {{ label }}
      <span v-if="$attrs.required !== undefined" class="text-red-500 ml-0.5">*</span>
    </div>
    <input
      :class="[
        'w-full bg-white dark:bg-gray-800 border rounded-md transition-colors duration-150 placeholder-gray-400 dark:placeholder-gray-500 text-gray-900 dark:text-gray-100',
        'focus:ring-2',
        'disabled:bg-gray-50 dark:disabled:bg-gray-900 disabled:text-gray-400 disabled:cursor-not-allowed disabled:border-gray-200 dark:disabled:border-gray-700',
        inputPaddingClass,
        inputTextSizeClass,
        hasError ? 'border-red-300 dark:border-red-700 focus:border-red-400 focus:ring-red-100 dark:focus:ring-red-900/30' : 'border-gray-200 dark:border-gray-700 focus:border-primary focus:ring-primary-50 dark:focus:ring-primary-900/30',
      ]"
      v-bind="$attrs"
      :placeholder="placeholder"
      :type="type"
      :value="modelValue"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
    <div v-if="typeof error === 'string' && error" class="mt-1.5 text-xs text-red-600">{{ error }}</div>
  </label>
</template>

<script setup lang="ts">
import { computed } from 'vue'

type InputSize = 'sm' | 'md' | 'lg'

const props = withDefaults(defineProps<{ label?: string; placeholder?: string; type?: string; modelValue?: string | number; size?: InputSize; error?: string | boolean }>(), {
  size: 'md',
  error: '',
})

defineEmits(['update:modelValue'])
const hasError = computed(() => !!props.error)

const labelSizeClass = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'text-sm'
    case 'lg':
      return 'text-base'
    default:
      return 'text-sm'
  }
})

const inputTextSizeClass = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'text-sm'
    case 'lg':
      return 'text-lg'
    default:
      return 'text-base'
  }
})

const inputPaddingClass = computed(() => {
  switch (props.size) {
    case 'sm':
      return 'px-3 py-2'
    case 'lg':
      return 'px-4 py-3'
    default:
      return 'px-3.5 py-2.5'
  }
})
</script>
