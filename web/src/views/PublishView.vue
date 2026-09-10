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

            <!-- v12：颜色 / 成色点选（替代 v8 外观/特征自由文本，录入规范化） -->
            <el-form-item label="颜色（点选，可多选）">
              <div class="chip-row">
                <span
                  v-for="c in COLOR_OPTIONS"
                  :key="c"
                  class="chip"
                  :class="{ on: found.colorChips.includes(c) }"
                  @click="toggleChip(found.colorChips, c)"
                >
                  {{ c }}
                </span>
              </div>
            </el-form-item>
            <el-form-item label="成色 / 状态（点选，可多选）">
              <div class="chip-row">
                <span
                  v-for="g in GRADE_OPTIONS"
                  :key="g"
                  class="chip chip-grade"
                  :class="{ on: found.gradeChips.includes(g) }"
                  @click="toggleChip(found.gradeChips, g)"
                >
                  {{ g }}
                </span>
              </div>
            </el-form-item>

            <el-form-item label="物品描述">
              <el-input
                v-model="found.description"
                type="textarea"
                :rows="4"
                placeholder="例：捡到一把黑色雨伞，按钮开关式，伞面有白色星星图案，伞内侧写着「太刀」两个字，手柄上有个小缺口"
              />
              <div class="lf-muted desc-tip">
                建议写清：数量、颜色、图案/花纹、内含物品、特殊标记，越具体越容易匹配成功。
              </div>
            </el-form-item>

            <!-- v12：智能确认卡片——展示系统从描述中识别到的标签，提交前可自查 -->
            <div v-if="foundPreviewTags.length" class="tag-preview-card">
              <span class="tag-preview-title">🏷️ 系统识别到：</span>
              <span v-for="t in foundPreviewTags" :key="t" class="tag-preview-item">{{ t }}</span>
              <span class="lf-muted tag-preview-hint">有遗漏？在描述里补充说明即可</span>
            </div>

            <el-form-item label="拾得地点（选填）">
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

            <!-- v12：颜色点选（替代 v1 颜色文本框——原 color 列不参与打分，点选词并入描述才是有效信号） -->
            <el-form-item label="颜色（点选，可多选）">
              <div class="chip-row">
                <span
                  v-for="c in COLOR_OPTIONS"
                  :key="c"
                  class="chip"
                  :class="{ on: lost.colorChips.includes(c) }"
                  @click="toggleChip(lost.colorChips, c)"
                >
                  {{ c }}
                </span>
              </div>
            </el-form-item>
            <el-form-item label="成色 / 状态（点选，可多选）">
              <div class="chip-row">
                <span
                  v-for="g in GRADE_OPTIONS"
                  :key="g"
                  class="chip chip-grade"
                  :class="{ on: lost.gradeChips.includes(g) }"
                  @click="toggleChip(lost.gradeChips, g)"
                >
                  {{ g }}
                </span>
              </div>
            </el-form-item>

            <el-form-item label="详细描述" required>
              <el-input
                v-model="lost.description"
                type="textarea"
                :rows="4"
                placeholder="例：丢了一把黑色雨伞，按钮开关式，伞面有白色星星图案，伞内侧写着「太刀」两个字，手柄上有个小缺口"
              />
              <div class="lf-muted desc-tip">
                建议写清：数量、颜色、图案/花纹、内含物品、特殊标记，越具体越容易匹配成功。
              </div>
            </el-form-item>

            <!-- v12：智能确认卡片（同拾物侧） -->
            <div v-if="lostPreviewTags.length" class="tag-preview-card">
              <span class="tag-preview-title">🏷️ 系统识别到：</span>
              <span v-for="t in lostPreviewTags" :key="t" class="tag-preview-item">{{ t }}</span>
              <span class="lf-muted tag-preview-hint">有遗漏？在描述里补充说明即可</span>
            </div>

            <el-form-item label="丢失地点（选填）">
              <el-input v-model="lost.location" placeholder="如：三教一楼自习室" />
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
import { compressImages } from '@/utils/image'
import type { VisionPredictResult } from '@/types'

const tab = ref<'found' | 'lost'>('found')

const foundLoading = ref(false)
const lostLoading = ref(false)

const foundFiles = ref<UploadUserFile[]>([])
const lostFiles = ref<UploadUserFile[]>([])

// v12：颜色 / 成色点选常量——与后端词表对齐（COLOR_WORDS / STATE_WORD_PAIRS），
// 点选词提交时并入 description 前缀，后端既有抽取管线零改动即可吃到规范化输入。
const COLOR_OPTIONS = [
  '黑色', '白色', '灰色', '红色', '蓝色', '绿色', '黄色',
  '粉色', '紫色', '橙色', '棕色', '金色', '银色', '彩色', '透明',
]
const GRADE_OPTIONS = [
  '全新', '崭新', '完好', '九成新', '八成新',
  '划痕', '磨损', '破损', '老旧', '破旧',
]

function toggleChip(list: string[], word: string) {
  const i = list.indexOf(word)
  if (i >= 0) list.splice(i, 1)
  else list.push(word)
}

// 点选词 + 用户描述 → 合成提交文本（点选词放前面，颜色/状态抽取都会命中）
function composeDescription(chips: string[], base: string): string {
  return [...chips, (base || '').trim()].filter(Boolean).join(' ')
}

const found = reactive({
  keep_status: 0 as number,
  category_name: '' as string,
  description: '',
  found_time: '' as string,
  contact_allowed: true,
  location: '' as string,
  colorChips: [] as string[],
  gradeChips: [] as string[],
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
// v9：识别前先压缩手机原图（visionApi.predict 内部压缩），上传与推理都快数倍
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
  description: '',
  location: '' as string,
  colorChips: [] as string[],
  gradeChips: [] as string[],
})

