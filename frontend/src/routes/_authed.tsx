import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, Outlet, createFileRoute, redirect, useNavigate } from '@tanstack/react-router'

import { getMeOptions, logoutMutation } from '@/client/@tanstack/react-query.gen'
import { Button } from '@/components/ui/button'

// Every screen except /login lives under this layout. A missing or expired session
// (401 from /api/auth/me) sends the user to the login page.
export const Route = createFileRoute('/_authed')({
  beforeLoad: async ({ context }) => {
    // retry: false: a 401 means "not signed in", not a glitch worth retrying (retries also stall in background tabs).
    try {
      return { user: await context.queryClient.ensureQueryData({ ...getMeOptions(), retry: false }) }
    } catch {
      throw redirect({ to: '/login' })
    }
  },
  component: AuthedLayout,
})

function AuthedLayout() {
  const { user } = Route.useRouteContext()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const logout = useMutation({
    ...logoutMutation(),
    onSuccess: async () => {
      queryClient.clear()
      await navigate({ to: '/login' })
    },
  })

  return (
    <>
      <header className="border-b">
        <nav className="mx-auto flex max-w-5xl items-center gap-6 px-4 py-3">
          <Link to="/" className="text-lg font-semibold">
            Audimax
          </Link>
          <Link to="/live" className="text-sm text-muted-foreground [&.active]:text-foreground">
            Live
          </Link>
          <Link to="/search" className="text-sm text-muted-foreground [&.active]:text-foreground">
            Search
          </Link>
          <Link to="/activity" className="text-sm text-muted-foreground [&.active]:text-foreground">
            Activity
          </Link>
          <Link to="/settings" className="text-sm text-muted-foreground [&.active]:text-foreground">
            Settings
          </Link>
          <Link to="/sessions" className="text-sm text-muted-foreground [&.active]:text-foreground">
            Sessions
          </Link>
          <div className="ml-auto flex items-center gap-3 text-sm text-muted-foreground">
            {user.username}
            <Button variant="outline" size="sm" onClick={() => logout.mutate({})} disabled={logout.isPending}>
              Log out
            </Button>
          </div>
        </nav>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-6">
        <Outlet />
      </main>
    </>
  )
}
