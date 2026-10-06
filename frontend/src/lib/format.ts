import type { LectureStatus } from '@/client/types.gen'

const pad = (n: number) => String(n).padStart(2, '0')

/** 75 -> "1:15", 3725 -> "1:02:05" */
export function fmt(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${m}:${pad(s % 60)}`
}

export const IDLE_STATUSES: LectureStatus[] = ['ready', 'english_ready', 'failed']
export const isBusy = (status: LectureStatus | undefined) => !!status && !IDLE_STATUSES.includes(status)

export const STATUS_LABEL: Record<LectureStatus, string> = {
  uploaded: 'Queued',
  transcribing: 'Transcribing',
  transcribed: 'Transcribed',
  translating: 'Translating',
  summarizing: 'Summarizing',
  ready: 'Ready',
  chunking: 'English: planning',
  scripting: 'English: writing',
  voicing: 'English: voicing',
  assembling: 'English: assembling',
  english_ready: 'English ready',
  failed: 'Failed',
}

/** Index of the last item whose `start` is <= t (items sorted by start), or -1. */
export function activeIndex(items: { start: number }[], t: number): number {
  let lo = 0
  let hi = items.length - 1
  let found = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (items[mid].start <= t) {
      found = mid
      lo = mid + 1
    } else hi = mid - 1
  }
  return found
}
