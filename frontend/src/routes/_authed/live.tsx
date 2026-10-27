import { useMutation, useQuery } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Maximize2, Minus, Mic, Plus, Square } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import {
  discardLiveRecordingMutation,
  listCoursesOptions,
  saveLiveRecordingMutation,
} from '@/client/@tanstack/react-query.gen'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useLiveSubtitles, type LiveStatus } from '@/hooks/use-live-subtitles'
import { fmt } from '@/lib/format'
import { cn } from '@/lib/utils'

export const Route = createFileRoute('/_authed/live')({
  validateSearch: (search: Record<string, unknown>): { course?: string } =>
    typeof search.course === 'string' ? { course: search.course } : {},
  component: LivePage,
})

const STATUS_TEXT: Record<LiveStatus, string> = {
  idle: '',
  connecting: 'Connecting…',
  live: 'Live',
  reconnecting: 'Connection lost, reconnecting…',
  stopping: 'Finishing the last sentence…',
  stopped: 'Stopped',
}

const FONT_SIZES = [20, 26, 32, 40, 52, 64]

function LivePage() {
  const { course } = Route.useSearch()
  const live = useLiveSubtitles()
  const [fontStep, setFontStep] = useState(2)
  const box = useRef<HTMLDivElement>(null)
  const running = live.status === 'connecting' || live.status === 'live' || live.status === 'reconnecting'

  // Follow the newest line.
  useEffect(() => {
    box.current?.scrollTo({ top: box.current.scrollHeight, behavior: 'smooth' })
  }, [live.lines])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">Live subtitles</h1>
        {live.status !== 'idle' && (
          <span
            className={cn(
              'flex items-center gap-2 text-sm',
              live.status === 'live' ? 'text-red-600' : 'text-muted-foreground',
            )}
          >
            {live.status === 'live' && <span className="size-2 animate-pulse rounded-full bg-red-600" />}
            {STATUS_TEXT[live.status]} · {fmt(live.seconds)}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" size="icon" aria-label="Smaller text" disabled={fontStep === 0} onClick={() => setFontStep((s) => s - 1)}>
            <Minus />
          </Button>
          <Button
            variant="outline"
            size="icon"
            aria-label="Larger text"
            disabled={fontStep === FONT_SIZES.length - 1}
            onClick={() => setFontStep((s) => s + 1)}
          >
            <Plus />
          </Button>
          <Button variant="outline" size="icon" aria-label="Full screen" onClick={() => void box.current?.requestFullscreen?.()}>
            <Maximize2 />
          </Button>
          {running ? (
            <Button variant="destructive" onClick={() => void live.stop()}>
              <Square /> Stop
            </Button>
          ) : (
            <Button onClick={() => void live.start()} disabled={live.status === 'stopping' || live.status === 'stopped'}>
              <Mic /> Start
            </Button>
          )}
        </div>
      </div>

      {live.error && <p className="text-sm text-destructive">{live.error}</p>}

      <div
        ref={box}
        className="h-[60vh] overflow-y-auto rounded-lg bg-black px-6 py-5 leading-snug text-white [&:fullscreen]:h-screen [&:fullscreen]:px-12 [&:fullscreen]:py-10"
        style={{ fontSize: FONT_SIZES[fontStep] }}
      >
        {live.lines.length === 0 ? (
          <p className="text-white/40">
            {live.status === 'idle'
              ? 'Press Start and allow the microphone. Subtitles appear here as the lecturer speaks.'
              : 'Listening…'}
          </p>
        ) : (
          live.lines.map((line) => (
            <p key={line.id} className={cn('mb-3', !line.final && 'text-white/60')}>
              {line.text || '…'}
            </p>
          ))
        )}
      </div>

      {live.status === 'stopped' && live.sessionId && (
        <SaveRecording sessionId={live.sessionId} seconds={live.seconds} defaultCourse={course} onDone={live.reset} />
      )}
      {live.status === 'idle' && (
        <p className="text-sm text-muted-foreground">
          Keep this tab open and in front: the screen stays on while live, but switching apps pauses the microphone. The
          recording is kept, so you can save it as a lecture afterwards.
        </p>
      )}
    </div>
  )
}

function SaveRecording(props: { sessionId: string; seconds: number; defaultCourse?: string; onDone: () => void }) {
  const navigate = useNavigate()
  const { data: courses } = useQuery(listCoursesOptions())
  const [courseId, setCourseId] = useState(props.defaultCourse ?? '')
  const [title, setTitle] = useState('')
  const selected = courseId || courses?.[0]?.id || ''

  const save = useMutation({
    ...saveLiveRecordingMutation(),
    onSuccess: async (lecture) => {
      props.onDone()
      await navigate({ to: '/lectures/$lectureId', params: { lectureId: lecture.id } })
    },
  })
  const discard = useMutation({ ...discardLiveRecordingMutation(), onSuccess: props.onDone })

  return (
    <form
      className="max-w-xl space-y-3 rounded-md border p-4"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate({ path: { session_id: props.sessionId }, body: { course_id: selected, title } })
      }}
    >
      <h2 className="font-semibold">Save the recording as a lecture ({fmt(props.seconds)})</h2>
      <p className="text-sm text-muted-foreground">
        It then goes through the usual steps: an accurate transcript with timestamps, the translation and the summary.
      </p>
      <select
        className="h-9 w-full rounded-md border bg-background px-3 text-sm"
        value={selected}
        onChange={(e) => setCourseId(e.target.value)}
      >
        {courses?.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
      <Input placeholder="Title (optional, defaults to the date and time)" value={title} onChange={(e) => setTitle(e.target.value)} />
      {save.isError && <p className="text-sm text-destructive">Could not save the recording. Try again.</p>}
      {courses?.length === 0 && <p className="text-sm text-destructive">Create a course first to save the recording.</p>}
      <div className="flex gap-2">
        <Button type="submit" disabled={!selected || save.isPending}>
          {save.isPending ? 'Saving…' : 'Save as lecture'}
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={discard.isPending}
          onClick={() => discard.mutate({ path: { session_id: props.sessionId } })}
        >
          Discard
        </Button>
      </div>
    </form>
  )
}
