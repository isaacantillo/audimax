import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'

import {
  createEnglishMutation,
  deleteLectureMutation,
  getLectureOptions,
  getSummaryOptions,
  rerunChunkMutation,
} from '@/client/@tanstack/react-query.gen'
import type { EnglishChunk, EnglishParagraph, TranscriptDetails } from '@/client/types.gen'
import { ConfirmButton } from '@/components/confirm-button'
import { Markdown } from '@/components/markdown'
import { StatusBadge } from '@/components/status-badge'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useOriginalPlayer, useSimplePlayer } from '@/hooks/use-original-player'
import { activeIndex, fmt, isBusy } from '@/lib/format'

const TABS = ['transcript', 'summary'] as const
type Tab = (typeof TABS)[number]
type Mode = 'original' | 'english'

export const Route = createFileRoute('/_authed/lectures/$lectureId')({
  validateSearch: (s: Record<string, unknown>): { tab?: Tab; t?: number; et?: number; mode?: 'english' } => {
    const t = Number(s.t)
    const et = Number(s.et)
    return {
      tab: TABS.find((x) => x === s.tab),
      t: s.t !== undefined && Number.isFinite(t) ? t : undefined,
      et: s.et !== undefined && Number.isFinite(et) ? et : undefined,
      mode: s.mode === 'english' ? 'english' : undefined,
    }
  },
  component: LectureView,
})

