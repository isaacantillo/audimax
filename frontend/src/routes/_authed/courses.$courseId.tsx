import { useQuery } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'

import { listLecturesOptions } from '@/client/@tanstack/react-query.gen'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

export const Route = createFileRoute('/_authed/courses/$courseId')({ component: CoursePage })

function CoursePage() {
  const { courseId } = Route.useParams()
  const { data: lectures, isPending } = useQuery(listLecturesOptions({ path: { course_id: courseId } }))

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Lectures</h1>
      {isPending && <Skeleton className="h-24" />}
      {lectures?.map((lecture) => (
        <Link key={lecture.id} to="/lectures/$lectureId" params={{ lectureId: lecture.id }}>
          <Card className="transition hover:bg-accent">
            <CardHeader>
              <CardTitle>{lecture.title}</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">{lecture.summary}</CardContent>
          </Card>
        </Link>
      ))}
    </div>
  )
}
