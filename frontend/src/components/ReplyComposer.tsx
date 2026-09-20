import { useEffect, useState } from 'react'
import { AlertTriangle, Check, Copy, FlaskConical, Mail, Send, Undo2 } from 'lucide-react'
import { api, type Draft, type Sent } from '@/api'
import type { Edit } from '@/useDrafts'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { relative } from '@/format'

const KIND_LABEL: Record<string, string> = {
  mismatch: 'Asks for the draft to be amended',
  confirm: 'Confirms the draft and releases it',
  missing_value: 'Asks for the blank values',
  missing_attachment: 'Asks for the missing attachment',
  unreadable: 'Asks for a readable copy',
  wrong_doc_type: 'Says the wrong document was attached',
  answer: 'Answers the question',
}

const FIELD =
  'w-full rounded-md border bg-background px-2 py-1.5 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50'

const TEST_KEY = 'vsmail.testRecipient'

/** Where test sends go, remembered per browser like the service token. */
export const getTestRecipient = (): string =>
  localStorage.getItem(TEST_KEY) || ''

/**
 * The reply, for a person to read, change and send.
 *
 * Rendered by both the deck and the list, because building an editor and a
 * Send button twice guarantees they drift — which is exactly how the card
 * once went on offering "amend the consignee" after a reviewer had corrected
 * it and the verdict had turned OK.
 *
 * The edit is the thing that goes out. What we composed is only a starting
 * point, and sending something other than what was approved would defeat the
 * approval.
 */
export default function ReplyComposer({
  emailId,
  draft,
  /**
   * The values on screen. Owned by the caller, not here: moving to the next
   * email and back remounts this component, and a reviewer who rewrote three
   * sentences would find them gone.
   */
  value,
  edited,
  onChange,
  onReset,
  onSent,
  sentAt,
  onError,
}: {
  emailId: string
  draft: Draft
  value: Edit
  edited: boolean
  onChange: (next: Edit) => void
  onReset: () => void
  /** Told after a real send, so the lane can drop this one into Read. */
  onSent?: () => void
  /** When this was already sent. Set, and Send is not offered again. */
  sentAt?: string | null
  onError: (message: string) => void
}) {
  const { to, subject, body } = value
  const [testTo, setTestTo] = useState(getTestRecipient)

  const [copied, setCopied] = useState(false)
  const [saving, setSaving] = useState(false)
  const [sending, setSending] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)
  const [sent, setSent] = useState<Sent | null>(null)

  // What happened to the *last* email must not be reported about this one.
  useEffect(() => {
    setCopied(false)
    setSaved(null)
    setSent(null)
  }, [emailId])

  const setTo = (v: string) => onChange({ ...value, to: v })
  const setSubject = (v: string) => onChange({ ...value, subject: v })
  const setBody = (v: string) => onChange({ ...value, body: v })

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(`To: ${to}\nSubject: ${subject}\n\n${body}`)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      onError('The browser would not allow copying to the clipboard.')
    }
  }

  const intoGmail = async () => {
    setSaving(true)
    try {
      const r = await api.replyIntoGmail(emailId)
      setSaved(r.threaded ? 'Draft created in the original thread.' : 'Draft created.')
    } catch (error) {
      onError((error as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const send = async () => {
    setSending(true)
    try {
      localStorage.setItem(TEST_KEY, testTo.trim())
      const r = await api.sendReply(emailId, {
        to,
        subject,
        body,
        test_recipient: testTo.trim(),
      })
      setSent(r)
      onSent?.()
    } catch (error) {
      onError((error as Error).message)
    } finally {
      setSending(false)
    }
  }

  return (
    <Card>
      <CardHeader className="gap-1">
        <CardTitle className="flex items-center gap-2 text-sm">
          Reply
          {edited && (
            <Badge variant="outline" className="font-normal">
              edited
            </Badge>
          )}
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          {KIND_LABEL[draft.kind] ?? 'Drafted for approval'}
        </p>
      </CardHeader>

      <CardContent className="space-y-3">
        {draft.fabricated && (
          <div className="flex items-start gap-2 rounded-md bg-review-bg px-3 py-2 text-xs text-review">
            <FlaskConical className="mt-0.5 size-3.5 shrink-0" />
            <span>
              Uses <b>demo records</b> — check the figures before sending.
            </span>
          </div>
        )}

        <div className="space-y-2">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-muted-foreground">To</span>
            <input className={FIELD} value={to} onChange={(e) => setTo(e.target.value)} />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-muted-foreground">
              Subject
            </span>
            <input
              className={FIELD}
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-muted-foreground">
              Message
            </span>
            <textarea
              className={`${FIELD} min-h-64 resize-y font-mono leading-relaxed`}
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
          </label>
        </div>

        {draft.missing && (
          <div className="flex items-start gap-2 rounded-md bg-uncertain-bg px-3 py-2 text-xs text-uncertain">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
            <span>Not covered by the material: {draft.missing}</span>
          </div>
        )}

        {draft.citations && draft.citations.length > 0 && (
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">Drawn from</div>
            <div className="flex flex-wrap gap-1.5">
              {draft.citations.map((c) => (
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

        {/* Already answered. Offering Send again would send the customer a
            second copy of the same correction. */}
        {!sentAt && (
        <div className="rounded-md border border-dashed p-3">
          <label className="block">
            <span className="mb-1 block text-xs font-medium">
              Send test emails to
            </span>
            <input
              className={FIELD}
              placeholder="you@example.com"
              value={testTo}
              onChange={(e) => setTestTo(e.target.value)}
            />
          </label>
          <p className="mt-1.5 text-xs text-muted-foreground">
            {testTo.trim() ? (
              <>Sends here instead of <b>{to}</b>.</>
            ) : (
              <>Required. Otherwise this would go to <b>{to}</b>.</>
            )}
          </p>
        </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          {!sentAt && (
            <Button
              size="sm"
              loading={sending}
              disabled={!testTo.trim() || !body.trim()}
              onClick={send}
            >
              <Send />
              Send
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={copy}>
            {copied ? <Check className="text-clean" /> : <Copy />}
            {copied ? 'Copied' : 'Copy'}
          </Button>
          <Button size="sm" variant="outline" loading={saving} onClick={intoGmail}>
            <Mail />
            Create Gmail draft
          </Button>
          {edited && (
            <Button size="sm" variant="ghost" onClick={onReset}>
              <Undo2 />
              Reset to drafted
            </Button>
          )}
        </div>

        {sentAt && (
          <p className="text-xs text-clean">Sent {relative(sentAt)}</p>
        )}
        {saved && <p className="text-xs text-clean">{saved}</p>}
        {sent && (
          <p className="text-xs text-clean">
            Sent to <b>{sent.sent_to}</b>
            {sent.diverted_from && <> instead of {sent.diverted_from}</>}
            {sent.threaded && <> · in the original thread</>}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
