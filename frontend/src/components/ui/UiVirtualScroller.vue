<script setup lang="ts">
/**
 * Lightweight virtual-scroll wrapper.
 *
 * Usage:
 *   <UiVirtualScroller :items="logs" :item-height="56" :buffer="8">
 *     <template #default="{ item, index }">
 *       <!-- render row -->
 *     </template>
 *   </UiVirtualScroller>
 *
 * The component renders only the visible slice of `items` inside a
 * fixed-height scrollable container, dramatically reducing DOM nodes
 * for large lists (logs, run-history, etc.).
 */
import { computed, ref, onMounted, onBeforeUnmount, type PropType } from 'vue'
import { VSCROLL_ITEM_HEIGHT_PX, VSCROLL_BUFFER_ITEMS } from '@/utils/constants'

const props = defineProps({
  items: { type: Array as PropType<unknown[]>, required: true },
  itemHeight: { type: Number, default: VSCROLL_ITEM_HEIGHT_PX },
  buffer: { type: Number, default: VSCROLL_BUFFER_ITEMS },
})

const containerRef = ref<HTMLElement | null>(null)
const scrollTop = ref(0)
const containerHeight = ref(600)

let observer: ResizeObserver | null = null

const totalHeight = computed(() => props.items.length * props.itemHeight)

const startIndex = computed(() => {
  const raw = Math.floor(scrollTop.value / props.itemHeight) - props.buffer
  return Math.max(0, raw)
})

const endIndex = computed(() => {
  const visible = Math.ceil(containerHeight.value / props.itemHeight)
  const raw = startIndex.value + visible + props.buffer * 2
  return Math.min(props.items.length, raw)
})

const visibleItems = computed(() =>
  props.items.slice(startIndex.value, endIndex.value).map((item, i) => ({
    item,
    index: startIndex.value + i,
  })),
)

const offsetY = computed(() => startIndex.value * props.itemHeight)

const onScroll = () => {
  scrollTop.value = containerRef.value?.scrollTop ?? 0
}

onMounted(() => {
  if (containerRef.value) {
    containerHeight.value = containerRef.value.clientHeight
    observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        containerHeight.value = entry.contentRect.height
      }
    })
    observer.observe(containerRef.value)
  }
})

onBeforeUnmount(() => {
  observer?.disconnect()
})
</script>

<template>
  <div
    ref="containerRef"
    class="overflow-y-auto"
    :style="{ position: 'relative' }"
    @scroll="onScroll"
    role="list"
  >
    <div :style="{ height: totalHeight + 'px', position: 'relative' }">
      <div :style="{ transform: `translateY(${offsetY}px)` }">
        <div
          v-for="{ item, index } in visibleItems"
          :key="index"
          :style="{ height: itemHeight + 'px' }"
          role="listitem"
        >
          <slot :item="item" :index="index" />
        </div>
      </div>
    </div>
  </div>
</template>
