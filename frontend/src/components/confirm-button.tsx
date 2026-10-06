import { useState } from 'react'

import { Button } from '@/components/ui/button'

/** Two-step button for destructive or costly actions (the viewer has no confirm() dialog). */
export function ConfirmButton({
  label,
  question,
  onConfirm,
  disabled,
  variant = 'outline',
}: {
  label: string
  question: string
  onConfirm: () => void
  disabled?: boolean
  variant?: 'outline' | 'destructive' | 'default'
}) {
  const [asking, setAsking] = useState(false)
  if (!asking) {
    return (
      <Button variant={variant} size="sm" disabled={disabled} onClick={() => setAsking(true)}>
        {label}
      </Button>
    )
  }
  return (
    <span className="inline-flex items-center gap-2 text-sm">
      {question}
      <Button
        variant={variant === 'default' ? 'default' : 'destructive'}
        size="sm"
        onClick={() => {
          setAsking(false)
          onConfirm()
        }}
      >
        Yes
      </Button>
      <Button variant="outline" size="sm" onClick={() => setAsking(false)}>
        Cancel
      </Button>
    </span>
  )
}
