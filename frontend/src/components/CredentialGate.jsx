import { useState } from 'react'
import {
  clearApiKey,
  hasApiKey,
  setApiKey,
  validateApiCredential,
} from '../api.js'
import { useToast } from './ToastProvider.jsx'

/**
 * Paste-once API credential gate (BIN-46 / Story 2.2).
 * Stores the key only in sessionStorage; api.js attaches X-API-Key.
 */
export default function CredentialGate() {
  const showToast = useToast()
  const [draft, setDraft] = useState('')
  const [configured, setConfigured] = useState(() => hasApiKey())
  const [busy, setBusy] = useState(false)

  const handleSave = async (e) => {
    e.preventDefault()
    const value = draft.trim()
    if (!value) {
      showToast('Paste an API credential first', { type: 'warning' })
      return
    }
    setBusy(true)
    setApiKey(value)
    try {
      await validateApiCredential()
      setConfigured(true)
      setDraft('')
      showToast('API credential saved for this session', { type: 'success' })
    } catch (err) {
      clearApiKey()
      setConfigured(false)
      showToast(err.message || 'Invalid or missing API credential', { type: 'error' })
    } finally {
      setBusy(false)
    }
  }

  const handleClear = () => {
    clearApiKey()
    setConfigured(false)
    setDraft('')
    showToast('API credential cleared', { type: 'info' })
  }

  return (
    <div className="credential-gate" data-testid="credential-gate">
      <div className="credential-gate-header">
        <span>API credential</span>
        <span
          className={`credential-gate-status ${configured ? 'set' : 'missing'}`}
          data-testid="credential-status"
        >
          {configured ? 'set' : 'missing'}
        </span>
      </div>
      <form className="credential-gate-form" onSubmit={handleSave}>
        <input
          type="password"
          className="form-input"
          placeholder="Paste API key"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          autoComplete="off"
          aria-label="API credential"
          data-testid="credential-input"
          disabled={busy}
        />
        <div className="credential-gate-actions">
          <button
            type="submit"
            className="btn btn-primary btn-sm"
            disabled={busy}
            data-testid="credential-save"
          >
            {busy ? '…' : 'Save'}
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={handleClear}
            disabled={busy || !configured}
            data-testid="credential-clear"
          >
            Clear
          </button>
        </div>
      </form>
    </div>
  )
}
