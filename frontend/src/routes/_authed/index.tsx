import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'

import { createCourseMutation, listCoursesOptions } from '@/client/@tanstack/react-query.gen'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'

export const Route = createFileRoute('/_authed/')({ component: CourseList })

function CourseList() {
  const queryClient = useQueryClient()
  const { data: courses, isPending, error } = useQuery({
    ...listCoursesOptions(),
    refetchInterval: (q) => (q.state.data?.some((c) => c.has_active_jobs) ? 4000 : false),
  })
  const [name, setName] = useState('')
  const create = useMutation({
    ...createCourseMutation(),
    onSuccess: () => {
      setName('')
      void queryClient.invalidateQueries({ queryKey: listCoursesOptions().queryKey })
    },
  })

  if (error) return <p className="text-destructive">Could not load courses.</p>

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Courses</h1>
      <div className="grid gap-4 sm:grid-cols-2">
        {isPending && <Skeleton className="h-28" />}
        {courses?.map((course) => (
          <Link key={course.id} to="/courses/$courseId" params={{ courseId: course.id }}>
            <Card className="transition hover:bg-accent">
              <CardHeader>
                <CardTitle className="flex items-center justify-between">
                  {course.name}
                  {course.has_active_jobs && <Badge className="animate-pulse">processing</Badge>}
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
      {courses?.length === 0 && <p className="text-muted-foreground">No courses yet. Create your first one.</p>}
      <form
        className="flex max-w-md gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (name.trim()) create.mutate({ body: { name } })
        }}
      >
        <Input placeholder="New course name" value={name} onChange={(e) => setName(e.target.value)} />
        <Button type="submit" disabled={!name.trim() || create.isPending}>
          Add course
        </Button>
      </form>
    </div>
  )
}
