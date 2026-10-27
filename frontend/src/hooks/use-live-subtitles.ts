import { useCallback, useEffect, useRef, useState } from 'react'

export type SubtitleLine = { id: string; text: string; final: boolean }
export type LiveStatus = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'stopping' | 'stopped'

type ServerEvent =
  | { type: 'item'; id: string; previous: string | null }
  | { type: 'delta'; id: string; text: string }
  | { type: 'final'; id: string; text: string }
  | { type: 'error'; message: string }

// Pause detection: the transcription model waits for us to say where a stretch of speech ends.
const FRAME_MS = 100
const MIN_SPEECH_MS = 1500 // speak at least this long before a pause counts
const PAUSE_MS = 600
const MAX_STRETCH_MS = 12000 // commit anyway, so a non-stop speaker still gets subtitles
const MAX_BUFFERED_FRAMES = 600 // keep up to 60 s of audio while reconnecting
const FINAL_WAIT_MS = 4000

function insertLine(lines: SubtitleLine[], id: string, previous: string | null): SubtitleLine[] {
  if (lines.some((l) => l.id === id)) return lines
  const line = { id, text: '', final: false }
  const after = previous ? lines.findIndex((l) => l.id === previous) : -1
  return after === -1 ? [...lines, line] : [...lines.slice(0, after + 1), line, ...lines.slice(after + 1)]
}

function apply(lines: SubtitleLine[], event: ServerEvent): SubtitleLine[] {
  if (event.type === 'item') return insertLine(lines, event.id, event.previous)
  if (event.type === 'error') return lines
  const withLine = insertLine(lines, event.id, null)
  if (event.type === 'final' && !event.text.trim()) return withLine.filter((l) => l.id !== event.id) // silence
  return withLine.map((l) =>
    l.id !== event.id
      ? l
      : event.type === 'delta'
        ? { ...l, text: l.final ? l.text : l.text + event.text }
        : { ...l, text: event.text.trim(), final: true },
  )
}

/** Mic -> server -> OpenAI realtime transcription -> subtitle lines. The server also keeps the audio
 * under `sessionId`, so the recording can be saved as a lecture after `stop()`. */
