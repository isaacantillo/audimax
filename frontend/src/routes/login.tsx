import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, redirect, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { getMeOptions, loginMutation } from '@/client/@tanstack/react-query.gen'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

export const Route = createFileRoute('/login')({
  // Already signed in: skip the form.
  beforeLoad: async ({ context }) => {
    const user = await context.queryClient.fetchQuery({ ...getMeOptions(), staleTime: 0 }).catch(() => null)
    if (user) throw redirect({ to: '/' })
  },
  component: Login,
})

function Login() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  const login = useMutation({
    ...loginMutation(),
    onSuccess: async (user) => {
      queryClient.setQueryData(getMeOptions().queryKey, user)
      await navigate({ to: '/' })
    },
  })

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl">Audimax</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault()
              login.mutate({ body: { username, password } })
            }}
          >
            <Input
              placeholder="Username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
            />
            <Input
              type="password"
              placeholder="Password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {login.isError && <p className="text-sm text-destructive">Wrong username or password.</p>}
            <Button type="submit" className="w-full" disabled={login.isPending || !username || !password}>
              Log in
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
