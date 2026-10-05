import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/_authed/activity')({ component: Activity })

function Activity() {
  return (
    <div className="space-y-2">
      <h1 className="text-2xl font-semibold">Activity</h1>
      <p className="text-muted-foreground">Jobs appear here once the worker exists.</p>
    </div>
  )
}