export function useLiveSubtitles() {
  const [status, setStatus] = useState<LiveStatus>('idle')
  const [lines, setLines] = useState<SubtitleLine[]>([])
  const [error, setError] = useState<string | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [seconds, setSeconds] = useState(0)

  const statusRef = useRef<LiveStatus>('idle')
  const ws = useRef<WebSocket | null>(null)
  const audio = useRef<{ ctx: AudioContext; stream: MediaStream } | null>(null)
  const wakeLock = useRef<WakeLockSentinel | null>(null)
  const pending = useRef<ArrayBuffer[]>([])
  const vad = useRef({ floor: 0.01, speechMs: 0, silenceMs: 0, stretchMs: 0 })
  const frames = useRef(0)

  const setBoth = (s: LiveStatus) => {
    statusRef.current = s
    setStatus(s)
  }

  const send = (data: ArrayBuffer | string) => {
    const socket = ws.current
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(data)
      return true
    }
    return false
  }

  const commit = () => {
    vad.current = { ...vad.current, speechMs: 0, silenceMs: 0, stretchMs: 0 }
    send(JSON.stringify({ type: 'commit' }))
  }

  const onFrame = (pcm: ArrayBuffer, rms: number) => {
    frames.current += 1
    if (frames.current % (1000 / FRAME_MS) === 0) setSeconds(frames.current / (1000 / FRAME_MS))
    if (!send(pcm)) {
      pending.current.push(pcm)
      if (pending.current.length > MAX_BUFFERED_FRAMES) pending.current.shift()
      return
    }
    // A slowly rising noise floor that drops at once to anything quieter: speech is well above it.
    const v = vad.current
    v.floor = rms < v.floor ? rms : v.floor + (rms - v.floor) * 0.002
    const speaking = rms > Math.max(0.012, v.floor * 3)
    v.stretchMs += FRAME_MS
    if (speaking) {
      v.speechMs += FRAME_MS
      v.silenceMs = 0
    } else {
      v.silenceMs += FRAME_MS
    }
    if ((v.speechMs >= MIN_SPEECH_MS && v.silenceMs >= PAUSE_MS) || v.stretchMs >= MAX_STRETCH_MS) commit()
  }

  const connect = useCallback((id: string) => {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
    const socket = new WebSocket(`${scheme}://${location.host}/api/live/ws?session=${id}`)
    socket.binaryType = 'arraybuffer'
    ws.current = socket
    socket.onopen = () => {
      if (statusRef.current === 'connecting' || statusRef.current === 'reconnecting') setBoth('live')
      for (const pcm of pending.current.splice(0)) socket.send(pcm)
      setError(null)
    }
    socket.onmessage = (e) => {
      const event = JSON.parse(e.data as string) as ServerEvent
      if (event.type === 'error') setError(event.message)
      setLines((current) => apply(current, event))
    }
    socket.onclose = (e) => {
      if (ws.current !== socket) return
      ws.current = null
      if (e.code === 4401) {
        setError('Your session expired. Log in again, then start a new live session.')
        void teardown('stopped')
        return
      }
      if (statusRef.current === 'live' || statusRef.current === 'connecting' || statusRef.current === 'reconnecting') {
        setBoth('reconnecting')
        setTimeout(() => {
          if (statusRef.current === 'reconnecting') connect(id)
        }, 1500)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const acquireWakeLock = async () => {
    try {
      wakeLock.current = (await navigator.wakeLock?.request('screen')) ?? null
    } catch {
      wakeLock.current = null // not supported or refused: the screen may sleep
    }
  }

  const teardown = async (next: LiveStatus) => {
    ws.current?.close()
    ws.current = null
    audio.current?.stream.getTracks().forEach((t) => t.stop())
    await audio.current?.ctx.close().catch(() => {})
    audio.current = null
    await wakeLock.current?.release().catch(() => {})
    wakeLock.current = null
    pending.current = []
    setBoth(next)
  }

  const start = useCallback(async () => {
    setError(null)
    setLines([])
    setSeconds(0)
    frames.current = 0
    setBoth('connecting')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: false, noiseSuppression: true, autoGainControl: true },
      })
      const ctx = new AudioContext()
      await ctx.audioWorklet.addModule('/pcm-worklet.js')
      const node = new AudioWorkletNode(ctx, 'pcm-worklet')
      node.port.onmessage = (e: MessageEvent<{ pcm: ArrayBuffer; rms: number }>) => onFrame(e.data.pcm, e.data.rms)
      ctx.createMediaStreamSource(stream).connect(node)
      audio.current = { ctx, stream }
      const id = crypto.randomUUID()
      setSessionId(id)
      vad.current = { floor: 0.01, speechMs: 0, silenceMs: 0, stretchMs: 0 }
      await acquireWakeLock()
      connect(id)
    } catch (e) {
      setError(
        e instanceof DOMException && e.name === 'NotAllowedError'
          ? 'Microphone access was denied. Allow it in the browser settings and try again.'
          : `Could not start: ${e instanceof Error ? e.message : String(e)}`,
      )
      await teardown('idle')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connect])

  /** Stop listening; the last stretch of speech is committed and given a moment to come back. */
  const stop = useCallback(async () => {
    if (statusRef.current === 'idle' || statusRef.current === 'stopped') return
    setBoth('stopping')
    audio.current?.stream.getTracks().forEach((t) => t.stop())
    commit()
    await new Promise((resolve) => setTimeout(resolve, FINAL_WAIT_MS))
    await teardown('stopped')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const reset = useCallback(() => {
    setLines([])
    setSessionId(null)
    setSeconds(0)
    setError(null)
    setBoth('idle')
  }, [])

  // The wake lock is dropped whenever the page is hidden; take it back when it returns.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible' && statusRef.current === 'live') void acquireWakeLock()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [])

  // Leaving the page ends the session (the recording stays on the server until saved or discarded).
  useEffect(
    () => () => {
      void teardown('stopped')
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  return { status, lines, error, sessionId, seconds, start, stop, reset }
}
