<template>
  <div :class="['bg-white dark:bg-gray-800 rounded-lg border border-gray-100 dark:border-gray-700 shadow-[0_0_18px_rgba(59,130,246,0.06)] dark:shadow-[0_0_18px_rgba(59,130,246,0.1)] hover:shadow-[0_0_26px_rgba(59,130,246,0.12)] dark:hover:shadow-[0_0_26px_rgba(59,130,246,0.15)] transition-shadow duration-300', $attrs.class]">
    <div v-if="$slots.header" class="px-4 sm:px-6 py-2 border-b border-gray-100 dark:border-gray-700">
      <slot name="header" />
    </div>
    <div
      v-show="bodyVisible"
      ref="content"
      class="p-4 sm:p-6"
    >
      <slot />
    </div>
    <div v-if="$slots.footer" class="px-4 sm:px-6 py-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 rounded-b-lg">
      <slot name="footer" />
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ bodyVisible?: boolean }>(), {
  bodyVisible: true,
})

defineOptions({
  inheritAttrs: false
})
</script>
