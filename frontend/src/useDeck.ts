import { useCallback, useEffect, useRef, useState } from 'react'
import type { IncomingEmail, ReplyResponse } from './api'

export type Entry<T> =
  | { state: 'pending' }
  | { state: 'ready'; value: T }
  | { state: 'error'; message: string }

export type ReplyEntry = Entry<ReplyResponse>
export type EmailEntry = Entry<IncomingEmail>

/**
 * A deck of emails, generating one ahead.
 *
 * A reply for an answered lane costs a retrieval and a model call — seconds.
 * Generating all 129 up front is slow and mostly wasted, since nobody opens
 * them all. Generating only what is on screen puts that wait in front of
 * every advance.
 *
 * So: the current one and the next one, then stop. By the time you move on,
 * the next is already there and the one after it starts. The wait happens
 * once, at the start, and is invisible from then on.
 *
 * `lookahead` is deliberately fixed at one. Two would double the wasted work
 * for a reader who stops after the first, and the latency it hides is already
 * hidden.
 */
export const LOOKAHEAD = 1

/**
 * The window, for one kind of thing.
 *
 * Two things are prefetched per email — the reply and the email itself — and
 * they must obey the same window or the lookahead stops meaning anything.
 * Sharing this rather than writing the effect twice is what guarantees that.
 */
function usePrefetch<T>(
  laneKey: string,
  ids: React.MutableRefObject<string[]>,
  index: number,
  fetcher: (id: string) => Promise<T>,
) {
  const [cache, setCache] = useState<Record<string, Entry<T>>>({})
  // Bumped to make the effect look again after a retry, which otherwise
  // changes nothing the effect depends on.
  const [nonce, setNonce] = useState(0)

  // Which ids have been asked for. A ref rather than state so the effect does
  // not depend on the cache it writes to — that would re-run on every arrival
  // and the guard would be doing all the work.
  const requested = useRef<Set<string>>(new Set())
  const live = useRef(true)

  useEffect(() => {
    live.current = true
    return () => {
      live.current = false
    }
  }, [])

  useEffect(() => {
    const wanted = ids.current.slice(index, index + 1 + LOOKAHEAD)
    for (const id of wanted) {
      if (!id || requested.current.has(id)) continue
      requested.current.add(id)
      setCache((c) => ({ ...c, [id]: { state: 'pending' } }))
      fetcher(id)
        .then((value) => {
          // A response that arrives after the reader has moved on is still
          // kept. It is not wasted, just not on screen.
          if (live.current) setCache((c) => ({ ...c, [id]: { state: 'ready', value } }))
        })
        .catch((error: Error) => {
          if (live.current) {
            setCache((c) => ({ ...c, [id]: { state: 'error', message: error.message } }))
          }
          // Let a retry ask again.
          requested.current.delete(id)
        })
    }
  }, [laneKey, index, nonce, fetcher, ids])

  const retry = useCallback((id: string) => {
    requested.current.delete(id)
    setCache((c) => {
      const next = { ...c }
      delete next[id]
      return next
    })
    setNonce((n) => n + 1)
  }, [])

  const forget = useCallback((id: string) => {
    requested.current.delete(id)
    setCache((c) => {
      const next = { ...c }
      delete next[id]
      return next
    })
  }, [])

  return { cache, retry, forget }
}

export function useDeck(
  laneKey: string,
  order: string[],
  fetchReply: (id: string) => Promise<ReplyResponse>,
  fetchEmail: (id: string) => Promise<IncomingEmail>,
) {
  const [index, setIndex] = useState(0)
  const ids = useRef<string[]>(order)
  ids.current = order

  // Lane changed. Start at the top; keep the caches, because coming back to a
  // lane should not regenerate what was already paid for. Keyed on the lane
  // name rather than the array, which is a fresh reference every render.
  useEffect(() => {
    setIndex(0)
  }, [laneKey])

  const replies = usePrefetch<ReplyResponse>(laneKey, ids, index, fetchReply)
  // The same window, but a file read rather than a model call — so it lands
  // first and the email is on screen while its reply is still being drafted,
  // which is the order you would want to read them in anyway.
  const emails = usePrefetch<IncomingEmail>(laneKey, ids, index, fetchEmail)

  const go = useCallback(
    (delta: number) =>
      setIndex((i) => Math.min(Math.max(i + delta, 0), Math.max(ids.current.length - 1, 0))),
    [],
  )

  const current = order[index]
  return {
    index,
    go,
    current,
    total: order.length,
    entry: current ? replies.cache[current] : undefined,
    email: current ? emails.cache[current] : undefined,
    retry: replies.retry,
    retryEmail: emails.retry,
    /** Drop a cached reply so the next pass asks for it again. */
    forgetReply: replies.forget,
    cache: replies.cache,
  }
}
