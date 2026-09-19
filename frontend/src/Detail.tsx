import { useState } from 'react'
import { api, type Case, type FieldRow, type Result } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { FIELD_LABELS, REVIEW_REASONS, TONE_CLASS, statusTone } from './format'

const FIELDS = Object.keys(FIELD_LABELS)

// The comparison table is the whole point of the product, so it shows what
// each document said *and* why two differently written values were accepted.
// Proving the absence of a false alarm is otherwise invisible: nobody notices
// a defect that was correctly not raised.
function Fields({ fields }: { fields: FieldRow[] }) {
  if (!fields?.length) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">The seven fields</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-40">Field</TableHead>
              <TableHead>Shipping instruction</TableHead>
              <TableHead>Draft bill of lading</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {fields.map((f) => (
              <TableRow
                key={f.field}
                className={!f.equal ? 'bg-defect-bg hover:bg-defect-bg' : undefined}
              >
                <TableCell
                  className={
                    !f.equal ? 'font-semibold text-defect' : 'text-muted-foreground'
                  }
                >
                  {FIELD_LABELS[f.field] || f.field}
                </TableCell>
                <TableCell className="whitespace-normal">
                  {f.si ?? <em className="text-muted-foreground">blank</em>}
                </TableCell>
                <TableCell className="whitespace-normal">
                  {f.bl ?? <em className="text-muted-foreground">blank</em>}
                  {f.equal && f.note && (
                    <span className="mt-1 block text-xs text-clean">✓ {f.note}</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

// Resolving supplies a value; it never writes a verdict. The comparison runs
// again over what the reviewer typed, so a wrong value produces a mismatch
// rather than a rubber stamp.
function Resolve({
  result,
  onDone,
  onError,
}: {
  result: Result
  onDone: () => void
  onError: (message: string) => void
}) {
  const [side, setSide] = useState<'si' | 'bl'>('si')
  const [field, setField] = useState(result.defect_fields?.[0] || 'gross_weight_kg')
  const [value, setValue] = useState('')
  const [saving, setSaving] = useState(false)

  const submit = async (payload: unknown) => {
    setSaving(true)
    try {
      await api.resolve(result.email_id, payload)
      setValue('')
      onDone()
    } catch (error) {
      onError((error as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const select =
    'h-9 rounded-md border bg-background px-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50'

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Resolve</CardTitle>
        <p className="text-sm text-muted-foreground">
          Supply the correct value and the comparison runs again over it. The
          verdict is never written by hand.
        </p>
      </CardHeader>
      <CardContent className="flex flex-wrap items-center gap-2">
        <select
          className={select}
          value={side}
          onChange={(e) => setSide(e.target.value as 'si' | 'bl')}
        >
          <option value="si">Shipping instruction</option>
          <option value="bl">Bill of lading</option>
        </select>
        <select
          className={select}
          value={field}
          onChange={(e) => setField(e.target.value)}
        >
          {FIELDS.map((f) => (
            <option key={f} value={f}>
              {FIELD_LABELS[f]}
            </option>
          ))}
        </select>
        <input
          className={`${select} min-w-56 flex-1`}
          placeholder="The correct value"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <Button
          size="sm"
          disabled={!value.trim()}
          loading={saving}
          onClick={() =>
            submit({ by: 'reviewer', [side]: { [field]: value.trim() } })
          }
        >
          Supply
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={saving}
          title="The escalation was right and there is nothing to fix"
          onClick={() => submit({ by: 'reviewer', confirm: true })}
        >
          Confirm as-is
        </Button>
      </CardContent>
    </Card>
  )
}

export default function Detail({
  email,
  onChanged,
  onError,
}: {
  email: { result: Result; case: Case | null } | null
  onChanged: () => void
  onError: (message: string) => void
}) {
  if (!email) {
    return (
      <div className="grid place-items-center p-10 text-sm text-muted-foreground">
        Choose an email to see what was found.
      </div>
    )
  }

  const { result, case: reviewCase } = email
  const tone = statusTone(result)
  const summary =
    result.status === 'MISMATCH'
      ? `${result.defect_fields.length} field${result.defect_fields.length === 1 ? '' : 's'} differ`
      : result.status === 'NEEDS_REVIEW'
        ? REVIEW_REASONS[result.review_reason ?? ''] || 'Needs a person'
        : 'No mismatch detected'

  return (
    <div className="flex flex-col gap-4 overflow-y-auto p-5">
      <div>
        <h2 className="text-lg font-semibold">{result.subject || '(no subject)'}</h2>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <span>{result.sender || 'unknown sender'}</span>
          <span>·</span>
          <span>{result.email_id}</span>
          <Badge className={TONE_CLASS[tone]}>{summary}</Badge>
        </div>
      </div>

      {result.concerns?.map((concern) => (
        <div
          key={concern}
          className="rounded-md bg-uncertain-bg px-3 py-2 text-sm text-uncertain"
        >
          ⚠ {concern}
        </div>
      ))}
      {result.provenance?.map((note) => (
        <div key={note} className="rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
          {note}
        </div>
      ))}

      {(result.si_source || result.bl_source) && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Documents</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm text-muted-foreground">
            <div>Shipping instruction — {result.si_source || 'not attached'}</div>
            <div>Bill of lading — {result.bl_source || 'not attached'}</div>
          </CardContent>
        </Card>
      )}

      <Fields fields={result.fields} />

      {result.category === 'BL_COMPARISON' && result.status !== 'OK' && (
        <Resolve result={result} onDone={onChanged} onError={onError} />
      )}

      {reviewCase?.audit && reviewCase.audit.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">History</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs leading-relaxed text-muted-foreground">
              {reviewCase.audit
                .map((e) => `${e.at}  ${e.by}  ${e.action}  ${e.detail}`)
                .join('\n')}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
