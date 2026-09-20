import { useState } from 'react'
import { motion } from 'motion/react'
import { Monitor, Moon, Palette, Plug, Sun } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { GmailStatus } from '@/api'
import { Button } from '@/components/ui/button'
import { getTestRecipient } from '@/components/ReplyComposer'
import { useTheme, type Theme } from '@/useTheme'

const SECTIONS: { id: string; label: string; icon: LucideIcon }[] = [
  { id: 'appearance', label: 'Appearance', icon: Palette },
  { id: 'gmail', label: 'Gmail', icon: Plug },
]

/**
 * A miniature of the app in that mode.
 *
 * The swatch colours are literal rather than themed on purpose: the whole
 * point is to show what dark looks like while you are sitting in light.
 */
function ThemeCard({
  mode,
  label,
  icon: Icon,
  on,
  onPick,
}: {
  mode: Theme
  label: string
  icon: LucideIcon
  on: boolean
  onPick: () => void
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={on}
      className={`theme-card${on ? ' is-on' : ''}`}
      onClick={onPick}
    >
      <span className={`theme-card__swatch theme-card__swatch--${mode}`} aria-hidden>
        <i /><i /><i />
      </span>
      <span className="theme-card__label">
        <Icon className="size-[15px]" />
        {label}
      </span>
    </button>
  )
}

export default function SettingsPage({
  gmail,
  onManageGmail,
}: {
  gmail: GmailStatus | null
  onManageGmail: () => void
}) {
  const [section, setSection] = useState('appearance')
  const { theme, setTheme } = useTheme()
  const testTo = getTestRecipient()
  const current = SECTIONS.find((s) => s.id === section) ?? SECTIONS[0]

  const connection = !gmail
    ? '—'
    : gmail.ready
      ? 'Connected'
      : gmail.expired
        ? 'Authorisation expired'
        : gmail.credentials_present
          ? 'Not connected'
          : 'Not set up'

  return (
    <motion.div
      className="settings"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, ease: [0.2, 0.8, 0.2, 1] }}
    >
      <nav className="settings__nav" aria-label="Settings sections">
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            type="button"
            className={`settings__link${s.id === current.id ? ' is-on' : ''}`}
            aria-current={s.id === current.id ? 'page' : undefined}
            onClick={() => setSection(s.id)}
          >
            <s.icon className="size-4" />
            {s.label}
          </button>
        ))}
      </nav>

      <section className="panel glass-2 settings__body">
        <h2 className="h2">{current.label}</h2>

        {current.id === 'appearance' && (
          <div>
            <div className="label">Theme</div>
            <div className="theme-grid" role="radiogroup" aria-label="Theme">
              <ThemeCard mode="light" label="Light" icon={Sun} on={theme === 'light'} onPick={() => setTheme('light')} />
              <ThemeCard mode="dark" label="Dark" icon={Moon} on={theme === 'dark'} onPick={() => setTheme('dark')} />
              <ThemeCard mode="system" label="System" icon={Monitor} on={theme === 'system'} onPick={() => setTheme('system')} />
            </div>
            <p className="hint mt-3">
              System follows your device and changes with it. The choice is kept in
              this browser only.
            </p>
          </div>
        )}

        {current.id === 'gmail' && (
          <>
            <dl className="kv">
              <div>
                <dt>Connection</dt>
                <dd>
                  <span
                    className={`dot${gmail?.ready ? ' dot--ok' : gmail?.expired ? ' dot--warn' : ''}`}
                    aria-hidden
                  />
                  {connection}
                </dd>
              </div>
              <div>
                <dt>Mailbox</dt>
                <dd className="mono">{gmail?.mailbox ?? '—'}</dd>
              </div>
              <div>
                <dt>OAuth client</dt>
                <dd>
                  {gmail?.credentials_source
                    ? `From the ${gmail.credentials_source}`
                    : 'Not found'}
                </dd>
              </div>
              <div>
                <dt>Token</dt>
                <dd>
                  {gmail?.token_source ? `In the ${gmail.token_source}` : 'None stored'}
                </dd>
              </div>
              <div>
                <dt>Test recipient</dt>
                <dd>{testTo || 'Not set. Sending is refused until there is one'}</dd>
              </div>
            </dl>
            <div>
              <Button variant="outline" onClick={onManageGmail}>
                <Plug />
                Manage Gmail connection
              </Button>
            </div>
            <p className="muted small">
              Signing in and connecting a mailbox are separate. Credentials live on the
              server and are never shown here.
            </p>
          </>
        )}
      </section>
    </motion.div>
  )
}
