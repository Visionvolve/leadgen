import { useState } from 'react'
import { useRegenEstimate, useRegenerateMessage } from '../../api/queries/useMessages'
import { useToast } from '../../components/ui/Toast'
import { LANGUAGES as LANG_LIST, FORMALITY_LABELS } from '../../lib/languages'

const LANGUAGES = LANG_LIST.map((l) => ({ value: l.code, label: l.label }))

const TONES = [
  { value: 'professional', label: 'Professional' },
  { value: 'friendly', label: 'Friendly' },
  { value: 'casual', label: 'Casual' },
  { value: 'bold', label: 'Bold' },
  { value: 'authoritative', label: 'Authoritative' },
  { value: 'empathetic', label: 'Empathetic' },
]

interface RegenerationDialogProps {
  messageId: string
  currentLanguage: string | null
  currentTone: string | null
  onClose: () => void
  onRegenerated: () => void
}

export function RegenerationDialog({
  messageId, currentLanguage, currentTone, onClose, onRegenerated,
}: RegenerationDialogProps) {
  const { toast } = useToast()
  const { data: estimate, isLoading: estimateLoading } = useRegenEstimate(messageId)
  const regenMutation = useRegenerateMessage()

  const [language, setLanguage] = useState(currentLanguage ?? 'en')
  const [formality, setFormality] = useState<'formal' | 'informal'>('formal')
  const [tone, setTone] = useState(currentTone ?? 'professional')
  const [instruction, setInstruction] = useState('')

  const hasFormality = language in FORMALITY_LABELS
  const formalityLabels = FORMALITY_LABELS[language] ?? { formal: 'Formal', informal: 'Informal' }

  const handleRegenerate = async () => {
    try {
      await regenMutation.mutateAsync({
        id: messageId,
        data: {
          language,
          formality: hasFormality ? formality : undefined,
          tone,
          instruction: instruction.trim() || undefined,
        },
      })
      toast('Message regenerated', 'success')
      onRegenerated()
    } catch {
      toast('Regeneration failed', 'error')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="bg-bg border border-border rounded-xl shadow-xl max-w-lg w-full mx-4 p-6" onClick={e => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-text mb-4">Regenerate Message</h3>

        <div className="space-y-4">
          {/* Language */}
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1">Language</label>
            <select
              value={language}
              onChange={e => setLanguage(e.target.value)}
              className="w-full px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text focus:outline-none focus:ring-1 focus:ring-accent"
            >
              {LANGUAGES.map(l => (
                <option key={l.value} value={l.value}>{l.label}</option>
              ))}
            </select>
          </div>

          {/* Formality */}
          {hasFormality && (
            <div>
              <label className="block text-xs font-medium text-text-muted mb-1">Formality</label>
              <div className="flex gap-2">
                {(['formal', 'informal'] as const).map(f => (
                  <button
                    key={f}
                    onClick={() => setFormality(f)}
                    className={`flex-1 px-3 py-2 text-sm rounded-lg border transition-colors ${
                      formality === f
                        ? 'bg-accent/15 border-accent text-accent font-medium'
                        : 'bg-surface border-border text-text-muted hover:bg-surface-alt'
                    }`}
                  >
                    {formalityLabels[f]}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Tone */}
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1">Tone</label>
            <select
              value={tone}
              onChange={e => setTone(e.target.value)}
              className="w-full px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text focus:outline-none focus:ring-1 focus:ring-accent"
            >
              {TONES.map(t => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>

          {/* Custom instruction */}
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1">
              Custom instruction <span className="text-text-dim">(optional, {instruction.length}/200)</span>
            </label>
            <input
              type="text"
              value={instruction}
              onChange={e => setInstruction(e.target.value.slice(0, 200))}
              placeholder="e.g. mention our mutual connection Jan"
              className="w-full px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>

          {/* Cost estimate */}
          <div className="p-3 bg-surface-alt rounded-lg border border-border">
            {estimateLoading ? (
              <span className="text-xs text-text-dim">Estimating cost...</span>
            ) : estimate ? (
              <div className="text-xs text-text-muted space-y-1">
                <div>Estimated cost: <span className="text-text font-medium">~{Math.round(estimate.estimated_cost * 1000)} credits</span></div>
                <div>{estimate.input_tokens} input + {estimate.output_tokens} output tokens</div>
                <div>Model: {estimate.model}</div>
              </div>
            ) : (
              <span className="text-xs text-text-dim">Cost estimate unavailable</span>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-2 mt-6">
          <button
            onClick={handleRegenerate}
            disabled={regenMutation.isPending}
            className="flex-1 px-4 py-2 bg-accent text-white text-sm font-medium rounded-lg hover:bg-accent-hover disabled:opacity-50"
          >
            {regenMutation.isPending ? 'Regenerating...' : 'Regenerate'}
          </button>
          <button
            onClick={onClose}
            disabled={regenMutation.isPending}
            className="px-4 py-2 bg-surface border border-border text-text text-sm rounded-lg hover:bg-surface-alt"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
