/** Multipart uploads go through plain fetch: the generated client is for JSON. */
async function post<T>(path: string, form: FormData): Promise<T> {
  const response = await fetch(path, { method: 'POST', body: form, credentials: 'include' })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = body?.detail
    throw new Error(typeof detail === 'string' ? detail : `Upload failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export function uploadLecture(args: { courseId: string; title: string; files: File[] }) {
  const form = new FormData()
  form.set('course_id', args.courseId)
  form.set('title', args.title)
  args.files.forEach((f) => form.append('files', f))
  return post<{ id: string; title: string }>('/api/lectures', form)
}
