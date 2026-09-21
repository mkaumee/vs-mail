import { useEffect, useRef, useState } from 'react'
import { api, type GmailStatus, type Job } from '@/api'
import { Button } from '@/components/ui/button'

const RESUME_WATCH_AFTER_JOB = 'vsmail.resumeWatchAfterSeed'
const PROCESS_LIMIT = 'vsmail.processLimit'
const ALLOWED_LIMITS = ['5', '10', '25', '50', 'all'] as const

function initialLimit(): string {
  const saved = localStorage.getItem(PROCESS_LIMIT)
  return saved && (ALLOWED_LIMITS as readonly string[]).includes(saved) ? saved : '10'
}

const PHASE_LABELS: Record<string, string> = {
  starting: 'Starting',
  reading_mailbox: 'Reading Gmail',
  classifying: 'Classifying emails',
  reading_documents: 'Reading attachments',
  extracting: 'Extracting shipping fields',
  comparing: 'Comparing documents',
  checking_discrepancies: 'Checking discrepancies',
  saving_results: 'Saving results',
  applying_labels: 'Applying Gmail labels',
  loading_samples: 'Loading sample emails',
  complete: 'Complete',
}

export default function Controls({
  gmail,
  onChanged,
  onError,
}: {
  gmail: GmailStatus | null
  onChanged: () => void
  onError: (message: string) => void
}) {
  const [job, setJob] = useState<Job | null>(null)
  const [watching, setWatching] = useState(false)
  const [starting, setStarting] = useState<'run' | 'seed' | null>(null)
  const [changingWatch, setChangingWatch] = useState(false)
  const [processLimit, setProcessLimit] = useState(initialLimit)
  const [recoveringJobs, setRecoveringJobs] = useState(true)
  const callbacks = useRef({ onChanged, onError })
  callbacks.current = { onChanged, onError }

  // A watcher runs continuously; it must not occupy the inbox processing slot.
  useEffect(() => {
    let active = true
    api.runningJobs().then(async ({ jobs }) => {
      if (!active) return
      const current = jobs.find((item) => item.kind === 'run' || item.kind === 'seed') ?? null
      setJob(current)
      if (!current && localStorage.getItem(RESUME_WATCH_AFTER_JOB) === '1') {
        localStorage.removeItem(RESUME_WATCH_AFTER_JOB)
        const watcher = await api.startWatch()
        if (active) setWatching(watcher.state === 'running')
      }
    }).catch((error: Error) => {
      if (active) callbacks.current.onError(error.message)
    }).finally(() => {
      if (active) setRecoveringJobs(false)
    })
    return () => { active = false }
  }, [])

  // Start watching a newly connected mailbox, but preserve an explicit pause.
  // Poll the actual job so failures and newly processed mail reach the page.
  useEffect(() => {
    if (!gmail?.ready) {
      setWatching(false)
      return
    }
    if (recoveringJobs) return
    let active = true
    let timer: ReturnType<typeof setTimeout>
    let previous: Job | null = null
    const manualBusy = starting !== null || (
      job?.state === 'running' && (job.kind === 'run' || job.kind === 'seed')
    )

    const sync = async (initial = false) => {
      try {
        const status = await api.watchStatus()
        if (!active) return
        const current = initial && !status.job && !manualBusy
          ? await api.startWatch()
          : status.job
        if (!active) return
        setWatching(current?.state === 'running')
        if (current?.state === 'failed' && previous?.state !== 'failed') {
          callbacks.current.onError(current.error || current.message || 'Mailbox monitoring failed.')
        } else if (current && previous && (current.id !== previous.id || current.done !== previous.done)) {
          callbacks.current.onChanged()
        }
        previous = current
      } catch (error) {
        if (active) callbacks.current.onError((error as Error).message)
      } finally {
        if (active) timer = setTimeout(() => sync(), 3000)
      }
    }
    void sync(true)
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [gmail?.ready, job?.id, job?.state, recoveringJobs, starting])

  useEffect(() => {
    if (!job || job.state !== 'running') return
    const timer = setInterval(async () => {
      try {
        const next = await api.job(job.id)
        setJob(next)
        if (next.state === 'failed') {
          callbacks.current.onError(next.error || next.message || 'The operation failed.')
        } else if (next.state !== 'running') {
          callbacks.current.onChanged()
        }
        if (
          next.state !== 'running' &&
          localStorage.getItem(RESUME_WATCH_AFTER_JOB) === '1'
        ) {
          localStorage.removeItem(RESUME_WATCH_AFTER_JOB)
          try {
            const watcher = await api.startWatch()
            setWatching(watcher.state === 'running')
          } catch (error) {
            callbacks.current.onError((error as Error).message)
          }
        }
      } catch (error) {
        callbacks.current.onError((error as Error).message)
        setJob(null)
      }
    }, 900)
    return () => clearInterval(timer)
  }, [job])

  const start = async (kind: 'run' | 'seed') => {
    setStarting(kind)
    try {
      if (watching) {
        // Manual jobs make many Gmail calls. Pause the poller so it cannot
        // consume quota at the same time (or process samples mid-import).
        await api.stopWatch()
        setWatching(false)
        localStorage.setItem(RESUME_WATCH_AFTER_JOB, '1')
      }
      setJob(await (
        kind === 'seed'
          ? api.seed()
          : api.startRun(processLimit === 'all' ? null : Number(processLimit))
      ))
    } catch (error) {
      onError((error as Error).message)
      if (localStorage.getItem(RESUME_WATCH_AFTER_JOB) === '1') {
        localStorage.removeItem(RESUME_WATCH_AFTER_JOB)
        try {
          const watcher = await api.startWatch()
          setWatching(watcher.state === 'running')
        } catch (watchError) {
          onError((watchError as Error).message)
        }
      }
    } finally {
      setStarting(null)
    }
  }

  const toggleWatch = async () => {
    setChangingWatch(true)
    try {
      if (watching) {
        await api.stopWatch()
        setWatching(false)
      } else {
        const next = await api.startWatch()
        setWatching(next.state === 'running')
      }
    } catch (error) {
      onError((error as Error).message)
    } finally {
      setChangingWatch(false)
    }
  }

  const busy = starting !== null || job?.state === 'running'
  const processing = starting === 'run' || (job?.kind === 'run' && job.state === 'running')
  const seeding = starting === 'seed' || (job?.kind === 'seed' && job.state === 'running')
  const running = job?.state === 'running'
  const percent = running && job.total > 0
    ? Math.min(100, Math.round((job.done / job.total) * 100))
    : 0

  const changeLimit = (value: string) => {
    setProcessLimit(value)
    localStorage.setItem(PROCESS_LIMIT, value)
  }

  return (
    <div className="flex max-w-xl flex-wrap items-center justify-end gap-2">
      <div className="flex h-9 items-center overflow-hidden rounded-md border bg-background shadow-xs">
        <label htmlFor="process-limit" className="pl-3 text-xs font-medium text-muted-foreground">
          Latest
        </label>
        <select
          id="process-limit"
          aria-label="Number of latest emails to process"
          className="h-full cursor-pointer bg-transparent px-2 text-sm font-medium outline-none disabled:cursor-not-allowed disabled:opacity-50"
          value={processLimit}
          disabled={busy || !gmail?.ready}
          onChange={(event) => changeLimit(event.target.value)}
        >
          <option value="5">5 emails</option>
          <option value="10">10 emails</option>
          <option value="25">25 emails</option>
          <option value="50">50 emails</option>
          <option value="all">All emails</option>
        </select>
        <Button
          className="rounded-l-none shadow-none"
          loading={processing}
          disabled={busy || !gmail?.ready}
          onClick={() => start('run')}
        >
          {processing ? `${job?.done ?? 0}/${job?.total || '…'}` : 'Process mail'}
        </Button>
      </div>

      {gmail?.ready ? (
        <>
          <Button
            variant="outline"
            loading={seeding}
            disabled={busy}
            onClick={() => start('seed')}
          >
            {seeding ? `${job?.done ?? 0}/${job?.total || '…'}` : 'Load sample emails'}
          </Button>
          <Button
            variant={watching ? 'secondary' : 'outline'}
            loading={changingWatch}
            disabled={changingWatch}
            onClick={toggleWatch}
            title={watching ? 'Pause automatic processing of new mail' : 'Automatically process new mail'}
          >
            {watching ? 'Pause monitoring' : 'Resume monitoring'}
          </Button>
        </>
      ) : (
        <span className="text-xs text-muted-foreground">Connect Gmail to process your inbox.</span>
      )}

      {running && (
        <div
          className="basis-full rounded-lg border bg-background/90 px-3 py-2.5 shadow-sm"
          role="status"
          aria-live="polite"
        >
          <div className="flex items-center justify-between gap-4 text-xs">
            <span className="font-semibold text-foreground">
              {PHASE_LABELS[job.phase] || job.message || 'Working'}
            </span>
            <span className="shrink-0 tabular-nums text-muted-foreground">
              {job.total > 0 ? `${job.done} of ${job.total} · ${percent}%` : 'Preparing…'}
            </span>
          </div>
          <div
            className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-label={PHASE_LABELS[job.phase] || 'Processing emails'}
            aria-valuemin={0}
            aria-valuemax={job.total || undefined}
            aria-valuenow={job.total ? job.done : undefined}
          >
            <div
              className={`h-full rounded-full bg-primary transition-[width] duration-500 ${job.total ? '' : 'animate-pulse'}`}
              style={{ width: job.total ? `${percent}%` : '32%' }}
            />
          </div>
          <p className="mt-1.5 truncate text-[11px] text-muted-foreground" title={job.message}>
            {job.message}
          </p>
        </div>
      )}
    </div>
  )
}
