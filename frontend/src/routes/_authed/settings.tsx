import { useMutation } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'

import { createApiTokenMutation } from '@/client/@tanstack/react-query.gen'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export const Route = createFileRoute('/_authed/settings')({ component: Settings })

function Settings() {
  const [name, setName] = useState('iPhone Shortcut')
  const create = useMutation(createApiTokenMutation())

  return (
    <div className="max-w-xl space-y-4">
      <h1 className="text-2xl font-semibold">Settings</h1>
      <section className="space-y-3 rounded-md border p-4">
        <h2 className="font-semibold">API token</h2>
        <p className="text-sm text-muted-foreground">
          For the phone Shortcut that uploads recordings: send it as <code>Authorization: Bearer &lt;token&gt;</code> to <code>POST /api/lectures</code>.
          The token is shown once; only a hash is stored.
        </p>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            create.mutate({ body: { name } })
          }}
        >
          <Input value={name} onChange={(e) => setName(e.target.value)} />
          <Button type="submit" disabled={!name.trim() || create.isPending}>
            Create token
          </Button>
        </form>
        {create.data && (
          <div className="space-y-1">
            <p className="text-sm font-medium">Copy it now, it will not be shown again:</p>
            <code className="block break-all rounded bg-muted p-2 text-sm">{create.data.token}</code>
          </div>
        )}
      </section>
    </div>
  )
}
