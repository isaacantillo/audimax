import { useCallback, useRef, useState } from 'react'

import type { LecturePart } from '@/client/types.gen'

/**
 * One lecture can be several recordings. This presents them as one timeline: `time` and `seek`
 * use lecture time (seconds from the start of the first file), and playback continues into the next
 * file by itself.
 */
export function useOriginalPlayer(parts: LecturePart[]) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [index, setIndex] = useState(0)
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  // A seek into another file waits here until that file's metadata has loaded.
  const pending = useRef<{ t: number; play: boolean } | null>(null)

  const part = parts[Math.min(index, Math.max(parts.length - 1, 0))]

  const seek = useCallback(
    (lectureTime: number, play = true) => {
      let target = parts.findLastIndex((p) => p.offset <= lectureTime)
      if (target < 0) target = 0
      const local = Math.max(0, lectureTime - (parts[target]?.offset ?? 0))
      const audio = audioRef.current
      if (target === index && audio && audio.readyState > 0) {
        audio.currentTime = local
        if (play) void audio.play()
      } else {
        // Another file, or this one has not loaded yet: apply it when its metadata arrives.
        pending.current = { t: local, play }
        setIndex(target)
      }
    },
    [parts, index],
  )

  const props = {
    ref: audioRef,
    src: part?.audio_url,
    preload: 'metadata' as const,
    onLoadedMetadata: (e: React.SyntheticEvent<HTMLAudioElement>) => {
      const next = pending.current
      if (!next) return
      pending.current = null
      e.currentTarget.currentTime = next.t
      if (next.play) void e.currentTarget.play()
    },
    onTimeUpdate: (e: React.SyntheticEvent<HTMLAudioElement>) => setTime((part?.offset ?? 0) + e.currentTarget.currentTime),
    onPlay: () => setPlaying(true),
    onPause: () => setPlaying(false),
    onEnded: () => {
      if (index + 1 < parts.length) {
        pending.current = { t: 0, play: true }
        setIndex(index + 1)
      }
    },
  }

  const pause = useCallback(() => audioRef.current?.pause(), [])
  // `audioKey` re-mounts the element when the next file starts; pass it as key={...} (React can't take a spread key).
  return { props, audioKey: part?.audio_url, time, playing, seek, pause, partIndex: index }
}

/** Plain single-file player (the English audio). */
export function useSimplePlayer() {
  const ref = useRef<HTMLAudioElement>(null)
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const pending = useRef<{ t: number; play: boolean } | null>(null)

  const seek = useCallback((t: number, play = true) => {
    const audio = ref.current
    if (!audio) return
    if (audio.readyState > 0) {
      audio.currentTime = t
      if (play) void audio.play()
    } else {
      pending.current = { t, play } // applied once the file's metadata has loaded
    }
  }, [])

  const props = {
    ref,
    onLoadedMetadata: (e: React.SyntheticEvent<HTMLAudioElement>) => {
      const next = pending.current
      if (!next) return
      pending.current = null
      e.currentTarget.currentTime = next.t
      if (next.play) void e.currentTarget.play()
    },
    onTimeUpdate: (e: React.SyntheticEvent<HTMLAudioElement>) => setTime(e.currentTarget.currentTime),
    onPlay: () => setPlaying(true),
    onPause: () => setPlaying(false),
  }
  return { props, time, playing, seek, pause: () => ref.current?.pause() }
}
