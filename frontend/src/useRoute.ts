import { useEffect, useState } from 'react'

export type View = 'lanes' | 'settings' | 'gmail'

const read = (): View => {
  const h = window.location.hash.replace(/^#\/?/, '').split('/')[0]
  return h === 'settings' || h === 'gmail' ? h : 'lanes'
}

/**
 * Which screen. In the hash rather than in state, for two reasons: a reload
 * keeps you where you were, and the Gmail consent flow leaves the app
 * entirely and has to land back on the page that started it.
 *
 * A hash rather than a path because the server serves one page and the OAuth
 * callback already owns the query string.
 */
export function useRoute() {
  const [view, setView] = useState<View>(read)

  useEffect(() => {
    const onHash = () => setView(read())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const go = (next: View) => {
    window.location.hash = next === 'lanes' ? '' : `/${next}`
    setView(next)
  }

  return { view, go }
}
