import { useQuery } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'

import { listCoursesOptions } from '@/client/@tanstack/react-query.gen'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

export const Route = createFileRoute('/_authed/')({ component: CourseList })

function CourseList() {
  const { data: courses, isPending, error } = useQuery(listCoursesOptions())

  if (error) return <p className="text-destructive">Could not load courses.</p>

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Courses</h1>
      <div className="grid gap-4 sm:grid-cols-2">
        {isPending && <Skeleton className="h-28" />}
        {courses?.map((course) => (
          <Link key={course.id} to="/courses/$courseId" params={{ courseId: course.id }}>
            <Card className="transition hover:bg-accent">
              <CardHeader>
                <CardTitle className="flex items-center justify-between">
                  {course.name}
                  {course.has_active_jobs && <Badge>processing</Badge>}
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                {course.lecture_count} lectures · {course.document_count} documents · last activity{' '}
                {new Date(course.last_activity_at).toLocaleDateString()}
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  )
}
