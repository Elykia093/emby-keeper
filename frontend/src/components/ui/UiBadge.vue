<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  variant?: 'default' | 'success' | 'warning' | 'error' | 'info'
  size?: 'sm' | 'md' | 'lg'
}>()

const variantClass = computed(() => {
  switch (props.variant) {
    case 'success': return 'bg-green-50 text-green-700 ring-green-600/20'
    case 'warning': return 'bg-yellow-50 text-yellow-800 ring-yellow-600/20'
    case 'error': return 'bg-red-50 text-red-700 ring-red-600/10'
    case 'info': return 'bg-blue-50 text-blue-700 ring-blue-700/10'
    default: return 'bg-gray-50 text-gray-600 ring-gray-500/10'
  }
})

const sizeClass = computed(() => {
  switch (props.size) {
    case 'sm': return 'px-1.5 py-0.5 text-xs'
    case 'lg': return 'px-2.5 py-1 text-sm'
    default: return 'px-2 py-1 text-xs'
  }
})
</script>

<template>
  <span :class="['inline-flex w-fit items-center self-start rounded-full font-medium ring-1 ring-inset', variantClass, sizeClass]">
    <slot />
  </span>
</template>
