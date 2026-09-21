// Every guarded route needs the shared secret. The token is kept in
// localStorage rather than embedded, so the built app carries no credential
// and a demo machine can be handed a different one.
const TOKEN_KEY = 'vsmail.token'

export const getToken = (): string => localStorage.getItem(TOKEN_KEY) || ''
export const setToken = (value: string): void =>
  localStorage.setItem(TOKEN_KEY, value.trim())
export const clearToken = (): void => localStorage.removeItem(TOKEN_KEY)

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
  attachment_count: number
  /** When a reply actually went out. Set, and it lives in Read. */
  sent_at: string | null
}

export type Citation = {
  id: string
  heading: string
  source: string
  fabricated: boolean
}

export type Draft = {
  to: string
  subject: string
  body: string
  kind: string
  citations?: Citation[]
  /** Any cited material was invented for the demo. Shown, never hidden. */
  fabricated?: boolean
  /** What the material did not cover, stated rather than filled in. */
  missing?: string
}

/** No draft is a real outcome, and `why` is what a person acts on. */
export type ReplyResponse = { draft: Draft | null; why?: string }

/**
 * The email being replied to.
 *
 * Not stored on `Result` — read through the source, so there is one copy of
 * each body and it cannot go stale. `core_body` is the trimmed request the
 * classifier saw; `body` is the whole thing, for when the trim looks wrong.
 */
export type IncomingEmail = {
  email_id: string
  sender: string
  subject: string
  body: string
  core_body: string
  attachments: string[]
  documents: Array<{
    path: string
    name: string
    role: 'SI' | 'BL' | null
  }>
  si_source: string | null
  bl_source: string | null
}

export type DocumentPreview = {
  name: string
  role: 'SI' | 'BL'
  media_type: string
  mode: 'pdf' | 'image' | 'text' | 'download'
  text: string | null
  error: string | null
}

export type Me = { email: string; name: string; picture: string }

export type AuthStatus = {
  configured: boolean
  redirect_uri: string
  signed_in: boolean
  token_accepted: boolean
}

export type Disconnected = {
  revoked: boolean
  file_removed: boolean
  still_in_environment: boolean
}

