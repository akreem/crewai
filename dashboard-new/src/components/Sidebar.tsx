import { logout } from '../lib/api'
import { useLLMCheck } from '../hooks/useData'
import type { Session, FileEntry } from '../lib/types'
import './Sidebar.css'

interface Props {
  sessions: Session[]
  currentSession: string | null
  collapsed: boolean
  onToggle: () => void
  onNewChat: () => void
  onOpenChat: (id: string) => void
  onDeleteChat: (id: string) => void
  files: FileEntry[]
  currentPath: string
  onBrowse: (dir: string) => void
  onViewFile: (path: string) => void
  agentStatus: { online: number; total: number }
}

export default function Sidebar({
  sessions, currentSession, collapsed, onToggle,
  onNewChat, onOpenChat, onDeleteChat,
  files, currentPath, onBrowse, onViewFile,
  agentStatus,
}: Props) {
  const { llmStatus, checking, check } = useLLMCheck()
  const allOnline = agentStatus.online === agentStatus.total
  const statusClass = allOnline ? 'ok' : agentStatus.online > 0 ? 'warn' : 'err'
  const statusText = allOnline
    ? 'All agents online'
    : `${agentStatus.online}/${agentStatus.total} agents online`

  return (
    <div className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-header">
        <span className="logo">Sentinel</span>
        <button className="sidebar-btn" onClick={onToggle} title="Close sidebar">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 12h18M3 6h18M3 18h18" />
          </svg>
        </button>
      </div>

      <button className="new-chat" onClick={onNewChat}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
          <path d="M12 5v14M5 12h14" />
        </svg>
        New Chat
      </button>

      <div className="sidebar-label">Recent</div>
      <ul className="chat-list">
        {sessions.map(s => (
          <li
            key={s.session_id}
            className={s.session_id === currentSession ? 'active' : ''}
            onClick={() => onOpenChat(s.session_id)}
          >
            <span className="title">{s.title || 'Untitled'}</span>
            <button
              className="del"
              onClick={e => { e.stopPropagation(); onDeleteChat(s.session_id) }}
            >
              &times;
            </button>
          </li>
        ))}
      </ul>

      <div className="files-section">
        <div className="sidebar-label">Workspace</div>
        <ul className="file-list">
          {currentPath && (
            <li onClick={() => onBrowse('')} style={{ color: 'var(--gray-400)' }}>
              &larr; Back
            </li>
          )}
          {files.length === 0 && (
            <li style={{ cursor: 'default', color: 'var(--gray-600)' }}>Empty</li>
          )}
          {files.map(f => (
            <li
              key={f.path}
              onClick={() => f.type === 'directory' ? onBrowse(f.path) : onViewFile(f.path)}
              style={f.type === 'directory' ? { color: 'var(--gray-300)' } : undefined}
            >
              {f.type === 'directory' ? '📁 ' : ''}{f.name}
            </li>
          ))}
        </ul>
      </div>

      <div className="sidebar-footer">
        <span className={`dot ${statusClass}`} />
        <span>{statusText}</span>
        <button
          className={`llm-check-btn ${checking ? 'checking' : ''}`}
          onClick={check}
        >
          {checking ? 'Checking...' : 'LLM Check'}
        </button>
        <button className="llm-check-btn" onClick={() => logout().then(() => { window.location.href = '/login' })}>
          Logout
        </button>
        {llmStatus && (
          <div className="llm-status-panel">
            {['orchestrator', 'watchman', 'shield', 'scribe'].map(name => {
              const info = llmStatus[name] || {}
              return (
                <div className="llm-status-row" key={name} title={info.error || ''}>
                  <span className={`dot ${info.ok ? 'ok' : 'err'}`} />
                  <span className="llm-name">{name}</span>
                  <span className="llm-model">{info.model || '?'}</span>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
