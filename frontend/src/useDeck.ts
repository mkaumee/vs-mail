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
  /**
   * The ids in view order. Must be stable between renders — memoise it — or
   * this asks again on every render.
   *
   * It is the array itself rather than a ref, and that is the whole point:
   * the deck now mounts before the inbox has loaded, so the first run sees
   * an empty list. A ref never changes identity, so the effect would not run
   * again when the rows arrived and nothing was ever fetched.
   */
  order: string[],
  /** Cache identity for each id. Replies include the verdict version. */
  keys: string[],
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
  // A retry can overlap the request it replaced. Only the newest response is
  // allowed to write the cache, otherwise a late old response wins at random.
  const generations = useRef<Map<string, number>>(new Map())
  const live = useRef(true)

  useEffect(() => {
    live.current = true
    return () => {
      live.current = false
    }
  }, [])

  useEffect(() => {
    const end = Math.min(order.length, index + 1 + LOOKAHEAD)
    for (let position = index; position < end; position += 1) {
      const id = order[position]
      const key = keys[position] ?? id
      if (!id || requested.current.has(key)) continue
      requested.current.add(key)
      const generation = (generations.current.get(key) ?? 0) + 1
      generations.current.set(key, generation)
      setCache((c) => ({ ...c, [key]: { state: 'pending' } }))
      fetcher(id)
        .then((value) => {
          // A response that arrives after the reader has moved on is still
          // kept. It is not wasted, just not on screen.
          if (live.current && generations.current.get(key) === generation) {
            setCache((c) => ({ ...c, [key]: { state: 'ready', value } }))
          }
        })
        .catch((error: Error) => {
          if (live.current && generations.current.get(key) === generation) {
            setCache((c) => ({ ...c, [key]: { state: 'error', message: error.message } }))
            // Let a retry ask again, but never unlock a newer in-flight request.
            requested.current.delete(key)
          }
        })
    }
  }, [laneKey, index, nonce, fetcher, keys, order])

  const retry = useCallback((key: string) => {
    requested.current.delete(key)
    generations.current.set(key, (generations.current.get(key) ?? 0) + 1)
    setCache((c) => {
      const next = { ...c }
      delete next[key]
      return next
    })
    setNonce((n) => n + 1)
  }, [])

  const forget = useCallback((key: string) => {
    requested.current.delete(key)
    generations.current.set(key, (generations.current.get(key) ?? 0) + 1)
    setCache((c) => {
      const next = { ...c }
      delete next[key]
      return next
    })
  }, [])

  return { cache, retry, forget }
}

export function useDeck(
  laneKey: string,
  order: string[],
  replyKeys: string[],
  fetchReply: (id: string) => Promise<ReplyResponse>,
  fetchEmail: (id: string) => Promise<IncomingEmail>,
) {
  const [index, setIndex] = useState(0)
  const ids = useRef<string[]>(order)
  ids.current = order
  const activeId = useRef<string | undefined>(undefined)
  const activeLane = useRef(laneKey)

  const laneChanged = activeLane.current !== laneKey
  if (laneChanged) {
    activeLane.current = laneKey
    activeId.current = undefined
  }

  // Lane changed. Start at the top; keep the caches, because coming back to a
  // lane should not regenerate what was already paid for. Keyed on the lane
  // name rather than the array, which is a fresh reference every render.
  useEffect(() => {
    setIndex(0)
  }, [laneKey])

  const maximum = Math.max(order.length - 1, 0)
  const stillHere = activeId.current ? order.indexOf(activeId.current) : -1
  const safeIndex = laneChanged ? 0 : stillHere >= 0 ? stillHere : Math.min(index, maximum)

  // Sending/removing the last item shrinks the lane. Keep rendering the new
  // last item immediately instead of returning a blank frame for one render.
  useEffect(() => {
    setIndex(safeIndex)
  }, [safeIndex])

  const replies = usePrefetch<ReplyResponse>(
    laneKey,
    order,
    replyKeys,
    safeIndex,
    fetchReply,
  )
  // The same window, but a file read rather than a model call — so it lands
  // first and the email is on screen while its reply is still being drafted,
  // which is the order you would want to read them in anyway.
  const emails = usePrefetch<IncomingEmail>(laneKey, order, order, safeIndex, fetchEmail)

  const go = useCallback(
    (delta: number) => {
      setIndex((i) => {
        const last = Math.max(ids.current.length - 1, 0)
        const current = activeId.current
          ? ids.current.indexOf(activeId.current)
          : Math.min(i, last)
        const target = Math.min(Math.max(Math.max(current, 0) + delta, 0), last)
        activeId.current = ids.current[target]
        return target
      })
    },
    [],
  )

  const current = order[safeIndex]
  activeId.current = current
  const replyKey = replyKeys[safeIndex]
  return {
    index: safeIndex,
    go,
    current,
    total: order.length,
    entry: replyKey ? replies.cache[replyKey] : undefined,
    email: current ? emails.cache[current] : undefined,
    retry: () => replyKey && replies.retry(replyKey),
    retryEmail: () => current && emails.retry(current),
    /** Drop a cached reply so the next pass asks for it again. */
    forgetReply: () => replyKey && replies.forget(replyKey),
    cache: replies.cache,
  }
}
