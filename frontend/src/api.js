// Every guarded route needs the shared secret. The token is kept in
// localStorage rather than embedded, so the built app carries no credential
// and a demo machine can be handed a different one.
const TOKEN_KEY = 'vsmail.token'

export const getToken = () => localStorage.getItem(TOKEN_KEY) || ''
export const setToken = (value) => localStorage.setItem(TOKEN_KEY, value.trim())

async function call(path, { method = 'GET', body } = {}) {
  const response = await fetch(path, {
    method,
    headers: {
      'X-VS-Token': getToken(),
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  if (response.status === 401) throw new Error('The service token was rejected.')
  if (response.status === 503) {
    const { detail } = await response.json().catch(() => ({}))
    throw new Error(detail || 'The service is not configured.')
  }
  if (!response.ok) {
    const { detail } = await response.json().catch(() => ({}))
    throw new Error(detail || `${method} ${path} failed (${response.status})`)
  }
  return response.json()
}

export const api = {
  health: () => fetch('/health').then((r) => r.json()),
  inbox: () => call('/inbox'),
  email: (id) => call(`/inbox/${id}`),
  startRun: (options) => call('/jobs/run', { method: 'POST', body: options }),
  job: (id) => call(`/jobs/${id}`),
  gmailStatus: () => call('/gmail/status'),
  // Returns where to send the browser. The callback Google redirects to is
  // the one route with no token on it, so starting here is what authorises
  // the whole exchange.
  gmailAuthStart: () => call('/gmail/auth/start'),
  seed: (limit) => call('/gmail/seed', { method: 'POST', body: { limit } }),
  resetGmail: () => call('/gmail/reset', { method: 'POST' }),
  watchStatus: () => call('/watch/status'),
  startWatch: (options) => call('/watch/start', { method: 'POST', body: options }),
  stopWatch: () => call('/watch/stop', { method: 'POST' }),
  queue: () => call('/review'),
  case: (id) => call(`/review/${id}`),
  resolve: (id, body) => call(`/review/${id}/resolve`, { method: 'POST', body }),
}
