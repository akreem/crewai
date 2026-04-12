import { useState, useRef, useCallback, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { fetchJSON } from '../lib/api'
import { formatElapsed } from '../lib/utils'
import { useWebSocket } from '../hooks/useWebSocket'
import { useSessions, useWorkspaceFiles, useAgentStatus } from '../hooks/useData'
import type { FeedItem, WSEvent, ChatMessage } from '../lib/types'
import Sidebar from './Sidebar'
import MessageFeed from './MessageFeed'
import InputArea from './InputArea'
import FileModal from './FileModal'
import './ChatView.css'

export default function ChatView() {
  const navigate = useNavigate()
  const { sessionId } = useParams<{ sessionId: string }>()
  const [feed, setFeed] = useState<FeedItem[]>([])
  const [typing, setTyping] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [currentSession, setCurrentSession] = useState<string | null>(sessionId || null)
  const [title, setTitle] = useState('New Chat')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [viewFile, setViewFile] = useState<string | null>(null)
  const messagesRef = useRef<HTMLDivElement>(null)
  const timerRef = useRef<number | null>(null)
  const agentStartRef = useRef<number | null>(null)

  const { sessions, refresh: refreshSessions } = useSessions()
  const { files, currentPath, browse } = useWorkspaceFiles()
  const agentStatus = useAgentStatus()

  const scrollDown = useCallback(() => {
    requestAnimationFrame(() => {
      if (messagesRef.current) messagesRef.current.scrollTop = messagesRef.current.scrollHeight
    })
  }, [])

  // Auto-scroll when typing indicator or feed changes
  useEffect(() => { scrollDown() }, [typing, feed, scrollDown])

  const addFeedItem = useCallback((item: FeedItem) => {
    setFeed(prev => [...prev, item])
    scrollDown()
  }, [scrollDown])

  const handleWSMessage = useCallback((ev: WSEvent) => {
    switch (ev.event) {
      case 'session':
        setCurrentSession(ev.session_id)
        setTitle(ev.title || 'Chat')
        navigate(`/chat/${ev.session_id}`, { replace: true })
        refreshSessions()
        break

      case 'phase':
        if (ev.phase === 'thinking') setTyping('Thinking')
        else if (ev.phase === 'executing') setTyping('Executing')
        else if (ev.phase === 'documenting') setTyping('Scribe documenting')
        else if (ev.phase === 'summarizing') setTyping('Writing summary')
        else if (ev.phase === 'done') {
          const elapsed = timerRef.current ? formatElapsed(Date.now() - timerRef.current) : ''
          timerRef.current = null
          setTyping(null)
          addFeedItem({ type: 'system', content: `Execution complete${elapsed ? ` in ${elapsed}` : ''}` })
          setSending(false)
          refreshSessions()
          browse(currentPath)
        } else if (ev.phase === 'chat') {
          setTyping(null)
          setSending(false)
        }
        if (ev.phase === 'thinking' || ev.phase === 'executing') {
          if (!timerRef.current) timerRef.current = Date.now()
        }
        break

      case 'reply':
        setTyping(null)
        if (ev.content) addFeedItem({ type: 'assistant', content: ev.content })
        setSending(false)
        break

      case 'agent_start':
        setTyping(`${(ev.agent || '').toUpperCase()} working`)
        agentStartRef.current = Date.now()
        break

      case 'agent_done': {
        const elapsed = agentStartRef.current ? formatElapsed(Date.now() - agentStartRef.current) : undefined
        agentStartRef.current = null
        setTyping(null)
        addFeedItem({
          type: 'agent',
          report: { agent: ev.agent, summary: ev.summary, output_file: ev.output_file, error: ev.error, elapsed },
        })
        break
      }

      case 'scribe_report':
        addFeedItem({ type: 'scribe', report: { filename: ev.filename, download_path: ev.download_path } })
        break

      case 'error':
        setTyping(null)
        addFeedItem({ type: 'system', content: `Error: ${ev.message || 'Unknown'}` })
        setSending(false)
        break
    }
  }, [addFeedItem, navigate, refreshSessions, browse, currentPath])

  const { send } = useWebSocket(handleWSMessage)

  // Load chat on mount or sessionId change
  useEffect(() => {
    if (!sessionId) return
    fetchJSON<{ title?: string; messages?: ChatMessage[] }>(`/chat/${sessionId}/messages`)
      .then(d => {
        setCurrentSession(sessionId)
        setTitle(d.title || 'Chat')
        const items: FeedItem[] = (d.messages || []).map(m => ({
          type: m.role === 'user' ? 'user' as const : 'assistant' as const,
          content: m.content,
        }))
        setFeed(items)
        scrollDown()
      })
      .catch(() => addFeedItem({ type: 'system', content: 'Failed to load chat' }))
  }, [sessionId, scrollDown, addFeedItem])

  function handleSend(text: string) {
    setSending(true)
    setFeed(prev => [...prev, { type: 'user', content: text }])
    scrollDown()
    send({ message: text, session_id: currentSession })
  }

  function handleNewChat() {
    setCurrentSession(null)
    setTitle('New Chat')
    setFeed([])
    navigate('/')
  }

  function handleOpenChat(id: string) {
    navigate(`/chat/${id}`)
  }

  function handleDeleteChat(id: string) {
    fetchJSON(`/chat/${id}/delete`, { method: 'DELETE' })
      .then(() => {
        if (currentSession === id) handleNewChat()
        refreshSessions()
      })
      .catch(() => {})
  }

  const showWelcome = feed.length === 0

  return (
    <div className="app">
      <Sidebar
        sessions={sessions}
        currentSession={currentSession}
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
        onNewChat={handleNewChat}
        onOpenChat={handleOpenChat}
        onDeleteChat={handleDeleteChat}
        files={files}
        currentPath={currentPath}
        onBrowse={browse}
        onViewFile={setViewFile}
        agentStatus={agentStatus}
      />
      <div className="main">
        <div className="topbar">
          <button className="toggle-sidebar" onClick={() => setSidebarCollapsed(!sidebarCollapsed)} title="Toggle sidebar">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 12h18M3 6h18M3 18h18" />
            </svg>
          </button>
          <span className="topbar-title">{title}</span>
        </div>
        <div className="messages" ref={messagesRef}>
          <div className="messages-inner">
            {showWelcome ? (
              <div className="welcome">
                <div className="welcome-title">Sentinel</div>
                <div className="welcome-sub">Multi-agent SRE &amp; Security platform. Start a conversation below.</div>
              </div>
            ) : (
              <MessageFeed feed={feed} typing={typing} />
            )}
          </div>
        </div>
        <InputArea onSend={handleSend} disabled={sending} />
      </div>
      <FileModal filePath={viewFile} onClose={() => setViewFile(null)} />
    </div>
  )
}
