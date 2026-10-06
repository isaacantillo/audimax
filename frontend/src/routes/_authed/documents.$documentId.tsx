import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'

import { deleteDocumentMutation, getDocumentOptions } from '@/client/@tanstack/react-query.gen'
import { Chat } from '@/components/chat'
import { ConfirmButton } from '@/components/confirm-button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

export const Route = createFileRoute('/_authed/documents/$documentId')({ component: DocumentView })

function DocumentView() {
  const { documentId } = Route.useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data: doc, isPending } = useQuery({
    ...getDocumentOptions({ path: { document_id: documentId } }),
    refetchInterval: (q) => (q.state.data && (q.state.data.status === 'queued' || q.state.data.status === 'processing') ? 3000 : false),
  })
  const remove = useMutation({
    ...deleteDocumentMutation(),
    onSuccess: async () => {
      const courseId = doc?.course.id
      await queryClient.invalidateQueries()
      if (courseId) await navigate({ to: '/courses/$courseId', params: { courseId }, search: { tab: 'documents' } })
    },
  })

  if (isPending) return <Skeleton className="h-64" />
  if (!doc) return <p className="text-destructive">Document not found.</p>

  return (
    <div className="space-y-4">
      <Link to="/courses/$courseId" params={{ courseId: doc.course.id }} search={{ tab: 'documents' }} className="text-sm text-muted-foreground hover:underline">
        ← {doc.course.name}
      </Link>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="flex flex-wrap items-center gap-2 text-2xl font-semibold">
          {doc.title}
          <Badge variant={doc.status === 'failed' ? 'destructive' : 'secondary'}>{doc.status}</Badge>
        </h1>
        <div className="flex items-center gap-3 text-sm">
          <a href={doc.file_url} target="_blank" rel="noreferrer" className="underline">Open PDF</a>
          <ConfirmButton label="Delete" question="Delete this document?" variant="destructive" onConfirm={() => remove.mutate({ path: { document_id: documentId } })} />
        </div>
      </div>
      {doc.lecture && (
        <p className="text-sm">
          Belongs to <Link to="/lectures/$lectureId" params={{ lectureId: doc.lecture.id }} className="underline">{doc.lecture.title}</Link>
        </p>
      )}
      {doc.status === 'failed' && <p className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm">{doc.error}</p>}
      <Tabs defaultValue="text">
        <TabsList>
          <TabsTrigger value="text">Text ({doc.page_count} pages)</TabsTrigger>
          <TabsTrigger value="chat">Chat</TabsTrigger>
        </TabsList>
        <TabsContent value="text" className="space-y-3">
          {doc.sections.map((s, i) => (
            <div key={i} className="rounded-md border p-3">
              <div className="mb-1 text-xs text-muted-foreground">Page {s.page}</div>
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{s.text}</p>
            </div>
          ))}
        </TabsContent>
        <TabsContent value="chat">
          <Chat courseId={doc.course.id} lectureIds={[]} documentIds={[doc.id]} scope={{ document_id: doc.id }} emptyHint="Ask about this document." />
        </TabsContent>
      </Tabs>
    </div>
  )
}
