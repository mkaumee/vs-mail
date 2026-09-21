import { useCallback, useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { CircleHelp, Clock, Filter, Mail, TriangleAlert } from 'lucide-react'
import Controls from './Controls'
import Deck from './Deck'
import Detail from './Detail'
import SignIn from '@/components/SignIn'
import SettingsPage from '@/pages/SettingsPage'
import GmailPage from '@/pages/GmailPage'
import Sidebar from '@/components/layout/Sidebar'
import { useRoute } from './useRoute'
import TopBar from '@/components/layout/TopBar'
import StatCard from '@/components/layout/StatCard'
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
import {
  CATEGORY_LABELS, REVIEW_REASONS, TONE_CLASS,
  firstName, greeting, relative, statusTone,
} from './format'

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
  const { view, go } = useRoute()

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
    // The session cookie is HttpOnly, so only the server knows. A brief
    // shimmer beats showing a sign-in screen to somebody already signed in.
    return (
      <div className="grid h-full place-items-center p-6">
        <div className="w-full max-w-md space-y-3">
          <div className="skeleton h-9 w-40" />
          <div className="skeleton h-4 w-full" />
          <div className="skeleton h-4 w-2/3" />
        </div>
      </div>
    )
  }
  if (!ready) return <SignIn onDone={() => setReady(true)} />

  const stats = data?.stats
  const empty = stats && stats.total === 0
  const laneLabel = CATEGORY_LABELS[lane] ?? lane
  // Which group the lane sits in, so the crumb adds something instead of
  // repeating the heading next to it.
  const laneGroup =
    lane === 'BL_COMPARISON' ? 'Verification' : lane === READ_LANE ? 'Done' : 'Inbox'

  return (
    <div className="app">
      {/* The ambient wash. Fixed, inert, behind everything. */}
      <div className="ambient" aria-hidden>
        <i /><i /><i />
      </div>

      <Sidebar
        data={data}
        lane={lane}
        view={view}
        onLane={(next) => {
          setLane(next)
          setSelected(null)
          go('lanes')
        }}
        onView={go}
      >
        {/* The mailbox has its own screen now, and the top-bar chip says
            its state. A third copy down here was two too many. */}
        {stats?.ran_at ? (
          <div>Last run {relative(stats.ran_at)}</div>
        ) : (
          <div>Nothing processed yet.</div>
        )}
      </Sidebar>

      <div className="app__main">
        <TopBar
          title={view === 'lanes' ? laneLabel : view === 'gmail' ? 'Gmail' : 'Settings'}
          crumb={view === 'lanes' ? laneGroup : 'System'}
          gmail={gmail}
          me={me}
          onGmail={() => go('gmail')}
          onSignOut={signOut}
        />

        <main className="app__content">
          <div className="page">
            {view === 'lanes' ? (
            <div className="page-head">
              <div className="page-head__row">
                <div className="min-w-0 flex-1">
                  <motion.h1
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.3, ease: [0.2, 0.8, 0.2, 1] }}
                  >
                    {greeting()}
                    {firstName(me) && `, ${firstName(me)}`}
                  </motion.h1>
                  <p className="page-head__sub">
                    {stats?.awaiting_review
                      ? `${stats.awaiting_review} cases need a person.`
                      : 'Shipping document checks and drafted replies.'}
                  </p>
                </div>
                <div className="page-head__actions">
                  {lane !== READ_LANE && (
                    <Button
                      size="sm"
                      variant={onlyFlagged ? 'default' : 'outline'}
                      onClick={() => setOnlyFlagged((v) => !v)}
                    >
                      <Filter />
                      Needs attention
                    </Button>
                  )}
                  <Controls gmail={gmail} onChanged={refreshBoth} onError={setError} />
                </div>
              </div>
            </div>
            ) : (
              <div className="page-head">
                <h1>{view === 'gmail' ? 'Gmail' : 'Settings'}</h1>
                <p className="page-head__sub">
                  {view === 'gmail'
                    ? 'Your mailbox connection. It is separate from signing in to VS-Mail.'
                    : 'Preferences are kept in this browser. Credentials never are.'}
                </p>
              </div>
            )}

            {view === 'lanes' && (
            <div className="stat-grid">
              <StatCard label="Emails" value={stats?.total} hint="processed" icon={Mail} delay={0} />
              <StatCard label="With errors" value={stats?.defects_found} hint="fields disagree" icon={TriangleAlert} tone="bad" delay={0.05} />
              <StatCard label="Need a person" value={stats?.awaiting_review} hint="escalated" icon={CircleHelp} tone="warn" delay={0.1} />
              <StatCard
                label="Checking saved"
                value={stats ? `${Math.round(stats.minutes_saved / 60)}h` : undefined}
                hint="against reading by hand"
                icon={Clock}
                tone="ok"
                delay={0.15}
              />
            </div>
            )}

            {error && (
              <div className="mb-4 rounded-md bg-defect-bg px-3 py-2 text-sm text-defect">
                {error}
              </div>
            )}
            {notice && (
              <button
                className={`mb-4 w-full rounded-md px-3 py-2 text-left text-sm ${notice.tone}`}
                onClick={() => setNotice(null)}
              >
                {notice.message}
              </button>
            )}

            {view === 'settings' && (
              <SettingsPage gmail={gmail} onManageGmail={() => go('gmail')} />
            )}

            {view === 'gmail' && (
              <GmailPage
                gmail={gmail}
                me={me}
                onChanged={() =>
                  api.gmailStatus().then(setGmail).catch(() => setGmail(null))
                }
                onError={setError}
              />
            )}

            {view === 'lanes' && (
            <AnimatePresence mode="wait">
              <motion.div
                key={lane}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}
                className="glass-2 min-h-[26rem] overflow-hidden"
              >
                {lane !== READ_LANE ? (
                  <Deck lane={lane} rows={rows} onSent={refreshBoth} />
                ) : (
                  <ReadLane
                    data={data}
                    rows={rows}
                    empty={empty}
                    selected={selected}
                    onOpen={open}
                    onChanged={refreshBoth}
                    onError={setError}
                  />
                )}
              </motion.div>
            </AnimatePresence>
            )}
          </div>
        </main>
      </div>
    </div>
  )
}

