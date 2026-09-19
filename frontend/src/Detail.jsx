import { useState } from 'react'
import { api } from './api.js'
import { FIELD_LABELS, REVIEW_REASONS, statusTone } from './format.js'

const FIELDS = Object.keys(FIELD_LABELS)

// The comparison table is the whole point of the product, so it shows what
// each document said *and* why two differently written values were accepted.
// Proving the absence of a false alarm is otherwise invisible.
function Fields({ fields }) {
  if (!fields?.length) return null
  return (
    <div className="card">
      <h4>The seven fields</h4>
      <table className="fields">
        <thead>
          <tr><th>Field</th><th>Shipping instruction</th><th>Draft bill of lading</th></tr>
        </thead>
        <tbody>
          {fields.map((f) => (
            <tr
              key={f.field}
              className={[!f.equal && 'differs', f.uncertain && 'uncertain']
                .filter(Boolean)
                .join(' ')}
            >
              <td className="name">{FIELD_LABELS[f.field] || f.field}</td>
              <td className="value">{f.si ?? <em>blank</em>}</td>
              <td className="value">
                {f.bl ?? <em>blank</em>}
                {f.equal && f.note && <span className="why">✓ {f.note}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// Resolving supplies a value; it never writes a verdict. The comparison runs
// again over what the reviewer typed, so a wrong value produces a mismatch
// rather than a rubber stamp.
function Resolve({ result, onDone, onError }) {
  const [side, setSide] = useState('si')
  const [field, setField] = useState(result.defect_fields?.[0] || 'gross_weight_kg')
  const [value, setValue] = useState('')
  const [saving, setSaving] = useState(false)

  const submit = async (payload) => {
    setSaving(true)
    try {
      await api.resolve(result.email_id, payload)
      onDone()
    } catch (error) {
      onError(error.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="card">
      <h4>Resolve</h4>
      <p style={{ marginTop: 0, color: 'var(--ink-2)' }}>
        Supply the correct value and the comparison runs again over it. The
        verdict is never written by hand.
      </p>
      <div className="fix">
        <select value={side} onChange={(e) => setSide(e.target.value)}>
          <option value="si">Shipping instruction</option>
          <option value="bl">Bill of lading</option>
        </select>
        <select value={field} onChange={(e) => setField(e.target.value)}>
          {FIELDS.map((f) => <option key={f} value={f}>{FIELD_LABELS[f]}</option>)}
        </select>
        <input
          placeholder="The correct value"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <button
          className="primary"
          disabled={!value.trim() || saving}
          onClick={() => submit({ by: 'reviewer', [side]: { [field]: value.trim() } })}
        >
          Supply
        </button>
        <button
          disabled={saving}
          onClick={() => submit({ by: 'reviewer', confirm: true })}
          title="The escalation was right and there is nothing to fix"
        >
          Confirm as-is
        </button>
      </div>
    </div>
  )
}

export default function Detail({ email, onChanged, onError }) {
  if (!email) {
    return <div className="detail"><p className="empty">Choose an email to see what was found.</p></div>
  }

  const { result, case: reviewCase } = email
  const tone = statusTone(result)

  return (
    <div className="detail">
      <h2>{result.subject || '(no subject)'}</h2>
      <div className="meta">
        {result.sender || 'unknown sender'} · {result.email_id} ·{' '}
        <span className={`pill ${tone}`}>
          {result.status === 'MISMATCH'
            ? `${result.defect_fields.length} field${result.defect_fields.length === 1 ? '' : 's'} differ`
            : result.status === 'NEEDS_REVIEW'
              ? REVIEW_REASONS[result.review_reason] || 'Needs a person'
              : 'No mismatch detected'}
        </span>
      </div>

      {result.concerns?.map((concern) => (
        <div className="note uncertain" key={concern}>⚠ {concern}</div>
      ))}
      {result.provenance?.map((note) => (
        <div className="note info" key={note}>{note}</div>
      ))}

      {(result.si_source || result.bl_source) && (
        <div className="card">
          <h4>Documents</h4>
          <div>Shipping instruction — {result.si_source || 'not attached'}</div>
          <div>Bill of lading — {result.bl_source || 'not attached'}</div>
        </div>
      )}

      <Fields fields={result.fields} />

      {result.category === 'BL_COMPARISON' && result.status !== 'OK' && (
        <Resolve result={result} onDone={onChanged} onError={onError} />
      )}

      {reviewCase?.audit?.length > 0 && (
        <div className="card">
          <h4>History</h4>
          <pre className="log">
            {reviewCase.audit
              .map((e) => `${e.at}  ${e.by}  ${e.action}  ${e.detail}`)
              .join('\n')}
          </pre>
        </div>
      )}
    </div>
  )
}
