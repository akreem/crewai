import { useState, useRef } from 'react'
import { renderMarkdown, parseThoughts, copyToClipboard } from '../lib/utils'
import type { FeedItem } from '../lib/types'
import './MessageFeed.css'

function CopyButton({ getText }: { getText: () => string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      className="copy-btn"
      onClick={() => {
        copyToClipboard(getText())
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      }}
    >
      {copied ? (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#22c55e" strokeWidth="2">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="9" y="9" width="13" height="13" rx="2" />
          <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
        </svg>
      )}
    </button>
  )
}

function ThoughtBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="thought-block">
      <button className={`thought-toggle ${open ? 'open' : ''}`} onClick={() => setOpen(!open)}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
          <polyline points="9 18 15 12 9 6" />
        </svg>
        <span className="thought-label">Thought process</span>
      </button>
      {open && <div className="thought-body open">{text.trim()}</div>}
    </div>
  )
}

function AssistantMessage({ content }: { content: string }) {
  const contentRef = useRef<HTMLDivElement>(null)
  const parts = parseThoughts(content)
  const plainText = parts.filter(p => p.type === 'text').map(p => p.text).join('').trim()

  return (
    <div className="msg-row assistant">
      <div className="msg-avatar assistant-av">S</div>
      <div>
        <div className="msg-content" ref={contentRef}>
          {parts.map((p, i) =>
            p.type === 'thought'
              ? <ThoughtBlock key={i} text={p.text} />
              : null
          )}
          <span dangerouslySetInnerHTML={{ __html: renderMarkdown(plainText) }} />
        </div>
        <div className="msg-actions">
          <CopyButton getText={() => contentRef.current?.textContent || ''} />
        </div>
      </div>
    </div>
  )
}

function AgentCard({ report }: { report: FeedItem & { type: 'agent' } }) {
  const { agent, summary, output_file, error, elapsed } = report.report
  const [expanded, setExpanded] = useState(false)

  let body = ''
  if (error) body = `Error: ${error}`
  else {
    if (summary) body = summary
    if (output_file) body += `${body ? '\n' : ''}File: ${output_file}`
  }

  const needsCollapse = body.length > 500

  return (
    <div className={`agent-card ${error ? 'error' : ''}`}>
      <div className="agent-card-header">
        <div className="agent-dot" />
        <div className="agent-card-name">{agent.toUpperCase()}</div>
        {elapsed && (
          <span style={{ fontSize: 11, color: 'var(--gray-500)', fontWeight: 400, marginLeft: 'auto' }}>
            {elapsed}
          </span>
        )}
      </div>
      <CopyButton getText={() => body} />
      <div className={`agent-card-body ${needsCollapse && !expanded ? 'collapsed' : ''}`}>
        {body}
      </div>
      {needsCollapse && (
        <button className="see-more" onClick={() => setExpanded(!expanded)}>
          {expanded ? 'See less' : 'See more'}
        </button>
      )}
    </div>
  )
}

function ScribeReportCard({ report }: { report: FeedItem & { type: 'scribe' } }) {
  const { filename, download_path } = report.report
  return (
    <div className="report-card">
      <div className="report-card-header">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
          <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
          <polyline points="10 9 9 9 8 9" />
        </svg>
        <span className="report-card-title">{filename}</span>
      </div>
      <div className="report-actions">
        <a
          href={`${location.origin}/workspace/download/${encodeURIComponent(download_path)}`}
          download
          className="agent-action-btn"
          style={{ textDecoration: 'none' }}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14">
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          Download
        </a>
      </div>
    </div>
  )
}

function TypingIndicator({ label }: { label: string }) {
  return (
    <div className="typing-row">
      <div className="msg-avatar assistant-av">S</div>
      <div className="typing-dot-group">
        <span /><span /><span />
      </div>
      <div className="typing-label">{label}</div>
    </div>
  )
}

interface Props {
  feed: FeedItem[]
  typing: string | null
}

export default function MessageFeed({ feed, typing }: Props) {
  return (
    <>
      {feed.map((item, i) => {
        switch (item.type) {
          case 'user':
            return (
              <div className="msg-row user" key={i}>
                <div className="msg-content">{item.content}</div>
              </div>
            )
          case 'assistant':
            return <AssistantMessage key={i} content={item.content} />
          case 'system':
            return <div className="system-msg" key={i}>{item.content}</div>
          case 'agent':
            return <AgentCard key={i} report={item} />
          case 'scribe':
            return <ScribeReportCard key={i} report={item} />
          default:
            return null
        }
      })}
      {typing && <TypingIndicator label={typing} />}
    </>
  )
}