/** The archive: rows on the left, the one you clicked on the right. */
function ReadLane({
  data,
  rows,
  empty,
  selected,
  onOpen,
  onChanged,
  onError,
}: {
  data: Inbox | null
  rows: Result[]
  empty: boolean | undefined
  selected: { result: Result; case: Case | null } | null
  onOpen: (id: string) => void
  onChanged: () => void
  onError: (message: string) => void
}) {
  return (
    <div className="grid min-h-[26rem] grid-cols-[22rem_1fr] divide-x">
      <div className="max-h-[70vh] min-h-0 overflow-y-auto">
        {!data && <SkeletonRows rows={6} className="p-3" />}
        {empty && (
          <p className="p-6 text-sm text-muted-foreground">
            Nothing processed yet. Connect Gmail and press <b>Process inbox</b>.
          </p>
        )}
        {data && !empty && rows.length === 0 && (
          <p className="p-6 text-sm text-muted-foreground">Nothing sent yet.</p>
        )}
        {rows.map((row, i) => {
          const tone = statusTone(row)
          return (
            <motion.button
              key={row.email_id}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.2, delay: Math.min(i, 12) * 0.02 }}
              className={`flex w-full flex-col gap-1 border-b px-4 py-3 text-left transition-colors ${
                selected?.result.email_id === row.email_id
                  ? 'bg-gold-soft'
                  : 'hover:bg-muted/50'
              }`}
              onClick={() => onOpen(row.email_id)}
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
            </motion.button>
          )
        })}
      </div>
      <Detail email={selected} onChanged={onChanged} onError={onError} />
    </div>
  )
}
