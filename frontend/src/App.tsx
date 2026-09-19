import { useCallback, useEffect, useMemo, useState } from 'react'
import Controls from './Controls'
import Detail from './Detail'
import GmailCard from '@/components/GmailCard'
import { api, getToken, setToken, type Case, type GmailStatus, type Inbox, type Result } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { SkeletonRows } from '@/components/ui/skeleton'
import { CATEGORY_LABELS, REVIEW_REASONS, TONE_CLASS, relative, statusTone } from './format'

function Gate({ onDone }: { onDone: () => void }) {
  const [value, setValue] = useState('')
  const go = () => {
    setToken(value)
    onDone()
  }
  return (
    <div className="grid h-full place-items-center p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>VS-Mail</CardTitle>
          <p className="text-sm text-muted-foreground">
            The service is protected by a shared secret, so this page needs the
            same <code className="rounded bg-muted px-1 py-0.5 text-xs">VS_SERVICE_TOKEN</code>{' '}
            the server was started with.
          </p>
        </CardHeader>
        <CardContent className="flex gap-2">
          <input
            type="password"
            placeholder="Service token"
            className="h-9 flex-1 rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && value.trim() && go()}
          />
          <Button disabled={!value.trim()} onClick={go}>
            Connect
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}

// The OAuth callback cannot return JSON — a person's browser lands on it —
// so it says how it went in the URL and the app reports it here.
const GMAIL_OUTCOMES: Record<string, [string, string]> = {
  connected: ['bg-clean-bg text-clean', 'Gmail connected.'],
  denied: ['bg-defect-bg text-defect', 'Gmail access was not granted.'],
  expired: ['bg-review-bg text-review', 'That authorisation took too long. Press Connect Gmail again.'],
  failed: ['bg-defect-bg text-defect', 'Gmail could not be connected.'],
}

function readGmailOutcome(): { tone: string; message: string } | null {
  const params = new URLSearchParams(window.location.search)
  const outcome = GMAIL_OUTCOMES[params.get('gmail') ?? '']
  if (!outcome) return null
  const [tone, message] = outcome
  const detail = params.get('detail')
  // Strip it, so a reload does not repeat a message about something that
  // already happened.
  window.history.replaceState({}, '', window.location.pathname)
  return { tone, message: detail ? `${message} ${detail}` : message }
}

export default function App() {
  const [ready, setReady] = useState(Boolean(getToken()))
  const [data, setData] = useState<Inbox | null>(null)
  const [gmail, setGmail] = useState<GmailStatus | null>(null)
  const [lane, setLane] = useState('BL_COMPARISON')
  const [onlyFlagged, setOnlyFlagged] = useState(false)
  const [selected, setSelected] = useState<{ result: Result; case: Case | null } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState(readGmailOutcome)

  const load = useCallback(async () => {
    try {
      setData(await api.inbox())
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])

  useEffect(() => {
    if (!ready) return
    load()
    api.gmailStatus().then(setGmail).catch(() => setGmail(null))
  }, [ready, load])

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

  if (!ready) return <Gate onDone={() => setReady(true)} />

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
        <Controls stats={stats} gmail={gmail} onChanged={refreshBoth} onError={setError} />
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

      <div className="grid min-h-0 flex-1 grid-cols-[15rem_22rem_1fr] divide-x">
        <nav className="flex flex-col gap-1 overflow-y-auto p-3">
          <h3 className="px-2 py-1 text-[11px] uppercase tracking-wide text-muted-foreground">
            Inbox
          </h3>
          {Object.entries(CATEGORY_LABELS).map(([key, label]) => {
            const items = data?.lanes?.[key] || []
            const flagged = items.filter((r) => r.status !== 'OK').length
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
              <GmailCard gmail={gmail} onError={setError} />
            </div>
          )}

          {stats?.ran_at && (
            <div className="mt-3 px-2 text-xs text-muted-foreground">
              Last run {relative(stats.ran_at)} · {stats.source}
            </div>
          )}
        </nav>

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

        <Detail email={selected} onChanged={refreshBoth} onError={setError} />
      </div>
    </div>
  )
}
