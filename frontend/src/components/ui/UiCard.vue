<script setup lang="ts">
withDefaults(defineProps<{
  hover?: boolean
  padding?: 'sm' | 'md' | 'lg' | 'none'
  bodyVisible?: boolean
}>(), {
  bodyVisible: true,
})

defineOptions({
  inheritAttrs: false
})
</script>

<template>
  <div
    :class="[
      'rounded-3xl border border-slate-200/80 bg-white/92 shadow-[0_12px_32px_-18px_rgba(15,23,42,0.28)] backdrop-blur-sm transition-all duration-200',
      hover && 'cursor-pointer hover:-translate-y-0.5 hover:shadow-[0_18px_40px_-20px_rgba(15,23,42,0.34)]',
      $attrs.class
    ]"
  >
    <div v-if="$slots.header" class="rounded-t-3xl border-b border-slate-200/80 bg-slate-50/85 px-5 py-5 sm:px-7">
      <slot name="header" />
    </div>
    <div
      v-show="bodyVisible"
      :class="[
        padding === 'sm' && 'p-5',
        padding === 'lg' && 'p-8 sm:p-9',
        padding === 'none' && 'p-0',
        (!padding || padding === 'md') && 'p-5 sm:p-7',
      ]"
    >
      <slot />
    </div>
    <div v-if="$slots.footer" class="rounded-b-3xl border-t border-slate-200/80 bg-slate-50/85 px-5 py-5 sm:px-7">
      <slot name="footer" />
    </div>
  </div>
</template>
