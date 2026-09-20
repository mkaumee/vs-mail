import { type FieldRow } from '@/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { FIELD_LABELS } from '@/format'

// The comparison table is the whole point of the product, so it shows what
// each document said *and* why two differently written values were accepted.
// Proving the absence of a false alarm is otherwise invisible: nobody notices
// a defect that was correctly not raised.
export default function Fields({ fields }: { fields: FieldRow[] }) {
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
