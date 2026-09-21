import { motion } from 'motion/react'
import { LogOut } from 'lucide-react'
import type { GmailStatus, Me } from '@/api'
import { Button } from '@/components/ui/button'
import ThemeSwitcher from '@/components/ThemeSwitcher'
import { initials } from '@/format'

/** Connected, expired, or not set up — one dot and three words. */
function gmailChip(gmail: GmailStatus | null) {
  if (!gmail) return { tone: '', text: 'Gmail' }
  if (gmail.ready) return { tone: 'chip--ok', text: gmail.mailbox ?? 'Gmail connected' }
  if (gmail.expired) return { tone: 'chip--warn', text: 'Gmail expired' }
  return { tone: '', text: 'Gmail not connected' }
}

export default function TopBar({
  title,
  crumb,
  gmail,
  me,
  onGmail,
  onSignOut,
}: {
  title: string
  crumb: string
  gmail: GmailStatus | null
  me: Me | null
  onGmail: () => void
  onSignOut: () => void
}) {
  const chip = gmailChip(gmail)

  return (
    <header className="topbar glass-2">
      <div className="min-w-0">
        <h1 className="topbar__h truncate">{title}</h1>
        <div className="crumbs">
          <span>VS-Mail</span>
          <span>›</span>
          <span className="truncate">{crumb}</span>
        </div>
      </div>

      <div className="topbar__actions">
        {/* The state, and the way to do something about it. */}
        <motion.button
          type="button"
          className={`chip glass-4 ${chip.tone}`}
          title={`${chip.text} — manage`}
          onClick={onGmail}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          transition={{ type: 'spring', stiffness: 420, damping: 26 }}
        >
          <span className="chip__dot" />
          <span className="hidden max-w-44 truncate lg:inline">{chip.text}</span>
        </motion.button>

        <ThemeSwitcher />

        {me && (
          <motion.span
            className="avatar"
            title={me.email}
            whileHover={{ scale: 1.06 }}
            transition={{ type: 'spring', stiffness: 420, damping: 26 }}
          >
            {initials(me)}
          </motion.span>
        )}

        <Button size="sm" variant="ghost" onClick={onSignOut}>
          <LogOut />
          <span className="hidden sm:inline">Sign out</span>
        </Button>
      </div>
    </header>
  )
}
