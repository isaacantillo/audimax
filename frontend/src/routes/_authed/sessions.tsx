import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'

import { listSessionsOptions, revokeSessionMutation } from '@/client/@tanstack/react-query.gen'
import type { SessionOut } from '@/client/types.gen'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export const Route = createFileRoute('/_authed/sessions')({ component: Sessions })

function ago(iso: string | null | undefined) {
  if (!iso) return '—'
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 5) return 'active now'
  if (minutes < 60) return `${minutes} min ago`
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)} h ago`
  return new Date(iso).toLocaleDateString()
}

function Sessions() {
  const { user } = Route.useRouteContext()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { data: sessions, isPending } = useQuery({ ...listSessionsOptions(), refetchInterval: 60000 })
  const revoke = useMutation({
    ...revokeSessionMutation(),
    onSuccess: async (_, vars) => {
      if (sessions?.find((s) => s.id === vars.path.session_id)?.current) {
        queryClient.clear()
        await navigate({ to: '/login' })
        return
      }
      await queryClient.invalidateQueries({ queryKey: listSessionsOptions().queryKey })
    },
  })

  const label = (s: SessionOut) => (s.kind === 'api' ? `API token “${s.name ?? 'unnamed'}”` : s.device)

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Sessions</h1>
      <p className="text-sm text-muted-foreground">
        {user.is_admin ? 'Every signed-in device and API token, for all users.' : 'Where you are signed in, and your API tokens.'}{' '}
        Log out anything you do not recognise. Locations are approximate, from the IP address.
      </p>
      {isPending && <p className="text-muted-foreground">Loading…</p>}
      {sessions && sessions.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              {user.is_admin && <TableHead>User</TableHead>}
              <TableHead>Device</TableHead>
              <TableHead>Location</TableHead>
              <TableHead>Last active</TableHead>
              <TableHead>Signed in</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {sessions.map((s) => (
              <TableRow key={s.id}>
                {user.is_admin && <TableCell className="font-medium">{s.username}</TableCell>}
                <TableCell>
                  {label(s)} {s.current && <Badge variant="secondary">this device</Badge>}
                </TableCell>
                <TableCell>
                  {s.location ?? 'Unknown'}
                  {s.ip && <p className="text-xs text-muted-foreground">{s.ip}</p>}
                </TableCell>
                <TableCell className="text-muted-foreground">{s.last_seen_at ? ago(s.last_seen_at) : 'not used yet'}</TableCell>
                <TableCell className="text-muted-foreground">{new Date(s.created_at).toLocaleDateString()}</TableCell>
                <TableCell>
                  <Button size="sm" variant="outline" disabled={revoke.isPending} onClick={() => revoke.mutate({ path: { session_id: s.id } })}>
                    {s.kind === 'api' ? 'Revoke' : 'Log out'}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <p className="text-xs text-muted-foreground">
        <a href="https://db-ip.com" className="underline">
          IP Geolocation by DB-IP
        </a>
      </p>
    </div>
  )
}
