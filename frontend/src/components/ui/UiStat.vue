<script setup lang="ts">
import type { Component } from 'vue'

defineProps<{
  label: string
  value: string | number
  icon?: Component
  trend?: 'up' | 'down'
  trendValue?: string
}>()
</script>

<template>
  <div class="flex items-center gap-4 rounded-[26px] border border-slate-200/80 bg-gradient-to-br from-white via-white to-slate-50 px-5 py-4 shadow-[0_12px_32px_-18px_rgba(15,23,42,0.24)] transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_18px_40px_-20px_rgba(15,23,42,0.32)] sm:px-6 sm:py-5">
    <div v-if="icon" class="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-[20px] bg-primary-50 text-primary-600 ring-1 ring-primary-500/10 shadow-inner shadow-white">
      <component :is="icon" class="h-6 w-6" aria-hidden="true" />
    </div>
    <div class="min-w-0">
      <p class="text-sm font-medium text-slate-500">{{ label }}</p>
      <div class="mt-1 flex items-baseline gap-2">
        <p class="text-3xl font-semibold tracking-tight text-slate-950">{{ value }}</p>
        <p v-if="trendValue" :class="[trend === 'up' ? 'text-green-600' : 'text-red-600', 'text-sm font-medium']">
          {{ trend === 'up' ? '↑' : '↓' }} {{ trendValue }}
        </p>
      </div>
    </div>
  </div>
</template>
