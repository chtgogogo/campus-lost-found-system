<template>
  <div class="lf-container">
    <h2 class="lf-page-title">发布</h2>

    <el-tabs v-model="tab" class="publish-tabs">
      <!-- ===================== 拾得者·发布拾物 ===================== -->
      <el-tab-pane label="拾得者 · 发布拾物" name="found">
        <div class="lf-card publish-card">
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="零门槛发布"
            description="至少上传 1 张照片，保管状态二选一即可发布；分类由系统视觉识别自动预填，您可修改。"
            style="margin-bottom: 16px"
          />

          <el-form label-position="top">
            <el-form-item label="保管状态" required>
              <div class="keep-options">
                <!-- v5 修复：将选项包进 el-radio-group 并绑定 v-model，
                     否则单个 el-radio 无模型，点击后选中态与 found.keep_status 均不更新 -->
                <el-radio-group
                  v-model="found.keep_status"
                  style="display: flex; flex-direction: column; gap: 12px; width: 100%"
                >
                  <div class="keep-option">
                    <el-radio :value="0">暂为保管</el-radio>
                    <div class="lf-muted keep-tip">
                      已代为保管：将强制开启“允许联系”，失主可联系你取回。
                    </div>
                  </div>
                  <div class="keep-option">
                    <el-radio :value="1">未挪动</el-radio>
                    <div class="lf-muted keep-tip">
                      物品原地未动：失主可“申请匹配”自取，你也可开启联系。
                    </div>
                  </div>
                </el-radio-group>
              </div>
            </el-form-item>

            <el-form-item label="物品照片（至少 1 张）" required>
              <el-upload
                v-model:file-list="foundFiles"
                list-type="picture-card"
                :auto-upload="false"
                :on-preview="onPreview"
                :on-remove="() => {}"
                accept="image/*"
                multiple
              >
                <el-icon><Plus /></el-icon>
              </el-upload>
              <span v-if="foundFiles.length === 0" class="lf-muted upload-hint">
                请上传照片，系统将自动识别类别
              </span>
            </el-form-item>

            <!-- AI 识别结果卡片：上传后自动预识别，结果预填到分类文本框（可改） -->
            <el-form-item label="AI 识别结果" v-if="visionResult">
              <el-card shadow="never" class="vision-card">
                <div class="vision-row">
                  <span class="vision-label">识别类别：<b>{{ visionResult.label }}</b></span>
                  <span class="vision-conf">置信度：{{ visionPercent }}%</span>
                </div>
                <el-progress
                  :percentage="visionPercent"
                  :status="visionLow ? 'exception' : 'success'"
                  :stroke-width="10"
                  class="vision-progress"
                />
                <el-alert
                  v-if="visionLow"
                  type="warning"
                  :closable="false"
                  class="vision-tip"
                  title="置信度较低，请手动确认类别"
                />
                <el-form-item label="分类（可修改）" style="margin-top: 8px; margin-bottom: 0">
                  <el-input
                    v-model="found.category_name"
                    placeholder="系统已预填识别结果，可修改"
                    maxlength="100"
                    show-word-limit
                  />
                </el-form-item>
              </el-card>
            </el-form-item>

            <el-form-item label="描述（选填）">
              <el-input
                v-model="found.description"
                type="textarea"
                :rows="3"
                placeholder="描述颜色、图案/花纹、内含物品、尺寸等，可显著提升匹配成功率"
              />
              <div class="lf-muted desc-tip">
                建议描述：颜色、图案/花纹、内含物品（如银行卡）、尺寸大小，越具体越容易匹配成功。
              </div>
            </el-form-item>

            <!-- v8：外观 / 特征 / 地点（选填） -->
            <el-form-item label="外观（选填）">
              <el-input v-model="found.appearance" placeholder="如：黑色皮质，带银色挂件" />
            </el-form-item>
            <el-form-item label="特征（选填）">
              <el-input v-model="found.features" placeholder="如：挂件为星星造型，有划痕" />
            </el-form-item>
            <el-form-item label="地点（选填）">
              <el-input v-model="found.location" placeholder="如：三教一楼自习室" />
            </el-form-item>

            <el-form-item label="拾得时间（选填）">
              <el-date-picker
                v-model="found.found_time"
                type="datetime"
                placeholder="选择时间"
                value-format="YYYY-MM-DDTHH:mm:ss"
                style="width: 100%"
              />
            </el-form-item>

            <el-form-item label="允许认领者联系我">
              <el-switch
                v-model="found.contact_allowed"
                :disabled="found.keep_status === 0"
              />
              <span v-if="found.keep_status === 0" class="lf-muted keep-tip">
                暂为保管时不可关闭
              </span>
            </el-form-item>

            <el-button
              type="success"
              size="large"
              :loading="foundLoading"
              @click="onSubmitFound"
            >
              发布拾物
            </el-button>
          </el-form>
        </div>
      </el-tab-pane>

      <!-- ===================== 失主·发布失物 ===================== -->
      <el-tab-pane label="失主 · 发布失物" name="lost">
        <div class="lf-card publish-card">
          <el-form label-position="top">
            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="物品分类" required>
                  <el-input
                    v-model="lost.category_name"
                    placeholder="如：书包 / 手机 / 水杯"
                    maxlength="100"
                    show-word-limit
                  />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="标题" required>
                  <el-input v-model="lost.title" placeholder="如：黑色 iPhone 13 一部" />
                </el-form-item>
              </el-col>
            </el-row>

            <el-form-item label="丢失时间（选填）">
              <el-date-picker
                v-model="lost.lost_time"
                type="datetime"
                placeholder="选择丢失时间（不知道/记不清可留空）"
                value-format="YYYY-MM-DDTHH:mm:ss"
                style="width: 100%"
              />
              <div class="lf-muted desc-tip">
                丢失时间不确定可留空，不影响发布与匹配。
              </div>
            </el-form-item>

            <el-form-item label="颜色（选填）">
              <el-input v-model="lost.color" placeholder="如：黑色" />
            </el-form-item>

            <!-- v8：外观 / 特征 / 地点（选填） -->
            <el-form-item label="外观（选填）">
              <el-input v-model="lost.appearance" placeholder="如：黑色皮质，带银色挂件" />
            </el-form-item>
            <el-form-item label="特征（选填）">
              <el-input v-model="lost.features" placeholder="如：挂件为星星造型，有划痕" />
            </el-form-item>
            <el-form-item label="地点（选填）">
              <el-input v-model="lost.location" placeholder="如：三教一楼自习室" />
            </el-form-item>

            <el-form-item label="详细描述" required>
              <el-input
                v-model="lost.description"
                type="textarea"
                :rows="3"
                placeholder="描述颜色、图案/花纹、内含物品、尺寸等，便于精准匹配"
              />
              <div class="lf-muted desc-tip">
                建议描述：颜色、图案/花纹、内含物品（如银行卡）、尺寸大小，越具体越容易匹配成功。
              </div>
            </el-form-item>

            <el-form-item label="照片（选填，最多 9 张）">
              <el-upload
                v-model:file-list="lostFiles"
                list-type="picture-card"
                :auto-upload="false"
                :on-preview="onPreview"
                accept="image/*"
                multiple
                :limit="9"
              >
                <el-icon><Plus /></el-icon>
              </el-upload>
            </el-form-item>

            <el-button
              type="primary"
              size="large"
              :loading="lostLoading"
              @click="onSubmitLost"
            >
              发布失物
            </el-button>
          </el-form>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 图片预览 -->
    <el-dialog v-model="previewVisible" title="图片预览" width="520px">
      <img :src="previewUrl" style="width: 100%; border-radius: 8px" alt="预览" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, type UploadUserFile } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { itemsApi } from '@/api/items'
