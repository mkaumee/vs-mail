import { motion } from 'motion/react'
import type { LucideIcon } from 'lucide-react'

export default function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = 'neutral',
  delay = 0,
}: {
  label: string
  value: number | string | undefined
  hint?: string
  icon?: LucideIcon
  tone?: 'neutral' | 'ok' | 'warn' | 'bad' | 'note'
  delay?: number
}) {
  return (
    <motion.div
      className={`stat glass-3 lift stat--${tone}`}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, delay, ease: [0.2, 0.8, 0.2, 1] }}
    >
      <div className="stat__top">
        <span className="stat__label">{label}</span>
        {Icon && (
          <span className="stat__icon">
            <Icon className="size-4" />
          </span>
        )}
      </div>
      <div className="stat__value tabular">
        {value === undefined ? <span className="skeleton block h-9 w-20" /> : value}
      </div>
      {hint && <div className="stat__hint">{hint}</div>}
    </motion.div>
  )
}
