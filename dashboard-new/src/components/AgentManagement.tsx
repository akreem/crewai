import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchJSON } from '../lib/api'
import { useAgentStatusMap } from '../hooks/useData'
import './AgentManagement.css'

interface AgentProfile {
  display_name: string
  avatar: string
  avatar_url: string | null
  description: string
  system_prompt_override: string | null
  live_system_prompt: string | null
}

type AgentConfigs = Record<string, AgentProfile>

const AVATAR_OPTIONS = [
  '👁️', '🛡️', '📝', '🤖', '🦾', '🧠', '⚡', '🔍', '🎯', '🦅',
  '🐺', '🦊', '🐻', '🦁', '🐉', '🔮', '💎', '🌟', '🚀', '⚔️',
  '🏴‍☠️', '👾', '🦇', '🕵️', '🧙', '👨‍💻', '👩‍💻', '🤺', '🎭', '🗡️',
]

export default function AgentManagement() {
  const navigate = useNavigate()
  const [configs, setConfigs] = useState<AgentConfigs>({})
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<string | null>(null)
  const [editForm, setEditForm] = useState({ display_name: '', avatar: '', description: '', system_prompt_override: '' })
  const [saving, setSaving] = useState(false)
  const [showAvatarPicker, setShowAvatarPicker] = useState(false)
  const [promptExpanded, setPromptExpanded] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [avatarVer, setAvatarVer] = useState(0)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const agentStatus = useAgentStatusMap()

  const loadConfigs = useCallback(() => {
    setLoading(true)
    fetchJSON<AgentConfigs>('/agents/config')
      .then(d => { setConfigs(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => { loadConfigs() }, [loadConfigs])

  function startEdit(name: string) {
    const profile = configs[name]
    setEditing(name)
    setEditForm({
      display_name: profile.display_name,
      avatar: profile.avatar,
      description: profile.description,
      system_prompt_override: profile.system_prompt_override || profile.live_system_prompt || '',
    })
    setShowAvatarPicker(false)
    setPromptExpanded(false)
  }

  function cancelEdit() {
    setEditing(null)
    setShowAvatarPicker(false)
    setPromptExpanded(false)
  }

  async function saveEdit() {
    if (!editing) return
    setSaving(true)
    try {
      const original = configs[editing]
      const body: Record<string, string | null> = {}
      if (editForm.display_name !== original.display_name) body.display_name = editForm.display_name
      if (editForm.avatar !== original.avatar) body.avatar = editForm.avatar
      if (editForm.description !== original.description) body.description = editForm.description

      // Only send prompt if it was changed from the live/override value
      const currentPrompt = original.system_prompt_override || original.live_system_prompt || ''
      if (editForm.system_prompt_override !== currentPrompt) {
        body.system_prompt_override = editForm.system_prompt_override
      }

      if (Object.keys(body).length > 0) {
        await fetchJSON(`/agents/${editing}/config`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
      }
      setEditing(null)
      loadConfigs()
    } catch (e) {
      console.error('Failed to save', e)
    } finally {
      setSaving(false)
    }
  }

  async function resetPrompt(name: string) {
    try {
      await fetchJSON(`/agents/${name}/config/reset-prompt`, { method: 'POST' })
      loadConfigs()
      if (editing === name) {
        setEditForm(prev => ({ ...prev, system_prompt_override: '' }))
      }
    } catch (e) {
      console.error('Failed to reset prompt', e)
    }
  }

  async function uploadAvatar(name: string, file: File) {
    if (file.size > 2 * 1024 * 1024) {
      alert('Image must be under 2 MB')
      return
    }
    setUploading(true)
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch(`${location.origin}/agents/${name}/avatar`, {
        method: 'POST',
        body: form,
        credentials: 'same-origin',
      })
      if (!res.ok) throw new Error('Upload failed')
      setAvatarVer(v => v + 1)
      loadConfigs()
    } catch (e) {
      console.error('Avatar upload failed', e)
    } finally {
      setUploading(false)
    }
  }

  async function removeAvatar(name: string) {
    try {
      await fetchJSON(`/agents/${name}/avatar`, { method: 'DELETE' })
      setAvatarVer(v => v + 1)
      loadConfigs()
    } catch (e) {
      console.error('Failed to remove avatar', e)
    }
  }

  const agentOrder = ['orchestrator', 'watchman', 'shield', 'scribe']
  const sortedAgents = agentOrder.filter(n => n in configs)

  return (
    <div className="agent-mgmt">
      <div className="agent-mgmt-header">
        <button className="agent-mgmt-back" onClick={() => navigate('/')} title="Back to chat">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
        <h1>Agent Management</h1>
        <p className="agent-mgmt-sub">Customize your agents — give them names, avatars, and fine-tune their behavior</p>
      </div>

      {loading ? (
        <div className="agent-mgmt-loading">Loading agents...</div>
      ) : (
        <div className="agent-cards-grid">
          {sortedAgents.map(name => {
            const profile = configs[name]
            const isEditing = editing === name

            return (
              <div key={name} className={`agent-profile-card ${isEditing ? 'editing' : ''}`}>
                {/* View mode */}
                {!isEditing && (
                  <>
                    <div className="agent-profile-top">
                      <div className="agent-profile-avatar">
                        {profile.avatar_url
                          ? <img src={`${profile.avatar_url}?v=${avatarVer}`} alt={profile.display_name} />
                          : profile.avatar
                        }
                        <span className={`status-dot ${agentStatus[name] ? 'online' : 'offline'}`} />
                      </div>
                      <div className="agent-profile-info">
                        <h2>{profile.display_name}</h2>
                        <span className="agent-profile-id">{name}</span>
                      </div>
                    </div>
                    <p className="agent-profile-desc">{profile.description}</p>
                    <div className="agent-profile-prompt-preview">
                      <span className="prompt-label">System Prompt</span>
                      <p className="prompt-preview-text">
                        {(profile.system_prompt_override || profile.live_system_prompt || '').substring(0, 150)}...
                      </p>
                      {profile.system_prompt_override && (
                        <span className="prompt-badge custom">Custom</span>
                      )}
                      {!profile.system_prompt_override && (
                        <span className="prompt-badge default">Default</span>
                      )}
                    </div>
                    <button className="agent-edit-btn" onClick={() => startEdit(name)}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
                        <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
                      </svg>
                      Edit Agent
                    </button>
                  </>
                )}

                {/* Edit mode */}
                {isEditing && (
                  <>
                    <div className="agent-edit-section">
                      <div className="agent-edit-avatar-row">
                        <div className="agent-edit-avatar-group">
                          <div className="agent-edit-avatar-preview">
                            {configs[name].avatar_url
                              ? <img src={`${configs[name].avatar_url}?v=${avatarVer}`} alt="" />
                              : <span>{editForm.avatar}</span>
                            }
                          </div>
                          <div className="agent-edit-avatar-actions">
                            <button
                              className="avatar-upload-btn"
                              onClick={() => fileInputRef.current?.click()}
                              disabled={uploading}
                            >
                              {uploading ? 'Uploading...' : 'Upload Photo'}
                            </button>
                            <input
                              ref={fileInputRef}
                              type="file"
                              accept="image/png,image/jpeg,image/webp,image/gif"
                              style={{ display: 'none' }}
                              onChange={e => {
                                const f = e.target.files?.[0]
                                if (f) uploadAvatar(name, f)
                                e.target.value = ''
                              }}
                            />
                            {configs[name].avatar_url && (
                              <button className="avatar-remove-btn" onClick={() => removeAvatar(name)}>
                                Remove
                              </button>
                            )}
                            <button
                              className="avatar-emoji-btn"
                              onClick={() => setShowAvatarPicker(!showAvatarPicker)}
                            >
                              {showAvatarPicker ? 'Close' : 'Pick Emoji'}
                            </button>
                          </div>
                        </div>
                        <div className="agent-edit-fields">
                          <label>
                            Display Name
                            <input
                              type="text"
                              value={editForm.display_name}
                              onChange={e => setEditForm(prev => ({ ...prev, display_name: e.target.value }))}
                              placeholder="Agent name"
                            />
                          </label>
                          <label>
                            Description
                            <input
                              type="text"
                              value={editForm.description}
                              onChange={e => setEditForm(prev => ({ ...prev, description: e.target.value }))}
                              placeholder="What this agent does"
                            />
                          </label>
                        </div>
                      </div>

                      {showAvatarPicker && (
                        <div className="avatar-picker">
                          {AVATAR_OPTIONS.map(emoji => (
                            <button
                              key={emoji}
                              className={`avatar-option ${editForm.avatar === emoji ? 'selected' : ''}`}
                              onClick={() => { setEditForm(prev => ({ ...prev, avatar: emoji })); setShowAvatarPicker(false) }}
                            >
                              {emoji}
                            </button>
                          ))}
                        </div>
                      )}

                      <div className="agent-edit-prompt">
                        <div className="prompt-header-row">
                          <button
                            className={`prompt-expand-btn ${promptExpanded ? 'open' : ''}`}
                            onClick={() => setPromptExpanded(!promptExpanded)}
                          >
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
                              <polyline points="9 18 15 12 9 6" />
                            </svg>
                            System Prompt
                          </button>
                          {configs[name].system_prompt_override && (
                            <button className="prompt-reset-btn" onClick={() => resetPrompt(name)}>
                              Reset to default
                            </button>
                          )}
                        </div>
                        {promptExpanded && (
                          <textarea
                            className="prompt-textarea"
                            value={editForm.system_prompt_override}
                            onChange={e => setEditForm(prev => ({ ...prev, system_prompt_override: e.target.value }))}
                            rows={12}
                            placeholder="System prompt for this agent..."
                          />
                        )}
                      </div>
                    </div>

                    <div className="agent-edit-actions">
                      <button className="btn-cancel" onClick={cancelEdit}>Cancel</button>
                      <button className="btn-save" onClick={saveEdit} disabled={saving}>
                        {saving ? 'Saving...' : 'Save Changes'}
                      </button>
                    </div>
                  </>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