import { visionApi } from '@/api/vision'
import type { VisionPredictResult } from '@/types'

const tab = ref<'found' | 'lost'>('found')

const foundLoading = ref(false)
const lostLoading = ref(false)

const foundFiles = ref<UploadUserFile[]>([])
const lostFiles = ref<UploadUserFile[]>([])

const found = reactive({
  keep_status: 0 as number,
  category_name: '' as string,
  description: '',
  found_time: '' as string,
  contact_allowed: true,
  // v8：外观 / 特征 / 地点（选填，随表单一并提交后端三列）
  appearance: '' as string,
  features: '' as string,
  location: '' as string,
})

// AI 预识别结果（发布前上传首图触发）
const visionResult = ref<VisionPredictResult | null>(null)

const visionPercent = computed(() =>
  Math.round((visionResult.value ? visionResult.value.confidence : 0) * 100),
)
const visionLow = computed(
  () => visionResult.value !== null && visionResult.value.confidence < 0.5,
)

// v4：暂为保管（keep_status=0）强制开启联系；切换到 0 时自动开灯
watch(
  () => found.keep_status,
  (ks) => {
    if (ks === 0) found.contact_allowed = true
  },
)

// 拾物上传后自动预识别（演示模式由 mockAdapter 返回占位结果），
// 并将识别 label 预填到分类文本框（用户可改）
watch(
  foundFiles,
  async (files) => {
    if (tab.value !== 'found') return
    const first = files.find((f) => f.raw)
    if (!first || !first.raw) {
      visionResult.value = null
      return
    }
    try {
      const res = await visionApi.predict(first.raw)
      visionResult.value = res
      found.category_name = res.label // 预填，可改
    } catch {
      visionResult.value = null
    }
  },
  { deep: true },
)

