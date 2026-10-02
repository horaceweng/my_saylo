import type { AdminUser, AdminUsage } from '../api/types'

/** One user's use today, e.g. "影片 1/5 · 音訊 12/90 分 · AI 40/300 次" (no "/limit" when the limits are not known). */
export function usageLine(used: AdminUser['usage_today'], limits?: AdminUsage['limits']): string {
  const of = (n: number, limit?: number) => (limit === undefined ? `${n}` : `${n}/${limit}`)
  const minutes = Math.round(used.audio_minutes)
  return `影片 ${of(used.media, limits?.media)} · 音訊 ${of(minutes, limits?.audio_minutes)} 分 · AI ${of(used.ai, limits?.ai)} 次`
}
