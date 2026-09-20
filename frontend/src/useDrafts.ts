import { useCallback, useState } from 'react'
import type { Draft } from './api'

export type Edit = { to: string; subject: string; body: string }
type Held = Edit & { version: string }

/**
 * Edits to drafted replies, held above the deck.
 *
 * The composer cannot hold these itself: moving to the next email and back
 * remounts it, and a reviewer who rewrote three sentences would find them
 * gone. So they live here, keyed by email id, and survive navigation within
 * the session.
 *
 * Each edit remembers the verdict it was written against. If a Resolve moves
 * that verdict, the edit is dropped rather than shown — a hand-edited email
 * still asking the customer to amend a field that now agrees is worse than
 * no draft at all, and it is one click from being sent.
 */
export function useDrafts() {
  const [edits, setEdits] = useState<Record<string, Held>>({})

  /** The values to show: the edit if it still applies, else the draft. */
  const valueFor = useCallback(
    (id: string, draft: Draft, version: string): Edit => {
      const held = edits[id]
      if (held && held.version === version) {
        return { to: held.to, subject: held.subject, body: held.body }
      }
      return { to: draft.to, subject: draft.subject, body: draft.body }
    },
    [edits],
  )

  const change = useCallback((id: string, version: string, next: Edit) => {
    setEdits((e) => ({ ...e, [id]: { ...next, version } }))
  }, [])

  const reset = useCallback((id: string) => {
    setEdits((e) => {
      const next = { ...e }
      delete next[id]
      return next
    })
  }, [])

  const isEdited = useCallback(
    (id: string, draft: Draft, version: string) => {
      const held = edits[id]
      if (!held || held.version !== version) return false
      return (
        held.to !== draft.to ||
        held.subject !== draft.subject ||
        held.body !== draft.body
      )
    },
    [edits],
  )

  return { valueFor, change, reset, isEdited }
}
