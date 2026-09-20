import { useCallback, useEffect, useState } from 'react'

export type Theme = 'light' | 'dark' | 'system'

const KEY = 'vsmail.theme'

const read = (): Theme => {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    // Private windows and blocked site data throw on access rather than
    // returning empty. Following the machine is the right default anyway.
    return 'system'
  }
}

/**
 * Light, dark, or whatever the machine says.
 *
 * `data-theme` is stamped on <html> rather than <body> so the pre-paint
 * script in index.html can set it before React exists — otherwise a dark
 * user gets a white flash on every load.
 *
 * The transition is switched on for a moment and then off again. Leaving a
 * transition on every colour property permanently would tax every ordinary
 * hover in the app to make one rare event smooth.
 */
export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(read)

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', theme)
    try {
      if (theme === 'system') localStorage.removeItem(KEY)
      else localStorage.setItem(KEY, theme)
    } catch {
      // Nothing to do; the theme still applies for this session.
    }
  }, [theme])

  const setTheme = useCallback((next: Theme) => {
    document.body.classList.add('theme-anim')
    window.setTimeout(() => document.body.classList.remove('theme-anim'), 360)
    setThemeState(next)
  }, [])

  const resolved: 'light' | 'dark' =
    theme === 'system'
      ? window.matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light'
      : theme

  return { theme, resolved, setTheme }
}
