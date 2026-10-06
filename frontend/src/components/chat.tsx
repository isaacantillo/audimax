import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'

import { chatMutation, historyOptions } from '@/client/@tanstack/react-query.gen'
import type { ChatMessage, ChatSource } from '@/client/types.gen'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { fmt } from '@/lib/format'

function SourceLink({ source, index }: { source: ChatSource; index: number }) {
  const label = (
    <>
      <span className="font-mono text-xs">[{index}]</span> {source.title}
      {source.kind === 'transcript' && source.start != null && ` · ${fmt(source.start)}`}
      {source.kind === 'slides' && source.page != null && ` · p. ${source.page}`}
      {source.kind === 'english' && ' · English'}
    </>
  )
  const cls = 'rounded-md border px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground'
  if (source.kind === 'transcript' && source.lecture_id)
    return (
      <Link to="/lectures/$lectureId" params={{ lectureId: source.lecture_id }} search={{ t: source.start ?? undefined }} className={cls} title={source.snippet}>
        {label}
      </Link>
    )
  if (source.kind === 'english' && source.lecture_id)
    return (
      <Link to="/lectures/$lectureId" params={{ lectureId: source.lecture_id }} search={{ mode: 'english' }} className={cls} title={source.snippet}>
        {label}
      </Link>
    )
  if (source.kind === 'slides' && source.document_id)
    return (
      <Link to="/documents/$documentId" params={{ documentId: source.document_id }} className={cls} title={source.snippet}>
        {label}
      </Link>
    )
  return (
    <a href={source.url ?? '#'} target="_blank" rel="noreferrer" className={cls} title={source.snippet}>
      {label}
    </a>
  )
}

function errorDetail(error: unknown): string | null {
  const detail = (error as { detail?: unknown } | null)?.detail
  return typeof detail === 'string' ? detail : null
}

export function Chat({
  courseId,
  lectureIds,
  documentIds,
  web = false,
  scope,
  emptyHint,
}: {
  courseId: string
  lectureIds: string[]
  documentIds: string[]
  web?: boolean
  /** Which saved conversation this screen shows: a lecture's own, a document's own, or the course's. */
  scope?: { lecture_id?: string; document_id?: string }
  emptyHint?: string
}) {
  const history = useQuery(historyOptions({ query: { course_id: courseId, ...scope } }))
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [threadId, setThreadId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const loaded = useRef(false)
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (history.data && !loaded.current) {
      loaded.current = true
      setMessages(history.data.messages)
      setThreadId(history.data.thread_id ?? null)
    }
  }, [history.data])

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [messages.length])

  const send = useMutation({
    ...chatMutation(),
    onSuccess: (response) => {
      setThreadId(response.thread_id)
      setMessages((m) => [...m, response.message])
    },
  })

  const nothingSelected = lectureIds.length === 0 && documentIds.length === 0

  function submit(e: React.FormEvent) {
    e.preventDefault()
    const message = draft.trim()
    if (!message || send.isPending) return
    setMessages((m) => [...m, { role: 'user', content: message, sources: [] }])
    setDraft('')
    send.mutate({ body: { message, course_id: courseId, lecture_ids: lectureIds, document_ids: documentIds, thread_id: threadId, web } })
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="max-h-[28rem] min-h-40 space-y-4 overflow-y-auto rounded-md border p-3">
        {messages.length === 0 && (
          <p className="text-sm text-muted-foreground">{emptyHint ?? 'Ask anything about the selected material. Answers cite their sources.'}</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'ml-auto max-w-[85%] rounded-lg bg-primary px-3 py-2 text-primary-foreground' : 'max-w-[95%]'}>
            <p className="whitespace-pre-wrap leading-relaxed">{m.content}</p>
            {m.sources.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {m.sources.map((s, n) => (
                  <SourceLink key={n} source={s} index={n + 1} />
                ))}
              </div>
            )}
          </div>
        ))}
        {send.isPending && <p className="text-sm text-muted-foreground animate-pulse">Thinking…</p>}
        {send.isError && <p className="text-sm text-destructive">{errorDetail(send.error) ?? 'Something went wrong. Try again.'}</p>}
        <div ref={bottom} />
      </div>
      {nothingSelected && <p className="text-sm text-muted-foreground">Select at least one lecture or document to ask about.</p>}
      <form onSubmit={submit} className="flex gap-2">
        <Input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Ask a question…" disabled={nothingSelected} />
        <Button type="submit" disabled={nothingSelected || send.isPending || !draft.trim()}>
          Send
        </Button>
      </form>
    </div>
  )
}
