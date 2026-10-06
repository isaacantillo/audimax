import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import { useEffect, useState } from 'react'

import {
  courseMindmapOptions,
  deleteCourseMutation,
  getChatSelectionOptions,
  getCourseOptions,
  listDocumentsOptions,
  listLecturesOptions,
  refreshCourseMindmapMutation,
  setChatSelectionMutation,
} from '@/client/@tanstack/react-query.gen'
import { Chat } from '@/components/chat'
import { ConfirmButton } from '@/components/confirm-button'
import { MindMap } from '@/components/mindmap'
import { StatusBadge } from '@/components/status-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { fmt, isBusy } from '@/lib/format'
import { uploadDocument, uploadLecture } from '@/lib/upload'

const TABS = ['lectures', 'documents', 'chat', 'mindmap'] as const
type Tab = (typeof TABS)[number]

export const Route = createFileRoute('/_authed/courses/$courseId')({
  validateSearch: (s: Record<string, unknown>): { tab?: Tab } => ({ tab: TABS.find((t) => t === s.tab) }),
  component: CoursePage,
})

function CoursePage() {
  const { courseId } = Route.useParams()
  const { tab = 'lectures' } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const queryClient = useQueryClient()
  const course = useQuery(getCourseOptions({ path: { course_id: courseId } }))
  const remove = useMutation({
    ...deleteCourseMutation(),
    onSuccess: async () => {
      await queryClient.invalidateQueries()
      await navigate({ to: '/' })
    },
  })

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">{course.data?.name ?? <Skeleton className="h-8 w-60" />}</h1>
        <ConfirmButton label="Delete course" question="Delete the course and everything in it?" variant="destructive" onConfirm={() => remove.mutate({ path: { course_id: courseId } })} />
      </div>
      <Tabs value={tab} onValueChange={(t) => void navigate({ search: { tab: t as Tab } })}>
        <TabsList>
          <TabsTrigger value="lectures">Lectures</TabsTrigger>
          <TabsTrigger value="documents">Documents</TabsTrigger>
          <TabsTrigger value="chat">Chat</TabsTrigger>
          <TabsTrigger value="mindmap">Mind map</TabsTrigger>
        </TabsList>
        <TabsContent value="lectures"><Lectures courseId={courseId} /></TabsContent>
        <TabsContent value="documents"><Documents courseId={courseId} /></TabsContent>
        <TabsContent value="chat"><CourseChat courseId={courseId} /></TabsContent>
        <TabsContent value="mindmap"><CourseMindMap courseId={courseId} /></TabsContent>
      </Tabs>
    </div>
  )
}

