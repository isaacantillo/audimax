import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { deleteCourseMutation, getCourseOptions, listLecturesOptions } from '@/client/@tanstack/react-query.gen'
import { ConfirmButton } from '@/components/confirm-button'
import { StatusBadge } from '@/components/status-badge'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { fmt, isBusy } from '@/lib/format'
import { uploadLecture } from '@/lib/upload'

export const Route = createFileRoute('/_authed/courses/$courseId')({ component: CoursePage })

function CoursePage() {
  const { courseId } = Route.useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const course = useQuery(getCourseOptions({ path: { course_id: courseId } }))
  const remove = useMutation({
    ...deleteCourseMutation(),
    onSuccess: async () => {
      await queryClient.invalidateQueries()
      await navigate({ to: '/' })
    },
  })

  const { data: lectures, isPending } = useQuery({
    ...listLecturesOptions({ path: { course_id: courseId } }),
    refetchInterval: (q) => (q.state.data?.some((l) => isBusy(l.status)) ? 3000 : false),
  })
  const [title, setTitle] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const upload = useMutation({
    mutationFn: () => uploadLecture({ courseId, title, files }),
    onSuccess: () => {
      setTitle('')
      setFiles([])
      void queryClient.invalidateQueries()
    },
  })

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">{course.data?.name ?? <Skeleton className="h-8 w-60" />}</h1>
        <div className="flex items-center gap-2">
          <Link to="/live" search={{ course: courseId }} className={buttonVariants({ variant: 'outline' })}>
            Go live
          </Link>
          <ConfirmButton label="Delete course" question="Delete the course and all its lectures?" variant="destructive" onConfirm={() => remove.mutate({ path: { course_id: courseId } })} />
        </div>
      </div>

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
                  {l.has_english && <Badge variant="outline">English version</Badge>}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 text-sm text-muted-foreground">
                <div>
                  {l.date && new Date(l.date).toLocaleDateString()}
                  {l.duration_seconds > 0 && ` · ${fmt(l.duration_seconds)}`}
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
        {upload.isError && <p className="text-sm text-destructive">{upload.error.message}</p>}
        <Button type="submit" disabled={files.length === 0 || upload.isPending}>
          {upload.isPending ? 'Uploading…' : `Upload${files.length > 1 ? ` ${files.length} files` : ''}`}
        </Button>
      </form>
    </div>
  )
}
