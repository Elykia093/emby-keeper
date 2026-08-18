<script setup lang="ts">
defineProps<{
  items: Array<{
    time?: string
    title: string
    description?: string
    type?: 'default' | 'success' | 'error' | 'warning'
  }>
}>()
</script>

<template>
  <div class="flow-root">
    <ul role="list" class="-mb-8">
      <li v-for="(item, index) in items" :key="index">
        <div class="relative pb-8">
          <span v-if="index !== items.length - 1" class="absolute left-4 top-4 -ml-px h-full w-0.5 bg-gray-200" aria-hidden="true" />
          <div class="relative flex space-x-3">
            <div>
              <span :class="[
                'h-8 w-8 rounded-full flex items-center justify-center ring-8 ring-white',
                item.type === 'error' ? 'bg-red-500' :
                item.type === 'warning' ? 'bg-yellow-500' :
                item.type === 'success' ? 'bg-green-500' :
                'bg-gray-400'
              ]">
                <div class="h-2.5 w-2.5 rounded-full bg-white" />
              </span>
            </div>
            <div class="flex min-w-0 flex-1 justify-between space-x-4 pt-1.5">
              <div>
                <p class="text-sm text-gray-900 font-medium">{{ item.title }}</p>
                <p v-if="item.description" class="mt-1 flex items-center text-sm text-gray-500">{{ item.description }}</p>
              </div>
              <div v-if="item.time" class="whitespace-nowrap text-right text-sm text-gray-500">
                <time>{{ item.time }}</time>
              </div>
            </div>
          </div>
        </div>
      </li>
    </ul>
  </div>
</template>
