import { Moon, Sun } from 'lucide-react'
import { motion } from 'motion/react'
import { useTheme } from '@/useTheme'

/** Light or dark, with the icon itself doing the turning. */
export default function ThemeSwitcher() {
  const { resolved, setTheme } = useTheme()
  const next = resolved === 'dark' ? 'light' : 'dark'
  const Icon = resolved === 'dark' ? Moon : Sun

  return (
    <motion.button
      type="button"
      aria-label={`Switch to ${next} theme`}
      className="chip glass-4 grid size-[38px] place-items-center p-0"
      onClick={() => setTheme(next)}
      whileHover={{ scale: 1.06 }}
      whileTap={{ scale: 0.94 }}
      transition={{ type: 'spring', stiffness: 420, damping: 26 }}
    >
      <motion.span
        key={resolved}
        initial={{ rotate: -90, opacity: 0 }}
        animate={{ rotate: 0, opacity: 1 }}
        transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}
        className="grid place-items-center"
      >
        <Icon className="size-4" />
      </motion.span>
    </motion.button>
  )
}
