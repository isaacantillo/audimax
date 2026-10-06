import type { LectureStatus } from '@/client/types.gen'
import { Badge } from '@/components/ui/badge'
import { STATUS_LABEL, isBusy } from '@/lib/format'

export function StatusBadge({ status }: { status: LectureStatus }) {
  if (status === 'failed') return <Badge variant="destructive">{STATUS_LABEL[status]}</Badge>
  if (isBusy(status)) return <Badge className="animate-pulse">{STATUS_LABEL[status]}</Badge>
  return <Badge variant="secondary">{STATUS_LABEL[status]}</Badge>
}
