import { createApp } from 'vue'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'
import { createPinia } from 'pinia'
import './style.css'

const app = createApp(App)

// 全局注册 Element Plus 图标，方便在各页面以 <组件名/> 形式使用。
for (const [name, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(name, component as never)
}

// Element Plus 组件改为 unplugin-vue-components 按需注册（见 vite.config.ts）；
// 全量 app.use(ElementPlus) 已移除（审查 P2，2026-09-24）——JS-API 类组件
// （ElMessage/ElMessageBox）仍按需 import，样式由上方全局 CSS 覆盖。
app.use(createPinia())
app.use(router)

app.mount('#app')
