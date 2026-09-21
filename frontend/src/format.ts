import type { Result } from './api'

export const CATEGORY_LABELS: Record<string, string> = {
  BL_COMPARISON: 'Document checks',
  SI_REQUEST: 'Draft requests',
  INVOICE_QUERY: 'Invoice queries',
  HELP: 'Help',
  GENERAL: 'General',
  SPAM: 'Spam',
  // Replied to. Out of the queue, kept for looking back at.
  READ: 'Read',
}

// What a wrong value actually costs. Consignee and notify party carry legal
// title to the cargo; gross weight is a SOLAS declaration.
export const FIELD_LABELS: Record<string, string> = {
  shipper: 'Shipper',
  consignee: 'Consignee',
  notify_party: 'Notify party',
  port_of_loading: 'Port of loading',
  port_of_discharge: 'Port of discharge',
  container_count: 'Containers',
  gross_weight_kg: 'Gross weight',
}

export const REVIEW_REASONS: Record<string, string> = {
  wrong_doc_type: 'Wrong document attached',
  missing_attachment: 'Attachment missing',
  unreadable: 'File will not open',
  missing_value: 'A required value is blank',
}

export type Tone = 'defect' | 'review' | 'uncertain' | 'clean'

export const statusTone = (result: Pick<Result, 'status' | 'concerns'>): Tone => {
  if (result.status === 'MISMATCH') return 'defect'
  if (result.status === 'NEEDS_REVIEW') return 'review'
  if (result.concerns?.length) return 'uncertain'
  return 'clean'
}

// Four meanings, four colours. Collapsing them into shadcn's destructive and
// secondary would lose the distinction between "this is wrong", "a person has
// to look", "the model was unsure" and "this is fine".
export const TONE_CLASS: Record<Tone, string> = {
  defect: 'bg-defect-bg text-defect',
  review: 'bg-review-bg text-review',
  uncertain: 'bg-uncertain-bg text-uncertain',
  clean: 'bg-clean-bg text-clean',
}

export const relative = (iso: string | null): string => {
  if (!iso) return 'never'
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`
  return `${Math.floor(seconds / 86400)} d ago`
}


/**
 * "Good morning" / "Good afternoon" / "Good evening".
 *
 * Local to the browser, deliberately: the person reading the screen is the
 * one whose time of day matters, not the server's.
 */
export function greeting(now = new Date()): string {
  const h = now.getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

/**
 * The name to greet, or nothing.
 *
 * Empty when signing in with a service token rather than Google, which has
 * no name behind it. "Good evening, there" is worse than "Good evening".
 */
export function firstName(me: { name?: string; email?: string } | null): string {
  if (!me) return ''
  const given = (me.name || '').trim().split(/\s+/)[0]
  if (given) return given
  const local = (me.email || '').split('@')[0]
  return local ? local.charAt(0).toUpperCase() + local.slice(1) : ''
}

/** Two letters for the avatar. */
export function initials(me: { name?: string; email?: string } | null): string {
  if (!me) return '?'
  const parts = (me.name || '').trim().split(/\s+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (me.email || '?').slice(0, 2).toUpperCase()
}
