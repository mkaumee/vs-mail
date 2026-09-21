import { useEffect, useState } from 'react'
import { api, type ReplyResponse } from '@/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import ReplyComposer from '@/components/ReplyComposer'
import { useDrafts } from '@/useDrafts'

/**
 * The reply in list view.
 *
 * Fetches; the composer does the rest, so the two views cannot drift apart.
 *
 * `version` is anything about the verdict that would change the reply. Keying
 * only on the email id was a bug with teeth: a reviewer corrected both fields,
 * the verdict became OK, and the card went on offering the reply that asks the
 * customer to amend them. That draft is one click from being sent.
 */
export default function ReplyCard({
  emailId,
  version,
  sentAt,
  onError,
}: {
  emailId: string
  version: string
  sentAt?: string | null
  onError: (message: string) => void
}) {
  const drafts = useDrafts()
  const [reply, setReply] = useState<ReplyResponse | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let live = true
    setReply(null)
    setFailed(null)
    api
      .reply(emailId)
      .then((r) => live && setReply(r))
      .catch((e: Error) => live && setFailed(e.message))
    return () => {
      live = false
    }
  }, [attempt, emailId, version])

  if (failed) {
    return (
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 py-5 text-sm text-defect">
          <span>{failed}</span>
          <Button size="sm" variant="outline" onClick={() => setAttempt((value) => value + 1)}>
            Try again
          </Button>
        </CardContent>
      </Card>
    )
  }

  if (!reply) return <Skeleton className="h-40 w-full" />

  // No draft is an outcome, not nothing. Returning null here meant the
  // explanation the API already sends was thrown away and the card just
  // vanished, which reads as a broken page rather than a decision.
  if (!reply.draft) {
    return (
      <Card>
        <CardContent className="py-5 text-sm text-muted-foreground">
          No reply drafted — {reply.why}
        </CardContent>
      </Card>
    )
  }

  return (
    <ReplyComposer
      emailId={emailId}
      draft={reply.draft}
      sentAt={sentAt}
      value={drafts.valueFor(emailId, reply.draft, version)}
      edited={drafts.isEdited(emailId, reply.draft, version)}
      onChange={(next) => drafts.change(emailId, version, next)}
      onReset={() => drafts.reset(emailId)}
      onError={onError}
    />
  )
}
