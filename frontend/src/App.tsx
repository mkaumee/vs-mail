import { useCallback, useEffect, useMemo, useState } from 'react'
import { LogOut } from 'lucide-react'
import Controls from './Controls'
import Deck from './Deck'
import Detail from './Detail'
import GmailCard from '@/components/GmailCard'
import SignIn from '@/components/SignIn'
import {
  api,
  clearToken,
  getToken,
  whenRejected,
  type Case,
  type GmailStatus,
  type Inbox,
  type Me,
  type Result,
} from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { SkeletonRows } from '@/components/ui/skeleton'
import { CATEGORY_LABELS, REVIEW_REASONS, TONE_CLASS, relative, statusTone } from './format'

// The OAuth callback cannot return JSON — a person's browser lands on it —
// so it says how it went in the URL and the app reports it here.
const SIGNIN_OUTCOMES: Record<string, [string, string]> = {
  ok: ['bg-clean-bg text-clean', 'Signed in.'],
  denied: ['bg-defect-bg text-defect', 'That account could not sign in.'],
  expired: ['bg-review-bg text-review', 'That sign-in took too long. Try again.'],
  failed: ['bg-defect-bg text-defect', 'Sign-in failed.'],
}

const GMAIL_OUTCOMES: Record<string, [string, string]> = {
  connected: ['bg-clean-bg text-clean', 'Gmail connected.'],
  denied: ['bg-defect-bg text-defect', 'Gmail access was not granted.'],
  expired: ['bg-review-bg text-review', 'That authorisation took too long. Press Connect Gmail again.'],
  failed: ['bg-defect-bg text-defect', 'Gmail could not be connected.'],
}

function readOutcome(): { tone: string; message: string } | null {
  const params = new URLSearchParams(window.location.search)
  const outcome =
    GMAIL_OUTCOMES[params.get('gmail') ?? ''] ??
    SIGNIN_OUTCOMES[params.get('signin') ?? '']
  if (!outcome) return null
  const [tone, message] = outcome
  const detail = params.get('detail')
  // Strip it, so a reload does not repeat a message about something that
  // already happened.
  window.history.replaceState({}, '', window.location.pathname)
  return { tone, message: detail ? `${message} ${detail}` : message }
}

