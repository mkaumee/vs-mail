import { useEffect, useRef, useState } from 'react'
import { api, type GmailStatus, type Job } from '@/api'
import { Button } from '@/components/ui/button'

const RESUME_WATCH_AFTER_SEED = 'vsmail.resumeWatchAfterSeed'

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
  const callbacks = useRef({ onChanged, onError })
  callbacks.current = { onChanged, onError }

  // A watcher runs continuously; it must not occupy the inbox processing slot.
  useEffect(() => {
    let active = true
    api.runningJobs().then(async ({ jobs }) => {
      if (!active) return
      const current = jobs.find((item) => item.kind === 'run' || item.kind === 'seed') ?? null
      setJob(current)
      if (!current && localStorage.getItem(RESUME_WATCH_AFTER_SEED) === '1') {
        localStorage.removeItem(RESUME_WATCH_AFTER_SEED)
        const watcher = await api.startWatch()
        if (active) setWatching(watcher.state === 'running')
      }
    }).catch((error: Error) => {
      if (active) callbacks.current.onError(error.message)
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
    let active = true
    let timer: ReturnType<typeof setTimeout>
    let previous: Job | null = null

    const sync = async (initial = false) => {
      try {
        const status = await api.watchStatus()
        if (!active) return
        const current = initial && !status.job ? await api.startWatch() : status.job
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
  }, [gmail?.ready])

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
          next.kind === 'seed' &&
          next.state !== 'running' &&
          localStorage.getItem(RESUME_WATCH_AFTER_SEED) === '1'
        ) {
          localStorage.removeItem(RESUME_WATCH_AFTER_SEED)
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
      if (kind === 'seed' && watching) {
        // Otherwise every inserted sample looks like new live mail and the
        // model starts processing the mailbox while it is still being filled.
        await api.stopWatch()
        setWatching(false)
        localStorage.setItem(RESUME_WATCH_AFTER_SEED, '1')
      }
      setJob(await (kind === 'seed' ? api.seed() : api.startRun()))
    } catch (error) {
      onError((error as Error).message)
      if (kind === 'seed' && localStorage.getItem(RESUME_WATCH_AFTER_SEED) === '1') {
        localStorage.removeItem(RESUME_WATCH_AFTER_SEED)
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

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        loading={processing}
        disabled={busy || !gmail?.ready}
        onClick={() => start('run')}
      >
        {job?.kind === 'run' && job.state === 'running' ? `Processing ${job.done}/${job.total}` : 'Process inbox'}
      </Button>

      {gmail?.ready ? (
        <>
          <Button
            variant="outline"
            loading={seeding}
            disabled={busy}
            onClick={() => start('seed')}
          >
            {job?.kind === 'seed' && job.state === 'running' ? `Seeding ${job.done}/${job.total}` : 'Seed Gmail'}
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

      {job?.state === 'running' && (
        <span className="text-xs text-muted-foreground" role="status">{job.message}</span>
      )}
    </div>
  )
}
