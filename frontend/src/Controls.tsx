import { useEffect, useState } from 'react'
import { api, type GmailStatus, type Job, type Stats } from '@/api'
import { Button } from '@/components/ui/button'

// Seeding and running take minutes, so they return a job and the bar polls
// it. Nobody should need a terminal open during a demo.
export default function Controls({
  stats,
  gmail,
  onChanged,
  onError,
}: {
  stats: Stats | undefined
  gmail: GmailStatus | null
  onChanged: () => void
  onError: (message: string) => void
}) {
  const [job, setJob] = useState<Job | null>(null)
  const [watching, setWatching] = useState(false)
  const [source, setSource] = useState('bundle')
  const [provider, setProvider] = useState('mock')

  useEffect(() => {
    api.watchStatus().then((s) => setWatching(s.watching)).catch(() => {})
  }, [])

  // While something is running, poll it; when it finishes, refresh the inbox.
  useEffect(() => {
    if (!job || job.state !== 'running') return
    const timer = setInterval(async () => {
      try {
        const next = await api.job(job.id)
        setJob(next)
        if (next.state !== 'running') onChanged()
      } catch (error) {
        onError((error as Error).message)
        setJob(null)
      }
    }, 900)
    return () => clearInterval(timer)
  }, [job, onChanged, onError])

  const start = async (fn: () => Promise<Job>) => {
    try {
      setJob(await fn())
    } catch (error) {
      onError((error as Error).message)
    }
  }

  const toggleWatch = async () => {
    try {
      if (watching) {
        await api.stopWatch()
        setWatching(false)
      } else {
        await api.startWatch({ provider, interval: 10 })
        setWatching(true)
      }
    } catch (error) {
      onError((error as Error).message)
    }
  }

  const busy = job?.state === 'running'
  const progress = busy && job.total ? ` ${job.done}/${job.total}` : ''
  const select =
    'h-9 rounded-md border bg-background px-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50'

  return (
    <div className="flex flex-wrap items-center gap-2">
      <select
        className={select}
        value={source}
        onChange={(e) => setSource(e.target.value)}
        disabled={busy}
      >
        <option value="bundle">Sample data</option>
        <option value="gmail" disabled={!gmail?.ready}>
          {gmail?.ready ? `Gmail — ${gmail.mailbox}` : 'Gmail — not connected'}
        </option>
      </select>

      <select
        className={select}
        value={provider}
        onChange={(e) => setProvider(e.target.value)}
        disabled={busy}
      >
        <option value="mock">Offline rules</option>
        <option value="deepseek">DeepSeek</option>
        <option value="remote">Deployed service</option>
      </select>

      <Button
        loading={busy && job.kind === 'run'}
        disabled={busy}
        onClick={() =>
          start(() => api.startRun({ source, provider, labels: source === 'gmail' }))
        }
      >
        {busy && job.kind === 'run' ? `Processing${progress}` : 'Process inbox'}
      </Button>

      {gmail?.ready && (
        <>
          <Button
            variant="outline"
            loading={busy && job.kind === 'seed'}
            disabled={busy}
            onClick={() => start(() => api.seed())}
          >
            {busy && job.kind === 'seed' ? `Seeding${progress}` : 'Seed Gmail'}
          </Button>
          <Button variant={watching ? 'secondary' : 'outline'} onClick={toggleWatch}>
            {watching ? '● Watching — stop' : 'Watch for new mail'}
          </Button>
        </>
      )}

      {/* Outside the Gmail block: the results are on screen whether or not a
          mailbox is connected, and "Clear Gmail" used to leave all 520 of
          them sitting there because they live in a different store. */}
      <Button
        variant="outline"
        disabled={busy}
        onClick={() => start(() => api.clearEverything())}
      >
        Clear everything
      </Button>

      {busy && <span className="text-xs text-muted-foreground">{job.message}</span>}
      {stats?.ran_at && !busy && (
        <span className="text-xs text-muted-foreground">
          {stats.source} · {stats.total} emails
        </span>
      )}
    </div>
  )
}
