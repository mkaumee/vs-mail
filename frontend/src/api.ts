// Every guarded route needs the shared secret. The token is kept in
// localStorage rather than embedded, so the built app carries no credential
// and a demo machine can be handed a different one.
const TOKEN_KEY = 'vsmail.token'

export const getToken = (): string => localStorage.getItem(TOKEN_KEY) || ''
export const setToken = (value: string): void =>
  localStorage.setItem(TOKEN_KEY, value.trim())

export type FieldRow = {
  field: string
  si: string | null
  bl: string | null
  equal: boolean
  /** Why two differently written values were accepted. The product. */
  note?: string | null
  uncertain?: boolean
}

export type Result = {
  email_id: string
  category: string
  status: 'OK' | 'MISMATCH' | 'NEEDS_REVIEW'
  review_reason: string | null
  has_defect: boolean
  defect_fields: string[]
  subject: string
  sender: string
  confidence: number
  concerns: string[]
  provenance: string[]
  fields: FieldRow[]
  si_source: string | null
  bl_source: string | null
}

export type Audit = { at: string; by: string; action: string; detail: string }

export type Case = {
  state: string
  reason: string
  corrections: Record<string, Record<string, string>>
  audit: Audit[]
}

export type Stats = {
  total: number
  defects_found: number
  awaiting_review: number
  minutes_saved: number
  ran_at: string | null
  source: string
  by_category: Record<string, number>
}

export type Inbox = { stats: Stats; lanes: Record<string, Result[]> }

export type Job = {
  id: string
  kind: string
  state: 'running' | 'done' | 'failed'
  done: number
  total: number
  message: string
  error?: string
}

/**
 * Gmail's four states, which the page has to tell apart.
 *
 * `credentials_source` is what separates "nothing was ever set" from "something
 * was set and cannot be used" — without it a mangled paste and an empty
 * variable look identical, and the operator has no idea which value to go and
 * look at. `expired` is the seven-day token running out, which is routine
 * rather than a fault and gets an invitation to reconnect, not setup
 * instructions.
 */
export type GmailStatus = {
  credentials_present: boolean
  credentials_source: 'environment' | 'file' | null
  authorised: boolean
  token_source: 'environment' | 'file' | null
  ready: boolean
  expired: boolean
  mailbox: string | null
  error?: string
}

async function call<T>(
  path: string,
  { method = 'GET', body }: { method?: string; body?: unknown } = {},
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: {
      'X-VS-Token': getToken(),
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  if (response.status === 401) throw new Error('The service token was rejected.')
  const failed = async (fallback: string) => {
    const data = await response.json().catch(() => ({}) as { detail?: string })
    return new Error(data.detail || fallback)
  }
  if (response.status === 503) throw await failed('The service is not configured.')
  if (!response.ok) throw await failed(`${method} ${path} failed (${response.status})`)
  return response.json() as Promise<T>
}

export const api = {
  inbox: () => call<Inbox>('/inbox'),
  email: (id: string) => call<{ result: Result; case: Case | null }>(`/inbox/${id}`),
  startRun: (options: { source: string; provider: string; labels: boolean }) =>
    call<Job>('/jobs/run', { method: 'POST', body: options }),
  job: (id: string) => call<Job>(`/jobs/${id}`),
  gmailStatus: () => call<GmailStatus>('/gmail/status'),
  // Returns where to send the browser. The callback Google redirects to is
  // the one route with no token on it, so starting here is what authorises
  // the whole exchange.
  gmailAuthStart: () => call<{ authorization_url: string }>('/gmail/auth/start'),
  seed: (limit?: number) => call<Job>('/gmail/seed', { method: 'POST', body: { limit } }),
  resetGmail: () => call<Job>('/gmail/reset', { method: 'POST' }),
  watchStatus: () => call<{ watching: boolean }>('/watch/status'),
  startWatch: (options: { provider: string; interval: number }) =>
    call<Job>('/watch/start', { method: 'POST', body: options }),
  stopWatch: () => call<{ stopped: boolean }>('/watch/stop', { method: 'POST' }),
  resolve: (id: string, body: unknown) =>
    call<unknown>(`/review/${id}/resolve`, { method: 'POST', body }),
  // Resolving records a value; it does not write a verdict. Something has to
  // run the comparator over it, or the page keeps showing what the original
  // run stored and supplying a value looks like it did nothing.
  recheck: (id: string) =>
    call<{ result: Result }>(`/inbox/${id}/recheck`, { method: 'POST' }),
}