function LectureView() {
  const { lectureId } = Route.useParams()
  const search = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const queryClient = useQueryClient()
  const { data: lecture, isPending } = useQuery({
    ...getLectureOptions({ path: { lecture_id: lectureId } }),
    refetchInterval: (q) => (isBusy(q.state.data?.status) ? 3000 : false),
  })

  const parts = lecture?.parts ?? []
  const original = useOriginalPlayer(parts)
  const english = useSimplePlayer()
  const [mode, setMode] = useState<Mode>(search.mode ?? 'original')

  // Arrived from a search hit: cue the original recording, or the English audio, at that moment
  // (without playing). The seek waits for the audio's metadata if it has not loaded yet.
  const cued = useRef(false)
  useEffect(() => {
    if (!lecture || cued.current) return
    if (search.t !== undefined) {
      cued.current = true
      original.seek(search.t, false)
    } else if (search.et !== undefined && lecture.english?.audio_url) {
      cued.current = true
      english.seek(search.et, false)
    }
  }, [lecture, search.t, search.et, original, english])

  const remove = useMutation({
    ...deleteLectureMutation(),
    onSuccess: async () => {
      const courseId = lecture?.course_id
      await queryClient.invalidateQueries()
      if (courseId) await navigate({ to: '/courses/$courseId', params: { courseId } })
    },
  })

  if (isPending) return <Skeleton className="h-64" />
  if (!lecture) return <p className="text-destructive">Lecture not found.</p>

  const hasEnglishAudio = !!lecture.english?.audio_url

  function switchMode(next: Mode) {
    if (next === mode) return
    original.pause()
    english.pause()
    setMode(next)
  }
  function hearOriginal(p: EnglishParagraph) {
    english.pause()
    setMode('original')
    original.seek(p.source_start)
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Link to="/courses/$courseId" params={{ courseId: lecture.course_id }} className="text-sm text-muted-foreground hover:underline">
          ← Course
        </Link>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="flex flex-wrap items-center gap-2 text-2xl font-semibold">
            {lecture.title}
            <StatusBadge status={lecture.status} />
          </h1>
          <ConfirmButton label="Delete" question="Delete this lecture and its audio?" variant="destructive" onConfirm={() => remove.mutate({ path: { lecture_id: lectureId } })} />
        </div>
        {lecture.status === 'failed' && (
          <p className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm">
            <strong>Processing failed.</strong> {lecture.error} <Link to="/activity" className="underline">Retry from Activity</Link>.
          </p>
        )}
      </div>

      {parts.length > 0 && (
        <div className="space-y-2 rounded-md border p-3">
          {hasEnglishAudio && (
            <div className="flex gap-1 text-sm">
              <Button size="sm" variant={mode === 'original' ? 'default' : 'outline'} onClick={() => switchMode('original')}>
                Original (German)
              </Button>
              <Button size="sm" variant={mode === 'english' ? 'default' : 'outline'} onClick={() => switchMode('english')}>
                English version
              </Button>
            </div>
          )}
          <audio key={original.audioKey} {...original.props} controls className={mode === 'original' ? 'w-full' : 'hidden'} />
          {hasEnglishAudio && <audio {...english.props} src={lecture.english!.audio_url!} preload="metadata" controls className={mode === 'english' ? 'w-full' : 'hidden'} />}
          {parts.length > 1 && mode === 'original' && (
            <p className="text-xs text-muted-foreground">
              {parts.length} recordings play as one lecture. Now: part {original.partIndex + 1}.
            </p>
          )}
        </div>
      )}

      <Tabs value={search.tab ?? 'transcript'} onValueChange={(t) => void navigate({ search: (prev) => ({ ...prev, tab: t as Tab }) })}>
        <TabsList>
          <TabsTrigger value="transcript">Transcript</TabsTrigger>
          <TabsTrigger value="summary">Summary</TabsTrigger>
        </TabsList>
        <TabsContent value="transcript" className="space-y-4">
          <EnglishPanel lecture={lecture} />
          {lecture.transcript_segments.length > 0 && <DownloadTranscript lectureId={lecture.id} />}
          {mode === 'english' && lecture.english ? (
            <EnglishScript lecture={lecture} time={english.time} playing={english.playing} onSeek={(t) => english.seek(t)} onHearOriginal={hearOriginal} />
          ) : (
            <OriginalTranscript segments={lecture.transcript_segments} time={original.time} playing={original.playing} onSeek={(t) => original.seek(t)} status={lecture.status} />
          )}
        </TabsContent>
        <TabsContent value="summary">
          <Summary lectureId={lectureId} ready={lecture.transcript_segments.length > 0} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function OriginalTranscript({
  segments,
  time,
  playing,
  onSeek,
  status,
}: {
  segments: TranscriptDetails['transcript_segments']
  time: number
  playing: boolean
  onSeek: (t: number) => void
  status: string
}) {
  const active = activeIndex(segments, time)
  const rows = useRef<(HTMLDivElement | null)[]>([])
  useEffect(() => {
    if (playing && active >= 0) rows.current[active]?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [active, playing])

  if (segments.length === 0)
    return <p className="text-muted-foreground">{isBusy(status as never) ? 'The transcript appears as soon as processing reaches it…' : 'No transcript.'}</p>
  return (
    <div className="space-y-2">
      {segments.map((s, i) => (
        <div
          key={i}
          ref={(el) => {
            rows.current[i] = el
          }}
          onClick={() => onSeek(s.start)}
          className={`cursor-pointer rounded-md border p-3 transition hover:bg-accent/60 ${i === active ? 'bg-accent' : ''}`}
        >
          <div className="mb-1 text-xs text-muted-foreground">{fmt(s.start)}</div>
          <p>{s.text_original}</p>
          {s.text_translated && <p className="text-muted-foreground">{s.text_translated}</p>}
        </div>
      ))}
    </div>
  )
}

/** Plain links: the browser sends the session cookie and saves the file the server names. */
function DownloadTranscript({ lectureId }: { lectureId: string }) {
  const link = (version: 'original' | 'translation' | 'both', label: string) => (
    <a
      key={version}
      href={`/api/lectures/${lectureId}/transcript.txt?version=${version}`}
      download
      className={buttonVariants({ variant: 'outline', size: 'sm' })}
    >
      {label}
    </a>
  )
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-muted-foreground">Download as .txt:</span>
      {link('original', 'German')}
      {link('translation', 'English translation')}
      {link('both', 'Both')}
    </div>
  )
}

const STEPS: { status: string; label: string }[] = [
  { status: 'chunking', label: 'Planning topics and checklists' },
  { status: 'scripting', label: 'Writing and checking the script' },
  { status: 'voicing', label: 'Recording the voice' },
  { status: 'assembling', label: 'Assembling the audio' },
]

function EnglishPanel({ lecture }: { lecture: TranscriptDetails }) {
  const queryClient = useQueryClient()
  const create = useMutation({ ...createEnglishMutation(), onSuccess: () => void queryClient.invalidateQueries() })
  const busyIndex = STEPS.findIndex((s) => s.status === lecture.status)

  if (busyIndex >= 0)
    return (
      <div className="rounded-md border p-4">
        <h2 className="mb-2 font-semibold">Creating the English version…</h2>
        <ol className="space-y-1 text-sm">
          {STEPS.map((s, i) => (
            <li key={s.status} className={i < busyIndex ? 'text-muted-foreground line-through' : i === busyIndex ? 'font-medium animate-pulse' : 'text-muted-foreground'}>
              {i + 1}. {s.label}
            </li>
          ))}
        </ol>
      </div>
    )

  if (!lecture.english && (lecture.status === 'ready' || lecture.status === 'failed') && lecture.transcript_segments.length > 0)
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-4">
        <p className="max-w-xl text-sm">
          <strong>English version.</strong> Re-performs the lecture as a fluent English professor would give it: every explanation, example, tip and exam hint kept,
          the noise removed. Costs about $1–2 of text-to-speech and takes a few minutes.
        </p>
        <ConfirmButton label="Create English version" question="Start it now?" variant="default" disabled={create.isPending} onConfirm={() => create.mutate({ path: { lecture_id: lecture.id } })} />
      </div>
    )

  if (lecture.english && lecture.status === 'english_ready')
    return (
      <p className="text-sm text-muted-foreground">
        English version ready: {fmt(lecture.english.duration_seconds)} (original {fmt(lecture.duration_seconds)}), voice: {lecture.english.tts_provider}. Use the buttons above the player to switch.
      </p>
    )
  return null
}

function EnglishScript({
  lecture,
  time,
  playing,
  onSeek,
  onHearOriginal,
}: {
  lecture: TranscriptDetails
  time: number
  playing: boolean
  onSeek: (t: number) => void
  onHearOriginal: (p: EnglishParagraph) => void
}) {
  const queryClient = useQueryClient()
  const rerun = useMutation({ ...rerunChunkMutation(), onSuccess: () => void queryClient.invalidateQueries() })
  const flat = lecture.english!.chunks.flatMap((c) => c.paragraphs)
  const timed = flat.filter((p) => p.start != null).map((p) => ({ ...p, start: p.start! }))
  const active = activeIndex(timed, time)
  const activeId = active >= 0 ? timed[active].id : null
  const refs = useRef<Record<string, HTMLDivElement | null>>({})
  useEffect(() => {
    if (playing && activeId) refs.current[activeId]?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [activeId, playing])
  const canRerun = lecture.status === 'english_ready' || lecture.status === 'failed'

  return (
    <div className="space-y-6">
      {lecture.english!.chunks.map((chunk: EnglishChunk) => (
        <section key={chunk.n} className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold">{chunk.title}</h3>
            {chunk.status === 'skipped' && <Badge variant="outline">left out: only logistics</Badge>}
            {chunk.status === 'done' && !chunk.verified && <Badge variant="destructive" title="The check still found a missing or invented item after 3 tries. Rewrite it.">unverified</Badge>}
            {chunk.status === 'pending' && <Badge className="animate-pulse">rewriting</Badge>}
            {chunk.status !== 'skipped' && canRerun && (
              <Button variant="ghost" size="sm" disabled={rerun.isPending} onClick={() => rerun.mutate({ path: { lecture_id: lecture.id, n: chunk.n } })}>
                Rewrite this part
              </Button>
            )}
          </div>
          {chunk.paragraphs.map((p) => (
            <div
              key={p.id}
              ref={(el) => {
                refs.current[p.id] = el
              }}
              className={`rounded-md border p-3 ${p.id === activeId ? 'bg-accent' : ''}`}
            >
              <p className="leading-relaxed">{p.text}</p>
              <div className="mt-2 flex gap-3 text-xs">
                {p.start != null && (
                  <button className="text-muted-foreground underline hover:text-foreground" onClick={() => onSeek(p.start!)}>
                    ▶ Play {fmt(p.start)}
                  </button>
                )}
                <button className="text-muted-foreground underline hover:text-foreground" onClick={() => onHearOriginal(p)}>
                  Hear original ({fmt(p.source_start)})
                </button>
              </div>
            </div>
          ))}
        </section>
      ))}
    </div>
  )
}

function Summary({ lectureId, ready }: { lectureId: string; ready: boolean }) {
  const { data, isPending } = useQuery({ ...getSummaryOptions({ path: { lecture_id: lectureId } }), enabled: ready })
  if (!ready || isPending) return <p className="text-muted-foreground">The summary appears when processing finishes.</p>
  return data?.summary ? <Markdown>{data.summary}</Markdown> : <p className="text-muted-foreground">No summary yet.</p>
}