export type Sent = {
  message_id: string
  sent_to: string
  diverted_from: string | null
  threaded: boolean
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
  state: 'running' | 'done' | 'failed' | 'stopped'
  done: number
  total: number
  message: string
  phase: string
  current_email?: string | null
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

/**
 * Told when the server says we are not signed in, so the app can show the
 * sign-in screen again.
 *
 * Without this a rejected credential was a dead end: `ready` was set once
 * from whether a token existed and never went back, so rotating
 * VS_SERVICE_TOKEN left the page rendering the shell with an error banner
 * and no way back short of clearing localStorage by hand.
 */
let onRejected: () => void = () => {}
export const whenRejected = (fn: () => void) => {
  onRejected = fn
}

export class NotSignedIn extends Error {}

async function call<T>(
  path: string,
  {
    method = 'GET',
    body,
    // A 401 from /auth/me is the answer to "am I signed in", not a failure —
    // firing the rejected handler on it would bounce a token-only browser to
    // the sign-in screen on every load.
    quiet401 = false,
  }: { method?: string; body?: unknown; quiet401?: boolean } = {},
): Promise<T> {
  const token = getToken()
  const response = await fetch(path, {
    method,
    // The session cookie is HttpOnly, so it only travels if we ask for it.
    credentials: 'include',
    headers: {
      // Still sent when one is held: scripts and a token-only browser both
      // remain valid ways in.
      ...(token ? { 'X-VS-Token': token } : {}),
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  if (response.status === 401) {
    if (!quiet401) onRejected()
    throw new NotSignedIn('Not signed in, or the service token was rejected.')
  }
  const failed = async (fallback: string) => {
    const data = await response.json().catch(() => ({}) as { detail?: string })
    return new Error(data.detail || fallback)
  }
  if (response.status === 503) throw await failed('The service is not configured.')
  if (!response.ok) throw await failed(`${method} ${path} failed (${response.status})`)
  return response.json() as Promise<T>
}

async function file(path: string): Promise<Blob> {
  const token = getToken()
  const response = await fetch(path, {
    credentials: 'include',
    headers: token ? { 'X-VS-Token': token } : {},
  })
  if (response.status === 401) {
    onRejected()
    throw new NotSignedIn('Not signed in, or the service token was rejected.')
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}) as { detail?: string })
    throw new Error(data.detail || `GET ${path} failed (${response.status})`)
  }
  return response.blob()
}

export const api = {
  inbox: () => call<Inbox>('/inbox'),
  // Signing in is separate from connecting a mailbox: one says who is using
  // this, the other says which mailbox it works on.
  me: () => call<Me>('/auth/me', { quiet401: true }),
  authStatus: () => call<AuthStatus>('/auth/status'),
  signInStart: () => call<{ authorization_url: string }>('/auth/login'),
  signOut: () => call<{ signed_out: boolean }>('/auth/logout', { method: 'POST' }),
  disconnectGmail: () =>
    call<Disconnected>('/gmail/disconnect', { method: 'POST' }),
  email: (id: string) => call<{ result: Result; case: Case | null }>(`/inbox/${id}`),
  startRun: (limit: number | null) =>
    call<Job>('/jobs/run', {
      method: 'POST',
      body: { source: 'gmail', labels: true, ...(limit === null ? {} : { limit }) },
    }),
  job: (id: string) => call<Job>(`/jobs/${id}`),
  // Work outlives the tab that started it, so a reloaded page adopts
  // whatever is still in flight rather than showing an idle screen.
  runningJobs: () => call<{ jobs: Job[] }>('/jobs/running'),
  gmailStatus: () => call<GmailStatus>('/gmail/status'),
  // Returns where to send the browser. The callback Google redirects to is
  // the one route with no token on it, so starting here is what authorises
  // the whole exchange.
  gmailAuthStart: () => call<{ authorization_url: string }>('/gmail/auth/start'),
  seed: () => call<Job>('/gmail/seed', { method: 'POST' }),
  watchStatus: () => call<{ watching: boolean; job: Job | null }>('/watch/status'),
  startWatch: () =>
    call<Job>('/watch/start', { method: 'POST', body: { interval: 10 } }),
  stopWatch: () => call<{ stopped: boolean }>('/watch/stop', { method: 'POST' }),
  resolve: (id: string, body: unknown) =>
    call<unknown>(`/review/${id}/resolve`, { method: 'POST', body }),
  // Resolving records a value; it does not write a verdict. Something has to
  // run the comparator over it, or the page keeps showing what the original
  // run stored and supplying a value looks like it did nothing.
  recheck: (id: string) =>
    call<{ result: Result }>(`/inbox/${id}/recheck`, { method: 'POST' }),
  reply: (id: string) => call<ReplyResponse>(`/inbox/${id}/reply`),
  // The email itself. A reply approved without reading what it answers is
  // not really approved.
  incoming: (id: string) => call<IncomingEmail>(`/inbox/${id}/email`),
  documentPreview: (id: string, role: 'SI' | 'BL') =>
    call<DocumentPreview>(`/inbox/${id}/documents/${role}/preview`),
  documentFile: (id: string, role: 'SI' | 'BL') =>
    file(`/inbox/${id}/documents/${role}`),
  replyIntoGmail: (id: string, body: { to: string; subject: string; body: string }) =>
    call<{ draft: Draft; threaded: boolean }>(`/inbox/${id}/reply/gmail`, {
      method: 'POST',
      body,
    }),
  // The words on screen are what goes out, not the ones we composed. Where
  // it goes is decided by the server, which refuses without a test address.
  sendReply: (
    id: string,
    body: { to: string; subject: string; body: string; test_recipient?: string; allow_real?: boolean },
  ) => call<Sent>(`/inbox/${id}/reply/send`, { method: 'POST', body }),
}
