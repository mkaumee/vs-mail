import { useCallback, useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { api, type Result } from './api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import Fields from '@/components/Fields'
import IncomingEmail from '@/components/IncomingEmail'
import ReplyComposer from '@/components/ReplyComposer'
import { useDeck } from './useDeck'
import { useDrafts } from './useDrafts'
import { REVIEW_REASONS, TONE_CLASS, statusTone } from './format'

const fetchReply = (id: string) => api.reply(id)
const fetchEmail = (id: string) => api.incoming(id)

/** Everything about a verdict that should invalidate an edited reply. */
const versionOf = (row: Result) =>
  `${row.status}:${row.defect_fields.join(',')}:${row.provenance.length}`

/**
 * One email at a time, with what it says, what the check found, and the
 * reply — in that order.
 *
 * A list is right for scanning and wrong for working: the job is to read one
 * email, approve or fix its reply, and move on. The deck makes that the shape
 * of the screen, and lets the next one be ready before it is asked for.
 */
export default function Deck({ lane, rows }: { lane: string; rows: Result[] }) {
  const order = rows.map((r) => r.email_id)
  const { index, go, retry, retryEmail, current, entry, email, total } = useDeck(
    lane,
    order,
    fetchReply,
    fetchEmail,
  )
  const [error, setError] = useState<string | null>(null)
  // Above the composer, so an edit survives moving away and back.
  const drafts = useDrafts()

  const onKey = useCallback(
    (e: KeyboardEvent) => {
      // Not while someone is typing in the reply.
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if (e.key === 'ArrowRight') go(1)
      if (e.key === 'ArrowLeft') go(-1)
    },
    [go],
  )

  useEffect(() => {
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onKey])

  useEffect(() => setError(null), [current])

  if (!total) {
    return <p className="p-8 text-sm text-muted-foreground">Nothing in this lane.</p>
  }

  const row = rows[index]
  if (!row) return null
  const tone = statusTone(row)
  const summary =
    row.status === 'MISMATCH'
      ? row.defect_fields.join(', ')
      : row.status === 'NEEDS_REVIEW'
        ? REVIEW_REASONS[row.review_reason ?? ''] || 'Needs a person'
        : 'checked'

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-3 border-b px-5 py-2">
        <Button size="icon-sm" variant="outline" disabled={index === 0} onClick={() => go(-1)}>
          <ChevronLeft />
        </Button>
        <span className="text-sm tabular-nums text-muted-foreground">
          {index + 1} of {total}
        </span>
        <Button
          size="icon-sm"
          variant="outline"
          disabled={index >= total - 1}
          onClick={() => go(1)}
        >
          <ChevronRight />
        </Button>
        <span className="text-xs text-muted-foreground">← → to move</span>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
        <div>
          <h2 className="text-lg font-semibold">{row.subject || '(no subject)'}</h2>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <span>{row.sender || 'unknown sender'}</span>
            <span>·</span>
            <span>{current}</span>
            <Badge className={TONE_CLASS[tone]}>{summary}</Badge>
          </div>
        </div>

        {error && (
          <Card>
            <CardContent className="py-4 text-sm text-defect">{error}</CardContent>
          </Card>
        )}

        {/* What was asked. It is a file read rather than a model call, so it
            lands well before the reply and there is something to read while
            the draft is still being written. */}
        {!email && <Skeleton className="h-32 w-full" />}
        {email?.state === 'ready' && <IncomingEmail email={email.value} />}
        {email?.state === 'error' && (
          <Card>
            <CardContent className="flex flex-wrap items-center gap-3 py-5">
              <span className="text-sm text-defect">{email.message}</span>
              <Button size="sm" variant="outline" onClick={() => retryEmail(current)}>
                Try again
              </Button>
            </CardContent>
          </Card>
        )}

        {/* What the check found. The reply asserts a discrepancy; this is the
            evidence for it, and without it the assertion is unverifiable. */}
        <Fields fields={row.fields} />

        {!entry && <Skeleton className="h-40 w-full" />}

        {entry?.state === 'pending' && (
          <Card>
            <CardContent className="flex items-center gap-3 py-6 text-sm text-muted-foreground">
              <Spinner />
              Drafting the reply…
            </CardContent>
          </Card>
        )}

        {entry?.state === 'error' && (
          <Card>
            <CardContent className="flex flex-wrap items-center gap-3 py-5">
              <span className="text-sm text-defect">{entry.message}</span>
              <Button size="sm" variant="outline" onClick={() => retry(current)}>
                Try again
              </Button>
            </CardContent>
          </Card>
        )}

        {entry?.state === 'ready' && !entry.value.draft && (
          <Card>
            <CardContent className="py-5 text-sm text-muted-foreground">
              No reply drafted — {entry.value.why}
            </CardContent>
          </Card>
        )}

        {entry?.state === 'ready' && entry.value.draft && (
          <ReplyComposer
            emailId={current}
            draft={entry.value.draft}
            value={drafts.valueFor(current, entry.value.draft, versionOf(row))}
            edited={drafts.isEdited(current, entry.value.draft, versionOf(row))}
            onChange={(next) => drafts.change(current, versionOf(row), next)}
            onReset={() => drafts.reset(current)}
            onError={setError}
          />
        )}
      </div>
    </div>
  )
}
