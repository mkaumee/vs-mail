import { useState } from 'react'
import { api, type Case, type Result } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import Fields from '@/components/Fields'
import ReplyCard from '@/components/ReplyCard'
import { FIELD_LABELS, REVIEW_REASONS, TONE_CLASS, statusTone } from './format'

const FIELDS = Object.keys(FIELD_LABELS)

// Resolving supplies a value; it never writes a verdict. The comparison runs
// again over what the reviewer typed, so a wrong value produces a mismatch
// rather than a rubber stamp.
export function HumanReview({
  result,
  onDone,
  onError,
}: {
  result: Result
  onDone: () => void
  onError: (message: string) => void
}) {
  const [side, setSide] = useState<'si' | 'bl'>('si')
  const [field, setField] = useState(
    result.defect_fields?.[0] ||
      result.fields.find((item) => item.uncertain || !item.si || !item.bl)?.field ||
      'gross_weight_kg',
  )
  const [value, setValue] = useState('')
  const [saving, setSaving] = useState(false)

  const submit = async (payload: unknown) => {
    setSaving(true)
    try {
      await api.resolve(result.email_id, payload)
      // A supplied value has to run through the comparator. Confirming the
      // escalation only acknowledges it, so another paid model pass would
      // add latency without changing the evidence.
      if (!(payload as { confirm?: boolean }).confirm) {
        await api.recheck(result.email_id)
      }
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
        <CardTitle className="text-sm">Human review</CardTitle>
        <p className="text-sm text-muted-foreground">
          {result.category === 'BL_COMPARISON'
            ? 'Supply a value for the system to compare again, or confirm that the escalation was correct.'
            : 'Confirm that this email was correctly escalated for a person.'}
        </p>
      </CardHeader>
      <CardContent className="flex flex-wrap items-center gap-2">
        {result.category === 'BL_COMPARISON' && (
          <>
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
          </>
        )}
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
  // An email a reviewer has already touched keeps its Resolve card even once
  // it reads OK. Otherwise a value typed wrongly — one that happens to
  // compare equal — is unreachable: the card that would let you fix it is
  // hidden by the very outcome the mistake produced.
  const corrected = Boolean(
    reviewCase &&
      (Object.keys(reviewCase.corrections?.si ?? {}).length ||
        Object.keys(reviewCase.corrections?.bl ?? {}).length),
  )
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

      {result.category === 'BL_COMPARISON' &&
        (result.status !== 'OK' || corrected) && (
          <HumanReview
            key={result.email_id}
            result={result}
            onDone={onChanged}
            onError={onError}
          />
        )}

      <ReplyCard
        emailId={result.email_id}
        version={`${result.status}:${result.defect_fields.join(',')}:${result.provenance.length}`}
        sentAt={result.sent_at}
        onError={onError}
      />

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
