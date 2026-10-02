export const CLOUD_DISABLED_WARNING = '雲端模型可能已被停用（OpenCode 免費額度限制），目前都改用本地模型；請到設定頁更換雲端模型'

/** A failure reason in words, e.g. "HTTP 403" or "逾時". */
export function reasonLabel(r: { error_class: string; status_code: number | null }): string {
  switch (r.error_class) {
    case 'http': return r.status_code ? `HTTP ${r.status_code}` : 'HTTP 錯誤'
    case 'timeout': return '逾時'
    case 'connection': return '連不上'
    case 'invalid_json': return '回覆格式錯誤'
    default: return '其他'
  }
}