const previewVisible = ref(false)
const previewUrl = ref('')

function onPreview(file: UploadUserFile) {
  previewUrl.value = file.url || ''
  previewVisible.value = true
}

// ---------------- v12：智能确认卡片（标签预览，防抖 600ms） ----------------
const foundPreviewTags = ref<string[]>([])
const lostPreviewTags = ref<string[]>([])
let previewTimer: ReturnType<typeof setTimeout> | undefined

async function refreshPreview() {
  const isLost = tab.value === 'lost'
  const payload = isLost
    ? {
        title: lost.title,
        description: composeDescription(
          [...lost.colorChips, ...lost.gradeChips],
          lost.description,
        ),
        category_name: lost.category_name,
      }
    : {
        description: composeDescription(
          [...found.colorChips, ...found.gradeChips],
          found.description,
        ),
        category_name: found.category_name,
      }
  try {
    const res = await itemsApi.tagsPreview(payload)
    if (isLost) lostPreviewTags.value = res.tags || []
    else foundPreviewTags.value = res.tags || []
  } catch {
    // 演示模式 / 网络异常：静默，不展示卡片
  }
}

watch(
  [
    () => lost.description,
    () => lost.title,
    () => lost.colorChips.length,
    () => lost.gradeChips.length,
    () => found.description,
    () => found.colorChips.length,
    () => found.gradeChips.length,
  ],
  () => {
    if (previewTimer) clearTimeout(previewTimer)
    previewTimer = setTimeout(refreshPreview, 600)
  },
)

// ---------------- 提交 ----------------
// v9：发布上传前压缩每张手机原图（几 MB → 几百 KB），公网小带宽下大幅减少上传耗时
async function buildFormWithImages(list: UploadUserFile[]): Promise<FormData> {
  const fd = new FormData()
  const raws: File[] = []
  list.forEach((f) => {
    if (f.raw) raws.push(f.raw as File)
  })
  const smalls = await compressImages(raws)
  smalls.forEach((f) => fd.append('images', f))
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
  const fd = await buildFormWithImages(foundFiles.value)
  fd.append('keep_status', String(found.keep_status))
  fd.append('category_name', found.category_name.trim())
  const desc = composeDescription(
    [...found.colorChips, ...found.gradeChips],
    found.description,
  )
  if (desc) fd.append('description', desc)
  if (found.found_time) fd.append('found_time', found.found_time)
  fd.append('contact_allowed', found.contact_allowed ? '1' : '0')
  if (found.location) fd.append('location', found.location)

  foundLoading.value = true
  try {
    const res = await itemsApi.createFound(fd)
    ElMessage.success(`发布成功${res.suspected_matches.length ? `，发现 ${res.suspected_matches.length} 条疑似匹配` : ''}`)
    foundFiles.value = []
    found.description = ''
    found.found_time = ''
    found.category_name = ''
    found.location = ''
    found.colorChips = []
    found.gradeChips = []
    foundPreviewTags.value = []
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
  const desc = composeDescription(
    [...lost.colorChips, ...lost.gradeChips],
    lost.description,
  )
  if (!desc.trim()) {
    ElMessage.warning('请填写详细描述（或点选颜色/成色）')
    return
  }

  const fd = await buildFormWithImages(lostFiles.value)
  fd.append('category_name', lost.category_name.trim())
  fd.append('title', lost.title)
  fd.append('description', desc)
  // R3：丢失时间选填，仅非空时提交（后端 lost_time Optional）
  if (lost.lost_time) fd.append('lost_time', lost.lost_time)
  if (lost.location) fd.append('location', lost.location)

  lostLoading.value = true
  try {
    const res = await itemsApi.createLost(fd)
    ElMessage.success(`发布成功${res.suspected_matches.length ? `，发现 ${res.suspected_matches.length} 条疑似匹配` : ''}`)
    lostFiles.value = []
    lost.title = ''
    lost.lost_time = ''
    lost.description = ''
    lost.location = ''
    lost.colorChips = []
    lost.gradeChips = []
    lostPreviewTags.value = []
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

/* v12：颜色/成色点选 chips */
.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.chip {
  padding: 5px 14px;
  border-radius: 999px;
  border: 1px solid var(--lf-border);
  background: #fff;
  font-size: 13px;
  color: var(--lf-text-sub);
  cursor: pointer;
  user-select: none;
  transition: all 0.15s ease;
  min-height: 30px;
  display: inline-flex;
  align-items: center;
}
.chip:hover {
  border-color: var(--lf-primary);
  color: var(--lf-primary);
}
.chip.on {
  background: var(--lf-primary);
  border-color: var(--lf-primary);
  color: #fff;
}
.chip-grade.on {
  background: var(--lf-accent);
  border-color: var(--lf-accent);
}

/* v12：智能确认卡片 */
.tag-preview-card {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin: 0 0 18px;
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--lf-primary-light-9, #e8f4f2);
  border: 1px dashed var(--lf-primary-light-7, #b7d6d3);
}
.tag-preview-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--lf-primary-dark);
}
.tag-preview-item {
  padding: 3px 10px;
  border-radius: 999px;
  background: #fff;
  border: 1px solid var(--lf-primary-light-7, #bed8d4);
  color: var(--lf-primary-dark);
  font-size: 12px;
  line-height: 1.5;
}
.tag-preview-hint {
  font-size: 12px;
  margin-left: 4px;
}
</style>