export default function App() {
  // null while we are still asking. The session cookie is HttpOnly, so the
  // page cannot read it — only the server knows, and showing a sign-in screen
  // to somebody who is already signed in is worse than a brief blank.
  const [ready, setReady] = useState<boolean | null>(null)
  const [me, setMe] = useState<Me | null>(null)
  const [data, setData] = useState<Inbox | null>(null)
  const [gmail, setGmail] = useState<GmailStatus | null>(null)
  const [lane, setLane] = useState('BL_COMPARISON')
  const [onlyFlagged, setOnlyFlagged] = useState(false)
  const [selected, setSelected] = useState<{ result: Result; case: Case | null } | null>(null)
  // Read is an archive you browse; everything else is a queue you work
  // through. So the lane decides the layout and there is no toggle: one
  // less thing on screen, and no way to end up in the wrong one.
  const READ_LANE = 'READ'
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState(readOutcome)

  const load = useCallback(async () => {
    try {
      setData(await api.inbox())
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])

  // Ask who we are. A 401 here is an answer, not a failure: it means no
  // session, and a held service token is still a valid way in.
  useEffect(() => {
    api
      .me()
      .then((who) => {
        setMe(who)
        setReady(true)
      })
      .catch(() => {
        setMe(null)
        setReady(Boolean(getToken()))
      })
  }, [])

  // The trap this replaces: `ready` was set once and never went back, so a
  // rotated VS_SERVICE_TOKEN left the page rendering the shell with an error
  // and no way out short of clearing localStorage by hand.
  useEffect(() => {
    whenRejected(() => {
      setMe(null)
      setReady(false)
    })
  }, [])

  useEffect(() => {
    if (!ready) return
    load()
    api.gmailStatus().then(setGmail).catch(() => setGmail(null))
  }, [ready, load])

  const signOut = useCallback(async () => {
    // The cookie is the server's to clear; the token is ours.
    await api.signOut().catch(() => {})
    clearToken()
    setMe(null)
    setData(null)
    setReady(false)
  }, [])

  const open = useCallback(async (id: string) => {
    try {
      setSelected(await api.email(id))
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])

  const refreshBoth = useCallback(async () => {
    await load()
    if (selected) await open(selected.result.email_id)
  }, [load, open, selected])

  const rows = useMemo(() => {
    const all = data?.lanes?.[lane] || []
    return onlyFlagged
      ? all.filter((r) => r.status !== 'OK' || r.concerns?.length)
      : all
  }, [data, lane, onlyFlagged])

  if (ready === null) {
    return (
      <div className="grid h-full place-items-center p-6 text-sm text-muted-foreground">
        …
      </div>
    )
  }
  if (!ready) return <SignIn onDone={() => setReady(true)} />

  const stats = data?.stats
  const empty = stats && stats.total === 0
  const tiles = [
    { value: stats?.total, label: 'emails', tone: '' },
    { value: stats?.defects_found, label: 'with errors', tone: 'text-defect' },
    { value: stats?.awaiting_review, label: 'need a person', tone: 'text-review' },
    {
      value: stats ? `${Math.round(stats.minutes_saved / 60)}h` : undefined,
      label: 'checking saved',
      tone: '',
    },
  ]

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-4 border-b px-5 py-3">
        <div className="font-semibold">
          VS-Mail
          <span className="ml-2 text-sm font-normal text-muted-foreground">
            shipping document checks
          </span>
        </div>

        <div className="flex gap-2">
          {tiles.map((t) => (
            <div key={t.label} className="rounded-lg border px-3 py-1.5 text-center">
              <div className={`text-base font-semibold ${t.tone}`}>{t.value ?? '—'}</div>
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                {t.label}
              </div>
            </div>
          ))}
        </div>

        <div className="flex-1" />
        <Controls gmail={gmail} onChanged={refreshBoth} onError={setError} />

        {/* Who is signed in, and the way out. Separate from the mailbox card
            below, which says which mailbox the app works on. */}
        <div className="flex items-center gap-2 border-l pl-4">
          {me && (
            <span className="max-w-44 truncate text-xs text-muted-foreground" title={me.email}>
              {me.email}
            </span>
          )}
          <Button size="sm" variant="ghost" onClick={signOut}>
            <LogOut />
            Sign out
          </Button>
        </div>
      </header>

      {error && (
        <div className="mx-5 mt-3 rounded-md bg-defect-bg px-3 py-2 text-sm text-defect">
          {error}
        </div>
      )}
      {notice && (
        <button
          className={`mx-5 mt-3 rounded-md px-3 py-2 text-left text-sm ${notice.tone}`}
          onClick={() => setNotice(null)}
        >
          {notice.message}
        </button>
      )}

      <div
        className={`grid min-h-0 flex-1 divide-x ${
          lane === READ_LANE ? 'grid-cols-[15rem_22rem_1fr]' : 'grid-cols-[15rem_1fr]'
        }`}
      >
        <nav className="flex flex-col gap-1 overflow-y-auto p-3">
          <h3 className="px-2 py-1 text-[11px] uppercase tracking-wide text-muted-foreground">
            Inbox
          </h3>
          {Object.entries(CATEGORY_LABELS).map(([key, label]) => {
            const items = data?.lanes?.[key] || []
            // Read is finished work. A red dot there reads as "needs
            // attention" about something already dealt with.
            const flagged =
              key === READ_LANE
                ? 0
                : items.filter((r) => r.status !== 'OK').length
            return (
              <button
                key={key}
                className={`flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors ${
                  lane === key ? 'bg-primary text-primary-foreground' : 'hover:bg-accent'
                }`}
                onClick={() => {
                  setLane(key)
                  setSelected(null)
                }}
              >
                <span
                  className={`size-1.5 shrink-0 rounded-full ${
                    flagged ? 'bg-defect' : 'bg-border'
                  }`}
                />
                <span className="flex-1 truncate">{label}</span>
                <span className="text-xs opacity-70">{items.length}</span>
              </button>
            )
          })}

          <h3 className="mt-3 px-2 py-1 text-[11px] uppercase tracking-wide text-muted-foreground">
            Filter
          </h3>
          <button
            className={`rounded-md px-2 py-1.5 text-left text-sm transition-colors ${
              onlyFlagged ? 'bg-primary text-primary-foreground' : 'hover:bg-accent'
            }`}
            onClick={() => setOnlyFlagged((v) => !v)}
          >
            Only ones needing attention
          </button>

          {gmail && (
            <div className="mt-3">
              <h3 className="px-2 py-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                Mailbox
              </h3>
              <GmailCard
                gmail={gmail}
                onChanged={() =>
                  api.gmailStatus().then(setGmail).catch(() => setGmail(null))
                }
                onError={setError}
              />
            </div>
          )}

          {stats?.ran_at && (
            <div className="mt-3 px-2 text-xs text-muted-foreground">
              Last run {relative(stats.ran_at)} · {stats.source}
            </div>
          )}
        </nav>

        {lane !== READ_LANE && (
          <Deck lane={lane} rows={rows} onSent={refreshBoth} />
        )}

        {lane === READ_LANE && (
        <div className="min-h-0 overflow-y-auto">
          {!data && <SkeletonRows rows={6} className="p-3" />}
          {empty && (
            <p className="p-6 text-sm text-muted-foreground">
              Nothing processed yet. Choose a source and press <b>Process inbox</b>.
            </p>
          )}
          {data && !empty && rows.length === 0 && (
            <p className="p-6 text-sm text-muted-foreground">Nothing here.</p>
          )}
          {rows.map((row) => {
            const tone = statusTone(row)
            return (
              <button
                key={row.email_id}
                className={`flex w-full flex-col gap-1 border-b px-4 py-3 text-left transition-colors ${
                  selected?.result.email_id === row.email_id ? 'bg-accent' : 'hover:bg-muted/50'
                }`}
                onClick={() => open(row.email_id)}
              >
                <div className="truncate text-xs text-muted-foreground">
                  {row.sender || row.email_id}
                </div>
                <div className="truncate text-sm font-medium">
                  {row.subject || '(no subject)'}
                </div>
                <Badge className={TONE_CLASS[tone]}>
                  {row.status === 'MISMATCH'
                    ? row.defect_fields.join(', ')
                    : row.status === 'NEEDS_REVIEW'
                      ? REVIEW_REASONS[row.review_reason ?? ''] ||
                        row.review_reason?.replace(/_/g, ' ')
                      : row.concerns?.length
                        ? 'uncertain'
                        : 'checked'}
                </Badge>
              </button>
            )
          })}
        </div>
        )}

        {lane === READ_LANE && (
          <Detail email={selected} onChanged={refreshBoth} onError={setError} />
        )}
      </div>
    </div>
  )
}
