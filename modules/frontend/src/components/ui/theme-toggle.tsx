import { Moon, Sun } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useTheme } from '@/stores/theme'

/** Switches between the dark and the warm-white theme; the icon is the one you would switch to. */
export function ThemeToggle() {
  const theme = useTheme((s) => s.theme)
  const toggleTheme = useTheme((s) => s.toggle)
  const label = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'

  return (
    <Button variant="ghost" size="icon" aria-label={label} title={label} onClick={toggleTheme}>
      {theme === 'dark' ? <Sun className="h-[15px] w-[15px]" /> : <Moon className="h-[15px] w-[15px]" />}
    </Button>
  )
}
