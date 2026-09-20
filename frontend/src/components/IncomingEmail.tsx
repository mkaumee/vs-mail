import { useState } from 'react'
import { Paperclip } from 'lucide-react'
import type { IncomingEmail as Email } from '@/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const filename = (path: string) => path.split('/').pop() || path

/**
 * The email being replied to.
 *
 * Approving a reply without seeing what it answers is not really approving
 * it — you are agreeing to words about an email you have not read. The deck
 * used to show the subject, the sender and then jump straight to the draft.
 *
 * The trimmed body is the default because the security banner and the
 * corporate signature repeat across hundreds of these and bury the one
 * sentence that matters. The full text is a click away for when the trim
 * looks like it ate something.
 */
export default function IncomingEmail({ email }: { email: Email }) {
  const [full, setFull] = useState(false)
  const shown = full ? email.body : email.core_body
  const trimmed = email.body.length > email.core_body.length

  return (
    <Card>
      <CardHeader className="gap-1">
        <CardTitle className="text-sm">Email</CardTitle>
        <p className="text-sm text-muted-foreground">{email.sender}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap rounded-md border px-3 py-3 text-sm leading-relaxed">
          {shown || <span className="text-muted-foreground">(no body)</span>}
        </pre>

        {trimmed && (
          <Button size="sm" variant="ghost" onClick={() => setFull((v) => !v)}>
            {full ? 'Show the request only' : 'Show full email'}
          </Button>
        )}

        {email.attachments.length > 0 && (
          <div className="space-y-1">
            {email.attachments.map((path) => {
              const name = filename(path)
              // Which slot this file filled, and what was actually read out
              // of it — a reviewer checking a verdict wants both.
              const role = /_SI\./i.test(name)
                ? email.si_source
                : /_BL\./i.test(name)
                  ? email.bl_source
                  : null
              return (
                <div key={path} className="flex items-center gap-2 text-xs">
                  <Paperclip className="size-3.5 shrink-0 text-muted-foreground" />
                  <span className="font-medium">{name}</span>
                  {role && <span className="text-muted-foreground">{role}</span>}
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
