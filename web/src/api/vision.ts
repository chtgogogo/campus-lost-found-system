// 视觉预识别接口（对齐 app/routers/vision.py）
// 发布前上传首图，返回 AI 识别结果（category_id / label / confidence）及可选分类列表。
import { apiPost } from './request'
import type { VisionPredictResult } from '@/types'

export const visionApi = {
  predict(file: File): Promise<VisionPredictResult> {
    const fd = new FormData()
    fd.append('image', file)
    return apiPost<VisionPredictResult>('/vision/predict', fd)
  },
}
