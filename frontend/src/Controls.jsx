import { useEffect, useState } from 'react'
import { api } from './api.js'

// Seeding and running take minutes, so they return a job and the bar polls
// it. Nobody should need a terminal open during a demo.
export default function Controls({ stats, onChanged, onError }) {
  const [job, setJob] = useState(null)
  const [gmail, setGmail] = useState(null)
  const [watching, setWatching] = useState(false)
  const [source, setSource] = useState('bundle')
  const [provider, setProvider] = useState('mock')

  useEffect(() => {
    api.gmailStatus().then(setGmail).catch(() => setGmail({ ready: false }))
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
        onError(error.message)
        setJob(null)
      }
    }, 900)
    return () => clearInterval(timer)
  }, [job, onChanged, onError])

  const start = async (fn) => {
    try {
      setJob(await fn())
    } catch (error) {
      onError(error.message)
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
      onError(error.message)
    }
  }

  const busy = job?.state === 'running'
  const progress = busy && job.total ? ` ${job.done}/${job.total}` : ''

  return (
    <>
      <select value={source} onChange={(e) => setSource(e.target.value)} disabled={busy}>
        <option value="bundle">Sample data</option>
        <option value="gmail" disabled={!gmail?.ready}>
          {gmail?.ready ? `Gmail — ${gmail.mailbox}` : 'Gmail — not connected'}
        </option>
      </select>

      <select value={provider} onChange={(e) => setProvider(e.target.value)} disabled={busy}>
        <option value="mock">Offline rules</option>
        <option value="deepseek">DeepSeek</option>
        <option value="remote">Deployed service</option>
      </select>

      <button
        className="primary"
        disabled={busy}
        onClick={() => start(() => api.startRun({ source, provider, labels: source === 'gmail' }))}
      >
        {busy && job.kind === 'run' ? `Processing${progress}` : 'Process inbox'}
      </button>

      {gmail?.ready && (
        <>
          <button disabled={busy} onClick={() => start(() => api.seed())}>
            {busy && job.kind === 'seed' ? `Seeding${progress}` : 'Seed Gmail'}
          </button>
          <button disabled={busy} onClick={() => start(() => api.resetGmail())}>
            Clear Gmail
          </button>
          <button onClick={toggleWatch}>
            {watching ? '● Watching — stop' : 'Watch for new mail'}
          </button>
        </>
      )}

      {busy && <span className="tile"><small>{job.message}</small></span>}
      {stats?.ran_at && !busy && (
        <span className="tile"><small>{stats.source} · {stats.total} emails</small></span>
      )}
    </>
  )
}
