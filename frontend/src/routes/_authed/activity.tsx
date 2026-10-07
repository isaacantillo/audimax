import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'

import { listJobsOptions, retryJobMutation } from '@/client/@tanstack/react-query.gen'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export const Route = createFileRoute('/_authed/activity')({ component: Activity })

const TASK_LABEL: Record<string, string> = {
  transcribe_lecture: 'Transcribe',
  translate_lecture: 'Translate',
  summarize_lecture: 'Summarise',
  english_plan: 'English: plan topics',
  english_write: 'English: write and check',
}

function Activity() {
  const queryClient = useQueryClient()
  const { data: jobs, isPending } = useQuery({
    ...listJobsOptions({ query: { limit: 100 } }),
    // Keep watching while anything is queued or running.
    refetchInterval: (q) => (q.state.data?.some((j) => j.status === 'todo' || j.status === 'doing') ? 2500 : 10000),
  })
  const retry = useMutation({ ...retryJobMutation(), onSuccess: () => void queryClient.invalidateQueries() })

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Activity</h1>
      {isPending && <p className="text-muted-foreground">Loading…</p>}
      {jobs?.length === 0 && <p className="text-muted-foreground">Nothing has run yet. Upload a lecture to get started.</p>}
      {jobs && jobs.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Step</TableHead>
              <TableHead>For</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>When</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {jobs.map((j) => (
              <TableRow key={j.id}>
                <TableCell>{TASK_LABEL[j.task] ?? j.task}</TableCell>
                <TableCell>
                  {j.lecture_id ? (
                    <Link to="/lectures/$lectureId" params={{ lectureId: j.lecture_id }} className="underline">{j.lecture_title}</Link>
                  ) : '—'}
                  {j.lecture_id && !j.lecture_title && <span className="text-muted-foreground">(deleted)</span>}
                </TableCell>
                <TableCell className="max-w-md">
                  <Badge variant={j.status === 'failed' ? 'destructive' : j.status === 'succeeded' ? 'secondary' : 'default'} className={j.status === 'doing' ? 'animate-pulse' : ''}>
                    {j.status === 'todo' ? 'queued' : j.status === 'doing' ? 'running' : j.status}
                  </Badge>
                  {j.error && <p className="mt-1 text-xs text-destructive">{j.error}</p>}
                </TableCell>
                <TableCell className="text-muted-foreground">{new Date(j.scheduled_at).toLocaleString()}</TableCell>
                <TableCell>
                  {j.status === 'failed' && j.lecture_title && (
                    <Button size="sm" variant="outline" disabled={retry.isPending} onClick={() => retry.mutate({ path: { job_id: j.id } })}>
                      Retry
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
