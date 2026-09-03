// 图片压缩工具：发布/识别前把手机原图压到可控体积。
//
// 背景（2026-08-20）：家人通过 cpolar 公网访问，手机原图常达 3-10MB，
// 上传慢 + 后端 CPU 跑 YOLO 识别慢，单请求容易超过前端 axios 15s 超时，
// 触发"网络错误 → 自动切演示模式"的假故障。压缩后上传体积和识别耗时
// 都大幅下降（目标：单张 < 400KB）。
//
// 规则：
// - 非图片（如误传文件）原样返回；
// - 已足够小（长边 ≤ maxSide 且 ≤ 512KB）原样返回，不二次压缩；
// - 否则 canvas 缩放到 maxSide（默认 1280 长边，YOLO 输入 640 足够，不掉精度）
//   并以 JPEG 质量 quality（默认 0.72）输出；
// - 现代浏览器解码时自动应用 EXIF 方向，canvas 输出即为正向，无需手动旋转。
export function compressImage(
  file: File,
  maxSide = 1280,
  quality = 0.72,
): Promise<File> {
  return new Promise((resolve) => {
    if (!file.type.startsWith('image/')) {
      resolve(file)
      return
    }
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(url)
      const { width, height } = img
      if (!width || !height) {
        resolve(file)
        return
      }
      const scale = Math.min(1, maxSide / Math.max(width, height))
      if (scale >= 1 && file.size <= 512 * 1024) {
        resolve(file)
        return
      }
      const w = Math.max(1, Math.round(width * scale))
      const h = Math.max(1, Math.round(height * scale))
      const canvas = document.createElement('canvas')
      canvas.width = w
      canvas.height = h
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        resolve(file)
        return
      }
      ctx.drawImage(img, 0, 0, w, h)
      canvas.toBlob(
        (blob) => {
          if (!blob) {
            resolve(file)
            return
          }
          const name = file.name.replace(/\.[^.]+$/, '') + '.jpg'
          resolve(new File([blob], name, { type: 'image/jpeg' }))
        },
        'image/jpeg',
        quality,
      )
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      resolve(file)
    }
    img.src = url
  })
}

/** 批量压缩（保留顺序；单张失败原样放回，不阻断流程）。 */
export async function compressImages(files: File[]): Promise<File[]> {
  const out: File[] = []
  for (const f of files) {
    out.push(await compressImage(f))
  }
  return out
}
