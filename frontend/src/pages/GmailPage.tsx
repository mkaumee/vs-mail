import { useState } from 'react'
import { motion } from 'motion/react'
import {
  CheckCircle2, KeyRound, LogIn, Plug, ShieldAlert, ShieldCheck,
  TriangleAlert, Unplug, UserRound, XCircle,
} from 'lucide-react'
import { api, type GmailStatus, type Me } from '@/api'
import { Button } from '@/components/ui/button'
import { getTestRecipient } from '@/components/ReplyComposer'

/**
 * Four states, four sets of words.
 *
 * `credentials_source` is what separates "nothing was ever set" from
 * "something was set and cannot be used" — without it a mangled paste and an
 * empty variable look identical, and there is no way to tell which value to
 * go and look at. `expired` separates the seven-day token running out, which
 * is routine, from a setup that was never done.
 */
function describe(g: GmailStatus) {
  if (g.ready)
    return { title: 'Gmail connected', tone: 'ok', Icon: Plug, active: true }
  if (g.expired)
    return { title: 'Authorisation expired', tone: 'warn', Icon: TriangleAlert, active: false }
  if (!g.credentials_present && g.credentials_source)
    return { title: 'Cannot read the OAuth client', tone: 'bad', Icon: ShieldAlert, active: false }
  if (!g.credentials_present)
    return { title: 'Gmail is not set up', tone: '', Icon: Unplug, active: false }
  return { title: 'Not connected', tone: '', Icon: Unplug, active: false }
}

export default function GmailPage({
  gmail,
  me,
  onChanged,
  onError,
}: {
  gmail: GmailStatus | null
  me: Me | null
  onChanged: () => void
  onError: (message: string) => void
}) {
  const [going, setGoing] = useState(false)
  const [dropping, setDropping] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const testTo = getTestRecipient()

  if (!gmail) return <div className="skeleton h-48 w-full" />

  const state = describe(gmail)
  const { Icon } = state

  const connect = async () => {
    setGoing(true)
    try {
      const { authorization_url } = await api.gmailAuthStart()
      window.location.href = authorization_url
    } catch (e) {
      onError((e as Error).message)
      setGoing(false)
    }
  }

  const disconnect = async () => {
    setDropping(true)
    try {
      const r = await api.disconnectGmail()
      setNote(
        r.still_in_environment
          ? 'Revoked at Google. VS_GMAIL_TOKEN_JSON still holds a now-dead token — remove that variable.'
          : 'Disconnected and revoked at Google.',
      )
      setConfirm(false)
      onChanged()
    } catch (e) {
      onError((e as Error).message)
    } finally {
      setDropping(false)
    }
  }

  return (
    <motion.div
      className="gmail-grid"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, ease: [0.2, 0.8, 0.2, 1] }}
    >
      <section className={`panel glass-2 gcard gcard--${state.tone}`}>
        <div className="gcard__top">
          <span className="gcard__icon" aria-hidden>
            <Icon className="size-[22px]" />
          </span>
          <div>
            <h2 className="h2">{state.title}</h2>
            {state.active && (
              <p className="muted small">
                <span className="dot dot--ok" aria-hidden />
                Active
              </p>
            )}
          </div>
        </div>

        {gmail.ready ? (
          <>
            <dl className="kv">
              <div>
                <dt>Mailbox</dt>
                <dd className="mono">{gmail.mailbox}</dd>
              </div>
              <div>
                <dt>Reads</dt>
                <dd>The whole mailbox, Spam included</dd>
              </div>
              <div>
                <dt>Token held in</dt>
                <dd>
                  {gmail.token_source === 'environment'
                    ? 'An environment variable'
                    : 'A file on the server'}
                </dd>
              </div>
            </dl>
            <div className="gcard__actions">
              {!confirm ? (
                <Button variant="outline" onClick={() => setConfirm(true)}>
                  <Unplug />
                  Disconnect
                </Button>
              ) : (
                <>
                  <Button variant="destructive" loading={dropping} onClick={disconnect}>
                    Disconnect and revoke
                  </Button>
                  <Button variant="ghost" onClick={() => setConfirm(false)}>
                    Cancel
                  </Button>
                </>
              )}
            </div>
            {confirm && (
              <p className="muted small">
                Revokes the grant at Google, so reconnecting asks for consent again.
                Results and drafts already produced are kept.
              </p>
            )}
          </>
        ) : (
          <>
            <p className="gcard__text">
              {gmail.expired
                ? 'Consent screens in Testing issue tokens that last seven days, so this is expected. Reconnect to carry on.'
                : gmail.error
                  ? gmail.error.split('\n')[0]
                  : 'Connect a mailbox to read and process real mail. Nothing leaves it without you pressing Send.'}
            </p>
            <div className="gcard__actions">
              <Button loading={going} onClick={connect}>
                <LogIn />
                {gmail.expired ? 'Reconnect Gmail' : 'Connect Gmail'}
              </Button>
            </div>
          </>
        )}

        {note && <p className="muted small">{note}</p>}
      </section>

      <section className="panel glass-3">
        <h2 className="h3">Application sign-in</h2>
        <div className="signin">
          <span className="signin__avatar" aria-hidden>
            <UserRound className="size-[18px]" />
          </span>
          <div>
            <strong>
              {me ? `Signed in as ${me.name || me.email}` : 'Signed in with a service token'}
            </strong>
            <span className="muted small">{me?.email ?? 'No Google account attached'}</span>
          </div>
        </div>
        <p className="muted small">
          This is your VS-Mail account. You can be signed in with no Gmail connected —
          connecting a mailbox is a separate step with its own permissions, and the
          mailbox belongs to the deployment rather than to you.
        </p>
      </section>

      <section className="panel glass-3">
        <h2 className="h3">Permissions and safety</h2>
        <ul className="checks">
          <li><CheckCircle2 className="size-[15px]" /> Read mail, including Spam</li>
          <li><CheckCircle2 className="size-[15px]" /> Create drafts in the original thread</li>
          <li><CheckCircle2 className="size-[15px]" /> Send, but only when you press Send</li>
          <li className="is-no"><XCircle className="size-[15px]" /> Delete mail: not requested</li>
          <li><KeyRound className="size-[15px]" /> Tokens stay on the server and are never shown here</li>
          <li className={testTo ? '' : 'is-off'}>
            {testTo ? <ShieldCheck className="size-[15px]" /> : <TriangleAlert className="size-[15px]" />}
            {testTo
              ? `Test recipient set (${testTo}) — every send is diverted there`
              : 'No test recipient set. Sending is refused until there is one'}
          </li>
        </ul>
      </section>
    </motion.div>
  )
}
