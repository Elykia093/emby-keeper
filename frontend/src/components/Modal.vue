<template>
  <Teleport to="body">
    <Transition name="modal-fade">
      <div v-if="open" class="relative z-50">
        <div class="fixed inset-0 bg-black/30" @click="$emit('close')" />
        <div class="fixed inset-0 overflow-y-auto">
          <div class="flex min-h-full items-center justify-center p-2 sm:p-4">
            <div
              :class="[
                'w-full overflow-hidden rounded-lg bg-white dark:bg-gray-800 p-4 sm:p-6 shadow-xl',
                sizeClasses
              ]"
              @click.stop
            >
              <h3 class="text-base sm:text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3 sm:mb-4">
                <slot name="title" />
              </h3>
              <div class="mt-2 mb-4 sm:mb-6">
                <slot />
              </div>
              <div class="flex gap-3 justify-end">
                <slot name="actions" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  open: boolean
  size?: 'sm' | 'md' | 'large' | 'xl'
}>(), {
  size: 'md'
})

defineEmits(['close'])

const sizeClasses = computed(() => {
  const sizes: Record<string, string> = {
    sm: 'max-w-sm',
    md: 'max-w-md',
    large: 'max-w-2xl',
    xl: 'max-w-4xl'
  }
  return sizes[props.size] || sizes.md
})
</script>

<style scoped>
.modal-fade-enter-active,
.modal-fade-leave-active {
  transition: opacity 0.2s ease;
}

.modal-fade-enter-from,
.modal-fade-leave-to {
  opacity: 0;
}
</style>
