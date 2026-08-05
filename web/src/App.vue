<template>
  <DemoBanner />
  <RouterView />
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useDemoStore } from '@/stores/demo'
import DemoBanner from '@/components/DemoBanner.vue'

// 启动探测后端可达性，决定是否自动开启演示模式
const demo = useDemoStore()
onMounted(() => {
  demo.init()
})
</script>
