import { motion } from 'motion/react'
import {
  CheckCircle2, CircleHelp, FileCheck2, Inbox, Mail, MailOpen, Plug, Settings as Cog,
  ShieldAlert,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { Inbox as InboxData } from '@/api'
import { CATEGORY_LABELS } from '@/format'

const ICONS: Record<string, LucideIcon> = {
  BL_COMPARISON: FileCheck2,
  SI_REQUEST: Mail,
  INVOICE_QUERY: Inbox,
  HELP: CircleHelp,
  GENERAL: MailOpen,
  SPAM: ShieldAlert,
  READ: CheckCircle2,
}

/** The queue, then what is finished. The order is the working order. */
const GROUPS: { label: string; lanes: string[] }[] = [
  { label: 'Verification', lanes: ['BL_COMPARISON'] },
  { label: 'Inbox', lanes: ['SI_REQUEST', 'INVOICE_QUERY', 'HELP', 'GENERAL', 'SPAM'] },
  { label: 'Done', lanes: ['READ'] },
]

export default function Sidebar({
  data,
  lane,
  view,
  onLane,
  onView,
  children,
}: {
  data: InboxData | null
  lane: string
  view: 'lanes' | 'settings' | 'gmail'
  onLane: (lane: string) => void
  onView: (view: 'lanes' | 'settings' | 'gmail') => void
  /** The mailbox card and the run line, which belong at the bottom. */
  children?: React.ReactNode
}) {
  return (
    <aside className="sidebar glass-2">
      <div className="sidebar__head">
        <span className="brand">
          <span className="brand__mark">
            <Mail className="size-[18px]" />
          </span>
          <span className="brand__word">VS-MAIL</span>
        </span>
      </div>

      <div className="sidebar__scroll">
        {GROUPS.map((group) => (
          <div className="nav__group" key={group.label}>
            <div className="nav__label-group">{group.label}</div>
            {group.lanes.map((key) => {
              const items = data?.lanes?.[key] || []
              // Read is finished work; a count in the attention colour there
              // would read as something still to do.
              const flagged = key === 'READ'
                ? 0
                : key === 'HELP'
                  ? items.length
                  : items.filter((r) => r.status !== 'OK').length
              const Icon = ICONS[key] ?? Mail
              const active = view === 'lanes' && lane === key
              return (
                <motion.button
                  key={key}
                  type="button"
                  className={`nav__item${active ? ' is-active' : ''}`}
                  onClick={() => onLane(key)}
                  whileHover={{ x: 2 }}
                  whileTap={{ scale: 0.985 }}
                  transition={{ type: 'spring', stiffness: 500, damping: 32 }}
                >
                  <Icon className="nav__icon size-4" />
                  <span className="nav__label">{CATEGORY_LABELS[key] ?? key}</span>
                  <span className={`nav__badge${flagged ? ' is-attn' : ''}`}>
                    {items.length}
                  </span>
                </motion.button>
              )
            })}
          </div>
        ))}
        {/* The mailbox and the preferences. Not lanes, so they sit apart. */}
        <div className="nav__group">
          <div className="nav__label-group">System</div>
          {([
            { id: 'gmail' as const, label: 'Gmail', Icon: Plug },
            { id: 'settings' as const, label: 'Settings', Icon: Cog },
          ]).map(({ id, label, Icon }) => (
            <motion.button
              key={id}
              type="button"
              className={`nav__item${view === id ? ' is-active' : ''}`}
              onClick={() => onView(id)}
              whileHover={{ x: 2 }}
              whileTap={{ scale: 0.985 }}
              transition={{ type: 'spring', stiffness: 500, damping: 32 }}
            >
              <Icon className="nav__icon size-4" />
              <span className="nav__label">{label}</span>
            </motion.button>
          ))}
        </div>
      </div>

      {children && <div className="sidebar__foot">{children}</div>}
    </aside>
  )
}