function Lectures({ courseId }: { courseId: string }) {
  const queryClient = useQueryClient()
  const options = listLecturesOptions({ path: { course_id: courseId } })
  const { data: lectures, isPending } = useQuery({
    ...options,
    refetchInterval: (q) => (q.state.data?.some((l) => isBusy(l.status)) ? 3000 : false),
  })
  const [title, setTitle] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [english, setEnglish] = useState(false)
  const upload = useMutation({
    mutationFn: () => uploadLecture({ courseId, title, files, english }),
    onSuccess: () => {
      setTitle('')
      setFiles([])
      setEnglish(false)
      void queryClient.invalidateQueries()
    },
  })

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        {isPending && <Skeleton className="h-24" />}
        {lectures?.length === 0 && <p className="text-muted-foreground">No lectures yet. Upload a recording below.</p>}
        {lectures?.map((l) => (
          <Link key={l.id} to="/lectures/$lectureId" params={{ lectureId: l.id }}>
            <Card className="transition hover:bg-accent">
              <CardHeader>
                <CardTitle className="flex flex-wrap items-center gap-2">
                  {l.title}
                  <StatusBadge status={l.status} />
                  {l.has_english && <Badge variant="outline">English audio</Badge>}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 text-sm text-muted-foreground">
                <div>
                  {l.date && new Date(l.date).toLocaleDateString()}
                  {l.duration_seconds > 0 && ` · ${fmt(l.duration_seconds)}`}
                  {l.document_count > 0 && ` · ${l.document_count} documents`}
                </div>
                {l.summary && <p className="line-clamp-2">{l.summary.replace(/[#*_-]/g, '')}</p>}
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      <form
        className="max-w-xl space-y-3 rounded-md border p-4"
        onSubmit={(e) => {
          e.preventDefault()
          upload.mutate()
        }}
      >
        <h2 className="font-semibold">Upload a lecture</h2>
        <Input placeholder="Title (optional)" value={title} onChange={(e) => setTitle(e.target.value)} />
        <Input type="file" multiple accept="audio/*,.m4a,.mp3,.wav,.flac,.ogg,.aac" onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
        <p className="text-xs text-muted-foreground">
          One lecture in several recordings? Select them all: they are joined in filename order (SE1_L1_1, SE1_L1_2…).
        </p>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={english} onCheckedChange={(v) => setEnglish(v === true)} />
          Also create the English version (about $1–2 of text-to-speech per lecture)
        </label>
        {upload.isError && <p className="text-sm text-destructive">{upload.error.message}</p>}
        <Button type="submit" disabled={files.length === 0 || upload.isPending}>
          {upload.isPending ? 'Uploading…' : `Upload${files.length > 1 ? ` ${files.length} files` : ''}`}
        </Button>
      </form>
    </div>
  )
}

function Documents({ courseId }: { courseId: string }) {
  const queryClient = useQueryClient()
  const { data: docs } = useQuery({
    ...listDocumentsOptions({ path: { course_id: courseId } }),
    refetchInterval: (q) => (q.state.data?.some((d) => d.status === 'queued' || d.status === 'processing') ? 3000 : false),
  })
  const { data: lectures } = useQuery(listLecturesOptions({ path: { course_id: courseId } }))
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [lectureId, setLectureId] = useState('')
  const upload = useMutation({
    mutationFn: () => uploadDocument({ courseId, lectureId: lectureId || undefined, title, file: file! }),
    onSuccess: () => {
      setFile(null)
      setTitle('')
      void queryClient.invalidateQueries()
    },
  })

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        {docs?.length === 0 && <p className="text-muted-foreground">No slides or scriptum yet.</p>}
        {docs?.map((d) => (
          <Link key={d.id} to="/documents/$documentId" params={{ documentId: d.id }}>
            <Card className="transition hover:bg-accent">
              <CardHeader>
                <CardTitle className="flex flex-wrap items-center gap-2">
                  {d.title}
                  <Badge variant={d.status === 'failed' ? 'destructive' : d.status === 'ready' ? 'secondary' : 'default'}>{d.status}</Badge>
                  {d.lecture && <Badge variant="outline">{d.lecture.title}</Badge>}
                </CardTitle>
              </CardHeader>
            </Card>
          </Link>
        ))}
      </div>
      <form
        className="max-w-xl space-y-3 rounded-md border p-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (file) upload.mutate()
        }}
      >
        <h2 className="font-semibold">Upload slides or a scriptum (PDF)</h2>
        <Input type="file" accept="application/pdf,.pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <Input placeholder="Title (optional)" value={title} onChange={(e) => setTitle(e.target.value)} />
        <select className="h-9 w-full rounded-md border bg-background px-3 text-sm" value={lectureId} onChange={(e) => setLectureId(e.target.value)}>
          <option value="">Not tied to a lecture</option>
          {lectures?.map((l) => (
            <option key={l.id} value={l.id}>
              Belongs to: {l.title}
            </option>
          ))}
        </select>
        {upload.isError && <p className="text-sm text-destructive">{upload.error.message}</p>}
        <Button type="submit" disabled={!file || upload.isPending}>
          {upload.isPending ? 'Uploading…' : 'Upload'}
        </Button>
      </form>
    </div>
  )
}

function CourseChat({ courseId }: { courseId: string }) {
  const { data: lectures } = useQuery(listLecturesOptions({ path: { course_id: courseId } }))
  const { data: docs } = useQuery(listDocumentsOptions({ path: { course_id: courseId } }))
  const saved = useQuery(getChatSelectionOptions({ path: { course_id: courseId } }))
  const save = useMutation(setChatSelectionMutation())
  const [lectureIds, setLectureIds] = useState<string[]>([])
  const [documentIds, setDocumentIds] = useState<string[]>([])
  const [web, setWeb] = useState(false)
  const [restored, setRestored] = useState(false)

  // Start from what was selected last time.
  useEffect(() => {
    if (saved.data && !restored) {
      setLectureIds(saved.data.lecture_ids)
      setDocumentIds(saved.data.document_ids)
      setWeb(saved.data.web ?? false)
      setRestored(true)
    }
  }, [saved.data, restored])

  function change(next: { lectureIds?: string[]; documentIds?: string[]; web?: boolean }) {
    const l = next.lectureIds ?? lectureIds
    const d = next.documentIds ?? documentIds
    const w = next.web ?? web
    setLectureIds(l)
    setDocumentIds(d)
    setWeb(w)
    save.mutate({ path: { course_id: courseId }, body: { lecture_ids: l, document_ids: d, web: w } })
  }
  const toggle = (list: string[], id: string) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id])

  const usableLectures = lectures?.filter((l) => l.status === 'ready' || l.status === 'english_ready') ?? []
  const usableDocs = docs?.filter((d) => d.status === 'ready') ?? []

  return (
    <div className="grid gap-6 md:grid-cols-[16rem_1fr]">
      <aside className="space-y-3 text-sm">
        <h2 className="font-semibold">Sources</h2>
        {usableLectures.length + usableDocs.length === 0 && <p className="text-muted-foreground">Nothing is ready to chat with yet.</p>}
        {usableLectures.map((l) => (
          <label key={l.id} className="flex items-start gap-2">
            <Checkbox checked={lectureIds.includes(l.id)} onCheckedChange={() => change({ lectureIds: toggle(lectureIds, l.id) })} />
            <span>{l.title}</span>
          </label>
        ))}
        {usableDocs.map((d) => (
          <label key={d.id} className="flex items-start gap-2">
            <Checkbox checked={documentIds.includes(d.id)} onCheckedChange={() => change({ documentIds: toggle(documentIds, d.id) })} />
            <span>{d.title} <span className="text-muted-foreground">(slides)</span></span>
          </label>
        ))}
        <label className="flex items-center gap-2 border-t pt-3">
          <Checkbox checked={web} onCheckedChange={(v) => change({ web: v === true })} />
          Also search the web
        </label>
        <div className="flex gap-2 text-xs">
          <button className="underline" onClick={() => change({ lectureIds: usableLectures.map((l) => l.id), documentIds: usableDocs.map((d) => d.id) })}>All</button>
          <button className="underline" onClick={() => change({ lectureIds: [], documentIds: [] })}>None</button>
        </div>
      </aside>
      <Chat courseId={courseId} lectureIds={lectureIds} documentIds={documentIds} web={web} />
    </div>
  )
}

function CourseMindMap({ courseId }: { courseId: string }) {
  const queryClient = useQueryClient()
  const options = courseMindmapOptions({ path: { course_id: courseId } })
  const { data, isPending } = useQuery(options)
  const refresh = useMutation({
    ...refreshCourseMindmapMutation(),
    onSuccess: (map) => queryClient.setQueryData(options.queryKey, map),
  })
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">One map across all lectures of the course.</p>
        <Button variant="outline" size="sm" disabled={refresh.isPending} onClick={() => refresh.mutate({ path: { course_id: courseId } })}>
          {refresh.isPending ? 'Regenerating…' : 'Regenerate'}
        </Button>
      </div>
      {isPending ? <Skeleton className="h-96" /> : data && <MindMap data={data} />}
    </div>
  )
}