const lost = reactive({
  category_name: '' as string,
  title: '',
  lost_time: '' as string,
  color: '',
  description: '',
  // v8：外观 / 特征 / 地点（选填，随表单一并提交后端三列）
  appearance: '' as string,
  features: '' as string,
  location: '' as string,
})

const previewVisible = ref(false)
const previewUrl = ref('')

function onPreview(file: UploadUserFile) {
  previewUrl.value = file.url || ''
  previewVisible.value = true
}

function buildFormWithImages(list: UploadUserFile[]): FormData {
  const fd = new FormData()
  list.forEach((f) => {
    if (f.raw) fd.append('images', f.raw)
  })
  return fd
}

async function onSubmitFound() {
  if (foundFiles.value.length === 0) {
    ElMessage.warning('请至少上传 1 张照片')
    return
  }
  if (!found.category_name.trim()) {
    ElMessage.warning('请填写物品分类')
    return
  }
  const fd = buildFormWithImages(foundFiles.value)
  fd.append('keep_status', String(found.keep_status))
  fd.append('category_name', found.category_name.trim())
  if (found.description) fd.append('description', found.description)
  if (found.found_time) fd.append('found_time', found.found_time)
  fd.append('contact_allowed', found.contact_allowed ? '1' : '0')
  // v8：外观 / 特征 / 地点（选填，仅非空时提交）
  if (found.appearance) fd.append('appearance', found.appearance)
  if (found.features) fd.append('features', found.features)
  if (found.location) fd.append('location', found.location)

  foundLoading.value = true
  try {
    const res = await itemsApi.createFound(fd)
    ElMessage.success(`发布成功${res.suspected_matches.length ? `，发现 ${res.suspected_matches.length} 条疑似匹配` : ''}`)
    foundFiles.value = []
    found.description = ''
    found.found_time = ''
    found.category_name = ''
    found.appearance = ''
    found.features = ''
    found.location = ''
    visionResult.value = null
  } catch {
    /* 忽略 */
  } finally {
    foundLoading.value = false
  }
}

async function onSubmitLost() {
  if (!lost.category_name.trim()) {
    ElMessage.warning('请填写物品分类')
    return
  }
  if (!lost.title.trim()) {
    ElMessage.warning('请填写标题')
    return
  }
  if (!lost.description.trim()) {
    ElMessage.warning('请填写详细描述')
    return
  }

  const fd = buildFormWithImages(lostFiles.value)
  fd.append('category_name', lost.category_name.trim())
  fd.append('title', lost.title)
  fd.append('description', lost.description)
  // R3：丢失时间选填，仅非空时提交（后端 lost_time Optional）
  if (lost.lost_time) fd.append('lost_time', lost.lost_time)
  if (lost.color) fd.append('color', lost.color)
  // v8：外观 / 特征 / 地点（选填，仅非空时提交）
  if (lost.appearance) fd.append('appearance', lost.appearance)
  if (lost.features) fd.append('features', lost.features)
  if (lost.location) fd.append('location', lost.location)

  lostLoading.value = true
  try {
    const res = await itemsApi.createLost(fd)
    ElMessage.success(`发布成功${res.suspected_matches.length ? `，发现 ${res.suspected_matches.length} 条疑似匹配` : ''}`)
    lostFiles.value = []
    lost.title = ''
    lost.lost_time = ''
    lost.color = ''
    lost.description = ''
    lost.appearance = ''
    lost.features = ''
    lost.location = ''
    lost.category_name = ''
  } catch {
    /* 忽略 */
  } finally {
    lostLoading.value = false
  }
}
</script>

<style scoped>
.publish-card {
  padding: 20px;
  max-width: 720px;
}
.upload-hint {
  margin-left: 12px;
  font-size: 13px;
}
.publish-tabs :deep(.el-upload--picture-card) {
  width: 96px;
  height: 96px;
}
.vision-card {
  margin-bottom: 6px;
}
.vision-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.vision-label {
  font-size: 14px;
}
.vision-conf {
  font-size: 13px;
  color: #606266;
}
.vision-progress {
  margin-bottom: 4px;
}
.vision-tip {
  margin-bottom: 6px;
}
.keep-tip {
  font-size: 12px;
  margin-top: 6px;
  line-height: 1.4;
}
.desc-tip {
  font-size: 12px;
  margin-top: 6px;
  line-height: 1.45;
}
.keep-options {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.keep-option {
  display: flex;
  flex-direction: column;
  padding: 8px 12px;
  border: 1px solid var(--lf-border, #ebeef5);
  border-radius: 8px;
  background: #f7f9fc;
}
.keep-option .el-radio {
  margin-bottom: 2px;
}
</style>
