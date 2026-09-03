// 视觉预识别接口（对齐 app/routers/vision.py）
// 发布前上传首图，返回 AI 识别结果（category_id / label / confidence）及可选分类列表。
import { apiPost } from './request'
import { compressImage } from '@/utils/image'
import type { VisionPredictResult } from '@/types'

// 识别 = 上传 + 后端 CPU 推理，公网下慢；给足 60s（全局 axios 默认 15s 不够）。
const UPLOAD_TIMEOUT = 60000

export const visionApi = {
  async predict(file: File): Promise<VisionPredictResult> {
    // 先压缩手机原图（几 MB → 几百 KB），上传与后端推理都快数倍
    const small = await compressImage(file)
    const fd = new FormData()
    fd.append('image', small)
    return apiPost<VisionPredictResult>('/vision/predict', fd, { timeout: UPLOAD_TIMEOUT })
  },
}
