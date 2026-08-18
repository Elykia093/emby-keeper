<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useSlots } from 'vue'

const props = withDefaults(defineProps<{
  text?: string
  widthClass?: string
  position?: 'top' | 'bottom'
}>(), {
  position: 'top',
  widthClass: 'w-72',
})

const slots = useSlots()
const hasContentSlot = computed(() => Boolean(slots.content))
const tooltipRef = ref<HTMLElement | null>(null)
const isOpen = ref(false)
const tooltipShift = ref(0)
const arrowShift = ref(0)

const VIEWPORT_MARGIN = 12
const ARROW_MARGIN = 18

const updatePosition = () => {
  const tooltipEl = tooltipRef.value
  if (!tooltipEl) return

  const rect = tooltipEl.getBoundingClientRect()
  const maxRight = window.innerWidth - VIEWPORT_MARGIN
  let shift = 0

  if (rect.left < VIEWPORT_MARGIN) {
    shift = VIEWPORT_MARGIN - rect.left
  } else if (rect.right > maxRight) {
    shift = maxRight - rect.right
  }

  tooltipShift.value = shift

  const maxArrowShift = Math.max(rect.width / 2 - ARROW_MARGIN, 0)
  arrowShift.value = Math.min(Math.max(-shift, -maxArrowShift), maxArrowShift)
}

const openTooltip = async () => {
  if (isOpen.value) return

  isOpen.value = true
  tooltipShift.value = 0
  arrowShift.value = 0

  await nextTick()
  updatePosition()
}

const closeTooltip = () => {
  isOpen.value = false
  tooltipShift.value = 0
  arrowShift.value = 0
}

const syncTooltipPosition = () => {
  if (isOpen.value) {
    updatePosition()
  }
}

onMounted(() => {
  window.addEventListener('resize', syncTooltipPosition)
  window.addEventListener('scroll', syncTooltipPosition, true)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', syncTooltipPosition)
  window.removeEventListener('scroll', syncTooltipPosition, true)
})
</script>

<template>
  <div class="relative inline-flex items-center" @mouseenter="openTooltip" @mouseleave="closeTooltip" @focusin="openTooltip" @focusout="closeTooltip">
    <slot />
    <div
      ref="tooltipRef"
      :class="[
        'pointer-events-none absolute left-1/2 z-30 max-w-[calc(100vw-1.5rem)] rounded-[20px] border border-slate-200/90 bg-white/95 px-4 py-3 text-xs leading-5 text-slate-600 shadow-[0_24px_60px_-30px_rgba(15,23,42,0.35)] ring-1 ring-white/70 backdrop-blur-sm transition duration-200',
        props.widthClass,
        props.position === 'top' ? 'bottom-full mb-3' : 'top-full mt-3',
        isOpen ? 'opacity-100' : 'opacity-0',
      ]"
      :style="{ transform: `translateX(calc(-50% + ${tooltipShift}px))` }"
      role="tooltip"
    >
      <slot name="content">
        <span v-if="!hasContentSlot">{{ text }}</span>
      </slot>
      <span
        :class="[
          'absolute h-3 w-3 -translate-x-1/2 rotate-45 border border-slate-200/90 bg-white/95',
          props.position === 'top' ? '-bottom-1.5' : '-top-1.5',
        ]"
        :style="{ left: `calc(50% + ${arrowShift}px)` }"
        aria-hidden="true"
      />
    </div>
  </div>
</template>