import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReplyResponse } from './api'

export type Entry =
  | { state: 'pending' }
  | { state: 'ready'; reply: ReplyResponse }
  | { state: 'error'; message: string }

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

export function useDeck(
  laneKey: string,
  order: string[],
  fetchReply: (id: string) => Promise<ReplyResponse>,
) {
  const [index, setIndex] = useState(0)
  const [cache, setCache] = useState<Record<string, Entry>>({})
  // Bumped to make the effect look again after a retry, which otherwise
  // changes nothing the effect depends on.
  const [nonce, setNonce] = useState(0)

  // Which ids have been asked for. A ref rather than state so the effect does
  // not depend on the cache it writes to — that would re-run on every arrival
  // and the guard would be doing all the work.
  const requested = useRef<Set<string>>(new Set())
  const live = useRef(true)
  const ids = useRef<string[]>(order)
  ids.current = order

  useEffect(() => {
    live.current = true
    return () => {
      live.current = false
    }
  }, [])

  // Lane changed. Start at the top; keep the cache, because coming back to a
  // lane should not regenerate what was already paid for. Keyed on the lane
  // name rather than the array, which is a fresh reference every render.
  useEffect(() => {
    setIndex(0)
  }, [laneKey])

  useEffect(() => {
    const wanted = ids.current.slice(index, index + 1 + LOOKAHEAD)
    for (const id of wanted) {
      if (!id || requested.current.has(id)) continue
      requested.current.add(id)
      setCache((c) => ({ ...c, [id]: { state: 'pending' } }))
      fetchReply(id)
        .then((reply) => {
          // A response that arrives after the reader has moved on is still
          // kept. It is not wasted, just not on screen.
          if (live.current) setCache((c) => ({ ...c, [id]: { state: 'ready', reply } }))
        })
        .catch((error: Error) => {
          if (live.current) {
            setCache((c) => ({ ...c, [id]: { state: 'error', message: error.message } }))
          }
          // Let a retry ask again.
          requested.current.delete(id)
        })
    }
  }, [laneKey, index, nonce, fetchReply])

  const retry = useCallback((id: string) => {
    requested.current.delete(id)
    setCache((c) => {
      const next = { ...c }
      delete next[id]
      return next
    })
    setNonce((n) => n + 1)
  }, [])

  const go = useCallback(
    (delta: number) =>
      setIndex((i) => Math.min(Math.max(i + delta, 0), Math.max(ids.current.length - 1, 0))),
    [],
  )

  const current = order[index]
  return {
    index,
    go,
    retry,
    current,
    entry: current ? cache[current] : undefined,
    cache,
    total: order.length,
  }
}
