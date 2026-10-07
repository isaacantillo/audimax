import { useQuery } from '@tanstack/react-query'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { listCoursesOptions, searchOptions } from '@/client/@tanstack/react-query.gen'
import type { SearchHit } from '@/client/types.gen'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { fmt } from '@/lib/format'

export const Route = createFileRoute('/_authed/search')({
  validateSearch: (s: Record<string, unknown>): { q?: string; course?: string } => ({
    q: typeof s.q === 'string' && s.q ? s.q : undefined,
    course: typeof s.course === 'string' && s.course ? s.course : undefined,
  }),
  component: SearchPage,
})

/** Wrap every case-insensitive occurrence of `query` in <mark>. */
function Highlight({ text, query }: { text: string; query: string }) {
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'))
  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === query.toLowerCase() ? (
          <mark key={i} className="rounded bg-yellow-200 px-0.5 text-foreground dark:bg-yellow-700">
            {part}
          </mark>
        ) : (
          part
        ),
      )}
    </>
  )
}

function SearchPage() {
  const { q, course } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const [draft, setDraft] = useState(q ?? '')
  const courses = useQuery(listCoursesOptions())
  const results = useQuery({
    ...searchOptions({ query: { q: q ?? '', course_id: course } }),
    enabled: !!q && q.length >= 2,
  })

  // Group the hits by lecture, keeping the order the API returned (lecture by lecture, in time order).
  const groups = new Map<string, { title: string; hits: SearchHit[] }>()
  for (const hit of results.data?.hits ?? []) {
    const group = groups.get(hit.lecture_id) ?? { title: hit.lecture_title, hits: [] }
    group.hits.push(hit)
    groups.set(hit.lecture_id, group)
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Search</h1>
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          void navigate({ search: (prev) => ({ ...prev, q: draft.trim() || undefined }) })
        }}
      >
        <Input className="min-w-60 flex-1" autoFocus placeholder="A word or phrase, German or English…" value={draft} onChange={(e) => setDraft(e.target.value)} />
        {courses.data && courses.data.length > 1 && (
          <select
            className="h-9 rounded-md border bg-background px-3 text-sm"
            value={course ?? ''}
            onChange={(e) => void navigate({ search: (prev) => ({ ...prev, course: e.target.value || undefined }) })}
          >
            <option value="">All courses</option>
            {courses.data.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        )}
        <Button type="submit" disabled={draft.trim().length < 2}>
          Search
        </Button>
      </form>
      <p className="text-xs text-muted-foreground">Searches the German transcripts, their translations and the English versions. Matches parts of words too.</p>

      {results.isFetching && <p className="text-muted-foreground">Searching…</p>}
      {results.data && results.data.hits.length === 0 && <p className="text-muted-foreground">No matches for “{results.data.query}”.</p>}
      {results.data?.truncated && <p className="text-sm text-muted-foreground">Showing the first matches only. Be more specific to narrow it down.</p>}

      <div className="space-y-6">
        {[...groups.entries()].map(([lectureId, group]) => (
          <section key={lectureId} className="space-y-2">
            <h2 className="font-semibold">
              <Link to="/lectures/$lectureId" params={{ lectureId }} className="hover:underline">
                {group.title}
              </Link>
            </h2>
            {group.hits.map((hit, i) => (
              <Link
                key={i}
                to="/lectures/$lectureId"
                params={{ lectureId }}
                search={hit.kind === 'transcript' ? { t: hit.start } : { mode: 'english', t: hit.start, p: hit.paragraph_id ?? undefined }}
                className="block rounded-md border p-3 transition hover:bg-accent"
              >
                <div className="mb-1 text-xs text-muted-foreground">
                  {hit.kind === 'transcript' ? `Original · ${fmt(hit.start)}` : `English version · from ${fmt(hit.start)} in the original`}
                </div>
                <p>{q && <Highlight text={hit.text} query={q} />}</p>
                {hit.text_translated && <p className="text-muted-foreground">{q && <Highlight text={hit.text_translated} query={q} />}</p>}
              </Link>
            ))}
          </section>
        ))}
      </div>
    </div>
  )
}
