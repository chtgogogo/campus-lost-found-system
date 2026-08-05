<template>
  <el-alert
    v-if="demo.bannerVisible"
    type="warning"
    :closable="true"
    show-icon
    class="demo-banner"
    title="当前为演示模式"
    description="后端服务暂时不可达，正在展示本地演示数据；部分功能（真实发布、短信验证码等）在此模式下不可用。"
    @close="demo.dismissBanner()"
  />
</template>

<script setup lang="ts">
import { useDemoStore } from '@/stores/demo'

const demo = useDemoStore()
</script>

<style scoped>
.demo-banner {
  position: sticky;
  top: 0;
  z-index: 2000;
  border-radius: 0;
}
</style>
