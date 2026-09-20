import { useEffect, useState } from 'react'
import { Check, Copy, Mail } from 'lucide-react'
import { api, type Draft } from '@/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const KIND_LABEL: Record<string, string> = {
  mismatch: 'Asks for the draft to be amended',
  confirm: 'Confirms the draft and releases it',
  missing_value: 'Asks for the blank values',
  missing_attachment: 'Asks for the missing attachment',
  unreadable: 'Asks for a readable copy',
  wrong_doc_type: 'Says the wrong document was attached',
}

/**
 * The reply, for a person to approve.
 *
 * What actually happens when a check finds something is an email — the
 * document is a *draft*, and the sender is waiting to be told what to fix.
 * That reply is formulaic and every value it needs is already on screen, so
 * making someone retype it is the waste this removes.
 *
 * It is never sent from here. Copy it, or put it in Gmail as a draft; the
 * send is always a person's.
 */
export default function ReplyCard({
  emailId,
  onError,
}: {
  emailId: string
  onError: (message: string) => void
}) {
  const [draft, setDraft] = useState<Draft | null>(null)
  const [copied, setCopied] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)

  useEffect(() => {
    setDraft(null)
    setCopied(false)
    setSaved(null)
    api
      .reply(emailId)
      .then((r) => setDraft(r.draft))
      .catch(() => setDraft(null))
  }, [emailId])

  if (!draft) return null

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(
        `To: ${draft.to}\nSubject: ${draft.subject}\n\n${draft.body}`,
      )
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

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Reply</CardTitle>
        <p className="text-sm text-muted-foreground">
          {KIND_LABEL[draft.kind] ?? 'Drafted for approval'}. Nothing is sent
          from here.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="rounded-md border">
          <div className="border-b px-3 py-2 text-xs text-muted-foreground">
            <div>
              <span className="font-medium text-foreground">To</span> {draft.to}
            </div>
            <div className="truncate">
              <span className="font-medium text-foreground">Subject</span>{' '}
              {draft.subject}
            </div>
          </div>
          <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap px-3 py-3 text-sm leading-relaxed">
            {draft.body}
          </pre>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" onClick={copy}>
            {copied ? <Check className="text-clean" /> : <Copy />}
            {copied ? 'Copied' : 'Copy'}
          </Button>
          <Button size="sm" variant="outline" loading={saving} onClick={intoGmail}>
            <Mail />
            Create Gmail draft
          </Button>
          {saved && <span className="text-xs text-clean">{saved}</span>}
        </div>
      </CardContent>
    </Card>
  )
}
