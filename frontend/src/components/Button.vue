<template>
  <button
    :class="[
      'inline-flex items-center justify-center font-semibold rounded-lg',
      'transition-all duration-300 ease-out',
      'focus:outline-none focus:ring-2 focus:ring-offset-2',
      'disabled:opacity-50 disabled:cursor-not-allowed',
      sizeClass,
      variantClass,
      { 'w-full': block }
    ]"
    v-bind="$attrs"
  >
    <slot />
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  block?: boolean
  variant?: 'default' | 'outline' | 'primary' | 'danger' | 'dangerOutline' | 'light'
  size?: 'sm' | 'md' | 'lg'
}>(), {
  block: false,
  variant: 'default',
  size: 'md',
})

const sizeClass = computed(() => {
  const sizes: Record<string, string> = {
    sm: 'px-3 py-1.5 text-sm',
    md: 'px-6 py-3 text-base',
    lg: 'px-8 py-4 text-lg'
  }
  return sizes[props.size] || sizes.md
})

const variantClass = computed(() => {
  if (props.variant === 'outline') {
    return [
      'bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 border border-gray-300 dark:border-gray-600',
      'hover:bg-gray-50 dark:hover:bg-gray-700',
      'focus:ring-primary/30',
    ].join(' ')
  }
  if (props.variant === 'danger') {
    return [
      'bg-red-600 dark:bg-red-700 text-white border border-red-600 dark:border-red-700',
      'hover:bg-red-700 dark:hover:bg-red-800',
      'focus:ring-red-500',
    ].join(' ')
  }
  if (props.variant === 'dangerOutline') {
    return [
      'bg-white dark:bg-gray-800 text-red-500 dark:text-red-400 border border-red-500 dark:border-red-400',
      'hover:bg-gradient-to-r hover:from-red-50 hover:to-white dark:hover:from-red-900/20 dark:hover:to-gray-800',
      'focus:ring-red-500',
    ].join(' ')
  }
  if (props.variant === 'primary') {
    return [
      'bg-primary text-white border border-primary',
      'hover:brightness-105',
      'focus:ring-primary/40',
    ].join(' ')
  }
  if (props.variant === 'light') {
    return [
      'bg-primary/10 dark:bg-primary/20 text-primary dark:text-primary-300 border border-primary/20 dark:border-primary/30',
      'hover:bg-primary/20 dark:hover:bg-primary/30',
      'focus:ring-primary/30',
    ].join(' ')
  }
  // default
  return [
    'bg-gradient-to-r from-gray-50 to-white dark:from-gray-700 dark:to-gray-800',
    'text-gray-800 dark:text-gray-200',
    'border border-gray-200 dark:border-gray-600',
    'shadow-[0_0_10px_rgba(59,130,246,0.08)] dark:shadow-[0_0_10px_rgba(59,130,246,0.15)]',
    'hover:from-primary/10 hover:to-violet-50 dark:hover:from-primary/20 dark:hover:to-violet-900/20',
    'hover:text-gray-900 dark:hover:text-gray-100 hover:border-primary/20 dark:hover:border-primary/30',
    'focus:ring-primary/30'
  ].join(' ')
})
</script>
