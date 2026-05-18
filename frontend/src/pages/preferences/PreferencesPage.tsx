/**
 * PreferencesPage -- tabbed settings page with vertical navigation.
 *
 * Sections are individually importable for use by other sprint items
 * (BL-037, LANG, TMPL).
 */

import { useState, useRef, useCallback, type KeyboardEvent } from 'react'
import { GeneralSection } from './sections/GeneralSection'
import { LanguageSection } from './sections/LanguageSection'
import { CampaignTemplatesSection } from './sections/CampaignTemplatesSection'
import { StrategyTemplatesSection } from './sections/StrategyTemplatesSection'
import { BrowserExtensionSection } from './sections/BrowserExtensionSection'

interface SettingsTab {
  id: string
  label: string
  component: React.ComponentType
}

const TABS: SettingsTab[] = [
  { id: 'general', label: 'General', component: GeneralSection },
  { id: 'browser-extension', label: 'Browser Extension', component: BrowserExtensionSection },
  { id: 'language', label: 'Language', component: LanguageSection },
  { id: 'campaign-templates', label: 'Campaign Templates', component: CampaignTemplatesSection },
  { id: 'strategy-templates', label: 'Strategy Templates', component: StrategyTemplatesSection },
]

export function PreferencesPage() {
  const [activeTab, setActiveTab] = useState(TABS[0].id)
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([])

  const activeIndex = TABS.findIndex((t) => t.id === activeTab)
  const ActiveComponent = TABS[activeIndex]?.component ?? TABS[0].component

  const focusTab = useCallback((index: number) => {
    const clamped = Math.max(0, Math.min(TABS.length - 1, index))
    tabRefs.current[clamped]?.focus()
    setActiveTab(TABS[clamped].id)
  }, [])

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault()
          focusTab(activeIndex + 1)
          break
        case 'ArrowUp':
          e.preventDefault()
          focusTab(activeIndex - 1)
          break
        case 'Home':
          e.preventDefault()
          focusTab(0)
          break
        case 'End':
          e.preventDefault()
          focusTab(TABS.length - 1)
          break
      }
    },
    [activeIndex, focusTab],
  )

  return (
    <div className="max-w-[960px] mx-auto">
      <div className="mb-5">
        <h1 className="font-title text-[1.3rem] font-semibold tracking-tight mb-1.5">
          Settings
        </h1>
        <p className="text-text-muted text-sm">
          Account settings and integrations.
        </p>
      </div>

      {/* Mobile dropdown (< 768px) */}
      <div className="md:hidden mb-4">
        <select
          value={activeTab}
          onChange={(e) => setActiveTab(e.target.value)}
          aria-label="Settings section"
          className="w-full bg-surface border border-border rounded-lg px-3 py-2.5 text-sm text-text focus:outline-none focus:border-accent"
        >
          {TABS.map((tab) => (
            <option key={tab.id} value={tab.id}>
              {tab.label}
            </option>
          ))}
        </select>
      </div>

      <div className="flex gap-6">
        {/* Vertical tab list (>= 768px) */}
        <div
          role="tablist"
          aria-label="Settings sections"
          aria-orientation="vertical"
          className="hidden md:flex flex-col flex-shrink-0 w-[200px]"
          onKeyDown={handleKeyDown}
        >
          {TABS.map((tab, i) => (
            <button
              key={tab.id}
              ref={(el) => { tabRefs.current[i] = el }}
              role="tab"
              id={`settings-tab-${tab.id}`}
              aria-selected={activeTab === tab.id}
              aria-controls={`settings-panel-${tab.id}`}
              tabIndex={activeTab === tab.id ? 0 : -1}
              onClick={() => setActiveTab(tab.id)}
              className={`text-left px-3 py-2 text-sm rounded-md transition-colors border-l-2 ${
                activeTab === tab.id
                  ? 'border-accent text-text bg-surface-alt font-medium'
                  : 'border-transparent text-text-muted hover:text-text hover:bg-surface-alt/50'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab panel */}
        <div
          role="tabpanel"
          id={`settings-panel-${activeTab}`}
          aria-labelledby={`settings-tab-${activeTab}`}
          className="flex-1 min-w-0"
        >
          <ActiveComponent />
        </div>
      </div>
    </div>
  )
}
