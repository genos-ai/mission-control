import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { Segmented, type SegmentedOption } from '@/components/ui/segmented'
import { useTheme, type Theme } from '@/stores/theme'

const THEME_OPTIONS: SegmentedOption<Theme>[] = [
  { value: 'dark', label: 'Dark' },
  { value: 'warm-white', label: 'Warm white' },
]

/** The theme choice shares the store with the sidebar toggle, so the two never disagree. */
export function AppearancePanel() {
  const theme = useTheme((s) => s.theme)
  const setTheme = useTheme((s) => s.setTheme)

  return (
    <Panel>
      <PanelHeader title="Appearance" />
      <PanelContent className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm font-medium text-text-3">Theme</p>
          <p className="text-xs text-subtle">Saved in this browser only.</p>
        </div>
        <Segmented label="Theme" value={theme} onChange={setTheme} options={THEME_OPTIONS} />
      </PanelContent>
    </Panel>
  )
}
