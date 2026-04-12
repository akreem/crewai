/* ── Sentinel Dashboard Types ── */

// WebSocket incoming events
export type WSEvent =
  | { event: 'session'; session_id: string; title?: string }
  | { event: 'phase'; phase: string }
  | { event: 'reply'; content: string }
  | { event: 'agent_start'; agent: string }
  | { event: 'agent_done'; agent: string; summary?: string; output_file?: string; error?: string }
  | { event: 'scribe_report'; filename: string; download_path: string }
  | { event: 'error'; message: string }

// Chat message
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
}

// Agent card data
export interface AgentReport {
  agent: string
  summary?: string
  output_file?: string
  error?: string
  elapsed?: string
}

// Scribe report
export interface ScribeReport {
  filename: string
  download_path: string
}

// Session from API
export interface Session {
  session_id: string
  title?: string
}

// File entry from workspace API
export interface FileEntry {
  name: string
  path: string
  type: 'file' | 'directory'
}

// Status response
export interface StatusResponse {
  watchman?: { status: string }
  shield?: { status: string }
  scribe?: { status: string }
}

// LLM status
export interface LLMStatus {
  [key: string]: { ok: boolean; model?: string; error?: string }
}

// Display item for the chat feed
export type FeedItem =
  | { type: 'user'; content: string }
  | { type: 'assistant'; content: string; elapsed?: string }
  | { type: 'system'; content: string }
  | { type: 'agent'; report: AgentReport }
  | { type: 'scribe'; report: ScribeReport }
  | { type: 'typing'; label: string }
