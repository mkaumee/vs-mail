import { useState } from 'react'
import { AlertTriangle, Check, Clock, Mail, Unlink } from 'lucide-react'
import { api, type GmailStatus } from '@/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

/**
 * Gmail has four states and they want different words.
 *
 * Collapsing them into connected/not-connected is what made this hard to
 * debug on the deployment: "not connected" was shown both when nothing had
 * been configured and when a pasted credential could not be parsed, and the
 * two need opposite actions. `credentials_source` tells them apart — it says
 * whether anything was found at all — and `expired` separates the seven-day
 * token running out, which is routine, from a setup that was never done.
 */
function describe(gmail: GmailStatus) {
  if (gmail.ready) {
    return {
      icon: Check,
      tone: 'text-clean',
      title: gmail.mailbox ?? 'Connected',
      detail: `Reading the whole mailbox, Spam included · token from ${gmail.token_source}`,
      action: null,
    }
  }
  if (gmail.expired) {
    return {
      icon: Clock,
      tone: 'text-review',
      title: 'Authorisation expired',
      // Worth saying plainly: gmail.modify is a restricted scope, so a consent
      // screen in Testing issues tokens that last seven days. Reconnecting is
      // the arrangement, not a fault to investigate.
      detail:
        'Consent screens in Testing issue tokens that last seven days, so this is expected. Reconnect to carry on.',
      action: 'Reconnect Gmail',
    }
  }
  if (!gmail.credentials_present && gmail.credentials_source) {
    return {
      icon: AlertTriangle,
      tone: 'text-defect',
      title: `The OAuth client in the ${gmail.credentials_source} cannot be read`,
      detail: gmail.error ?? 'It is set, but it is not valid JSON.',
      action: 'Try anyway',
    }
  }
  if (!gmail.credentials_present) {
    return {
      icon: Mail,
      tone: 'text-muted-foreground',
      title: 'Gmail is not set up',
      detail: 'No OAuth client found. Press connect for the setup steps.',
      action: 'Connect Gmail',
    }
  }
  return {
    icon: Mail,
    tone: 'text-muted-foreground',
    title: 'Not connected',
    detail: `OAuth client loaded from the ${gmail.credentials_source}. One consent screen to go.`,
    action: 'Connect Gmail',
  }
}

export default function GmailCard({
  gmail,
  onChanged,
  onError,
}: {
  gmail: GmailStatus
  onChanged: () => void
  onError: (message: string) => void
}) {
  const [going, setGoing] = useState(false)
  const [dropping, setDropping] = useState(false)
  const [dropped, setDropped] = useState<string | null>(null)
  const state = describe(gmail)
  const Icon = state.icon

  // Consent happens in the operator's own browser and comes back to this app,
  // which is what a web OAuth client means. There is no terminal step.
  const connect = async () => {
    setGoing(true)
    try {
      const { authorization_url } = await api.gmailAuthStart()
      window.location.href = authorization_url
    } catch (error) {
      onError((error as Error).message)
      setGoing(false)
    }
  }

  // Deleting our copy is not a disconnect — Google would still trust the
  // grant, so reconnecting would skip consent entirely. The server revokes.
  const disconnect = async () => {
    setDropping(true)
    try {
      const result = await api.disconnectGmail()
      setDropped(
        result.still_in_environment
          ? 'Revoked at Google, but VS_GMAIL_TOKEN_JSON still holds it — remove that variable.'
          : 'Disconnected and revoked at Google.',
      )
      onChanged()
    } catch (error) {
      onError((error as Error).message)
    } finally {
      setDropping(false)
    }
  }

  return (
    <Card className="gap-3 py-4">
      <CardContent className="flex items-start gap-3">
        <Icon className={`mt-0.5 size-4 shrink-0 ${state.tone}`} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{state.title}</div>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {state.detail}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {state.action && (
              <Button size="sm" variant="outline" loading={going} onClick={connect}>
                {state.action}
              </Button>
            )}
            {gmail.authorised && (
              <Button size="sm" variant="ghost" loading={dropping} onClick={disconnect}>
                <Unlink />
                Disconnect
              </Button>
            )}
          </div>
          {dropped && <p className="mt-2 text-xs text-muted-foreground">{dropped}</p>}
        </div>
      </CardContent>
    </Card>
  )
}
