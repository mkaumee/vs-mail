import { useCallback, useEffect } from 'react'
import { AlertTriangle, ChevronLeft, ChevronRight, FlaskConical } from 'lucide-react'
import { api, type Result } from './api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { useDeck } from './useDeck'
import { REVIEW_REASONS, TONE_CLASS, statusTone } from './format'

const KIND_LABEL: Record<string, string> = {
  mismatch: 'Asks for the draft to be amended',
  confirm: 'Confirms the draft and releases it',
  missing_value: 'Asks for the blank values',
  missing_attachment: 'Asks for the missing attachment',
  unreadable: 'Asks for a readable copy',
  wrong_doc_type: 'Says the wrong document was attached',
  answer: 'Answers the question',
}

const fetchReply = (id: string) => api.reply(id)

/**
 * One email at a time, with its drafted reply underneath.
 *
 * A list is right for scanning and wrong for working: the job is to read one
 * email, approve or fix its reply, and move on. The deck makes that the
 * shape of the screen, and lets the reply for the next one be ready before
 * it is asked for.
 */
export default function Deck({
  lane,
  rows,
}: {
  lane: string
  rows: Result[]
}) {
  const order = rows.map((r) => r.email_id)
  const { index, go, retry, current, entry, total } = useDeck(lane, order, fetchReply)

  const onKey = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') go(1)
      if (e.key === 'ArrowLeft') go(-1)
    },
    [go],
  )

  useEffect(() => {
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onKey])

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

        {entry?.state === 'ready' && !entry.reply.draft && (
          <Card>
            <CardContent className="py-5 text-sm text-muted-foreground">
              No reply drafted — {entry.reply.why}
            </CardContent>
          </Card>
        )}

        {entry?.state === 'ready' && entry.reply.draft && (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Reply</CardTitle>
              <p className="text-sm text-muted-foreground">
                {KIND_LABEL[entry.reply.draft.kind] ?? 'Drafted for approval'}. Nothing
                is sent from here.
              </p>
            </CardHeader>
            <CardContent className="space-y-3">
              {entry.reply.draft.fabricated && (
                <div className="flex items-start gap-2 rounded-md bg-review-bg px-3 py-2 text-xs text-review">
                  <FlaskConical className="mt-0.5 size-3.5 shrink-0" />
                  <span>
                    This answer uses <b>demo records</b>. The invoice and booking
                    numbers are real, the amounts and statuses were generated for
                    this project — check them before sending.
                  </span>
                </div>
              )}

              <div className="rounded-md border">
                <div className="border-b px-3 py-2 text-xs text-muted-foreground">
                  <div>
                    <span className="font-medium text-foreground">To</span>{' '}
                    {entry.reply.draft.to}
                  </div>
                  <div className="truncate">
                    <span className="font-medium text-foreground">Subject</span>{' '}
                    {entry.reply.draft.subject}
                  </div>
                </div>
                <pre className="whitespace-pre-wrap px-3 py-3 text-sm leading-relaxed">
                  {entry.reply.draft.body}
                </pre>
              </div>

              {entry.reply.draft.missing && (
                <div className="flex items-start gap-2 rounded-md bg-uncertain-bg px-3 py-2 text-xs text-uncertain">
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                  <span>Not covered by the material: {entry.reply.draft.missing}</span>
                </div>
              )}

              {entry.reply.draft.citations && entry.reply.draft.citations.length > 0 && (
                <div>
                  <div className="mb-1 text-xs font-medium text-muted-foreground">
                    Drawn from
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {entry.reply.draft.citations.map((c) => (
                      <Badge
                        key={c.id}
                        variant="outline"
                        className={c.fabricated ? 'border-review/40 text-review' : ''}
                        title={`${c.source} — ${c.heading}`}
                      >
                        {c.heading}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
