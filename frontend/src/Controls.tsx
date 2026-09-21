import { useEffect, useRef, useState } from 'react'
import { api, type GmailStatus, type Job } from '@/api'
import { Button } from '@/components/ui/button'

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
  const [starting, setStarting] = useState(false)
  const [changingWatch, setChangingWatch] = useState(false)
  const callbacks = useRef({ onChanged, onError })
  callbacks.current = { onChanged, onError }

  // A watcher runs continuously; it must not occupy the inbox processing slot.
  useEffect(() => {
    let active = true
    api.runningJobs().then(({ jobs }) => {
      if (active) setJob(jobs.find((item) => item.kind === 'run') ?? null)
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
          callbacks.current.onError(next.error || next.message || 'Inbox processing failed.')
        } else if (next.state !== 'running') {
          callbacks.current.onChanged()
        }
      } catch (error) {
        callbacks.current.onError((error as Error).message)
        setJob(null)
      }
    }, 900)
    return () => clearInterval(timer)
  }, [job])

  const processInbox = async () => {
    setStarting(true)
    try {
      setJob(await api.startRun())
    } catch (error) {
      onError((error as Error).message)
    } finally {
      setStarting(false)
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

  const busy = starting || job?.state === 'running'

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        loading={busy}
        disabled={busy || !gmail?.ready}
        onClick={processInbox}
      >
        {job?.state === 'running' ? `Processing ${job.done}/${job.total}` : 'Process inbox'}
      </Button>

      {gmail?.ready ? (
        <Button
          variant={watching ? 'secondary' : 'outline'}
          loading={changingWatch}
          disabled={changingWatch}
          onClick={toggleWatch}
          title={watching ? 'Pause automatic processing of new mail' : 'Automatically process new mail'}
        >
          {watching ? 'Pause monitoring' : 'Resume monitoring'}
        </Button>
      ) : (
        <span className="text-xs text-muted-foreground">Connect Gmail to process your inbox.</span>
      )}

      {job?.state === 'running' && (
        <span className="text-xs text-muted-foreground" role="status">{job.message}</span>
      )}
    </div>
  )
}
