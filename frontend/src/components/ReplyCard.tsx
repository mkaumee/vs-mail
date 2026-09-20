import { useEffect, useState } from 'react'
import { api, type ReplyResponse } from '@/api'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import ReplyComposer from '@/components/ReplyComposer'

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
  onError,
}: {
  emailId: string
  version: string
  onError: (message: string) => void
}) {
  const [reply, setReply] = useState<ReplyResponse | null>(null)
  const [failed, setFailed] = useState<string | null>(null)

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
  }, [emailId, version])

  if (failed) {
    return (
      <Card>
        <CardContent className="py-5 text-sm text-defect">{failed}</CardContent>
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
      version={version}
      onError={onError}
    />
  )
}
