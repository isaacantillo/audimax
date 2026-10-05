import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'

import { getLectureOptions } from '@/client/@tanstack/react-query.gen'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

export const Route = createFileRoute('/lectures/$lectureId')({ component: LectureView })

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

function LectureView() {
  const { lectureId } = Route.useParams()
  const { data: lecture, isPending } = useQuery(getLectureOptions({ path: { lecture_id: lectureId } }))
  const [time, setTime] = useState(0)

  if (isPending) return <Skeleton className="h-64" />
  if (!lecture) return <p className="text-destructive">Lecture not found.</p>

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{lecture.title}</h1>
      <audio controls className="w-full" src={lecture.audio_url} onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)} />
      <Tabs defaultValue="transcript">
        <TabsList>
          <TabsTrigger value="transcript">Transcript</TabsTrigger>
          <TabsTrigger value="summary" disabled>Summary</TabsTrigger>
          <TabsTrigger value="mindmap" disabled>Mind map</TabsTrigger>
          <TabsTrigger value="chat" disabled>Chat</TabsTrigger>
        </TabsList>
        <TabsContent value="transcript" className="space-y-3">
          {lecture.transcript_segments.map((seg) => {
            const active = time >= seg.start && time < seg.end
            return (
              <div key={seg.start} className={`rounded-md border p-3 ${active ? 'bg-accent' : ''}`}>
                <div className="mb-1 text-xs text-muted-foreground">{fmt(seg.start)}</div>
                <p>{seg.text_original}</p>
                {seg.text_translated && <p className="text-muted-foreground">{seg.text_translated}</p>}
              </div>
            )
          })}
        </TabsContent>
      </Tabs>
    </div>
  )
}
