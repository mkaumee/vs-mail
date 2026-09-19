import { useCallback, useEffect, useMemo, useState } from 'react'
import Controls from './Controls.jsx'
import Detail from './Detail.jsx'
import { api, getToken, setToken } from './api.js'
import { CATEGORY_LABELS, relative, statusTone } from './format.js'

function Gate({ onDone }) {
  const [value, setValue] = useState('')
  return (
    <div className="gate">
      <div className="card">
        <h2 style={{ marginTop: 0 }}>VS-Mail</h2>
        <p>
          The service is protected by a shared secret, so this page needs the
          same <code>VS_SERVICE_TOKEN</code> the server was started with.
        </p>
        <div className="fix">
          <input
            type="password"
            placeholder="Service token"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && value.trim() && (setToken(value), onDone())}
          />
          <button
            className="primary"
            disabled={!value.trim()}
            onClick={() => { setToken(value); onDone() }}
          >
            Connect
          </button>
        </div>
      </div>
    </div>
  )
}

export default function App() {
  const [ready, setReady] = useState(Boolean(getToken()))
  const [data, setData] = useState(null)
  const [lane, setLane] = useState('BL_COMPARISON')
  const [onlyFlagged, setOnlyFlagged] = useState(false)
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      setData(await api.inbox())
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => { if (ready) load() }, [ready, load])

  const open = useCallback(async (id) => {
    try {
      setSelected(await api.email(id))
    } catch (e) {
      setError(e.message)
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

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">VS-Mail<span>shipping document checks</span></div>

        <div className="tiles">
          <div className="tile"><b>{stats?.total ?? '—'}</b><small>emails</small></div>
          <div className="tile defect"><b>{stats?.defects_found ?? '—'}</b><small>with errors</small></div>
          <div className="tile review"><b>{stats?.awaiting_review ?? '—'}</b><small>need a person</small></div>
          <div className="tile">
            <b>{stats ? Math.round(stats.minutes_saved / 60) : '—'}h</b>
            <small>checking saved</small>
          </div>
        </div>

        <div className="spacer" />
        <Controls stats={stats} onChanged={refreshBoth} onError={setError} />
      </header>

      {error && <div className="note error" style={{ margin: '10px 18px' }}>{error}</div>}

      <div className="panes">
        <nav className="sidebar">
          <h3>Inbox</h3>
          {Object.entries(CATEGORY_LABELS).map(([key, label]) => {
            const items = data?.lanes?.[key] || []
            const flagged = items.filter((r) => r.status !== 'OK').length
            return (
              <button
                key={key}
                className={`lane ${lane === key ? 'on' : ''}`}
                onClick={() => { setLane(key); setSelected(null) }}
              >
                <span
                  className="dot"
                  style={{ background: flagged ? 'var(--defect)' : 'var(--line)' }}
                />
                {label}
                <span className="count">{items.length}</span>
              </button>
            )
          })}

          <h3>Filter</h3>
          <button
            className={`lane ${onlyFlagged ? 'on' : ''}`}
            onClick={() => setOnlyFlagged((v) => !v)}
          >
            Only ones needing attention
          </button>

          {stats?.ran_at && (
            <>
              <h3>Last run</h3>
              <div style={{ padding: '0 10px', color: 'var(--ink-3)', fontSize: 12 }}>
                {relative(stats.ran_at)} · {stats.source}
              </div>
            </>
          )}
        </nav>

        <div className="list">
          {empty && (
            <p className="empty">
              Nothing processed yet. Choose a source and press <b>Process inbox</b>.
            </p>
          )}
          {!empty && rows.length === 0 && <p className="empty">Nothing here.</p>}
          {rows.map((row) => {
            const tone = statusTone(row)
            return (
              <button
                key={row.email_id}
                className={`row ${selected?.result.email_id === row.email_id ? 'on' : ''}`}
                onClick={() => open(row.email_id)}
              >
                <div className="who">{row.sender || row.email_id}</div>
                <div className="subject">{row.subject || '(no subject)'}</div>
                <span className={`pill ${tone}`}>
                  {row.status === 'MISMATCH'
                    ? row.defect_fields.join(', ')
                    : row.status === 'NEEDS_REVIEW'
                      ? row.review_reason?.replace(/_/g, ' ')
                      : row.concerns?.length
                        ? 'uncertain'
                        : 'checked'}
                </span>
              </button>
            )
          })}
        </div>

        <Detail email={selected} onChanged={refreshBoth} onError={setError} />
      </div>
    </div>
  )
}
