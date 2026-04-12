import { useState, useEffect, useCallback } from 'react'
import { fetchJSON } from '../lib/api'
import type { Session, FileEntry, StatusResponse, LLMStatus } from '../lib/types'

export function useSessions() {
  const [sessions, setSessions] = useState<Session[]>([])

  const refresh = useCallback(() => {
    fetchJSON<{ sessions: Session[] }>('/chat/sessions')
      .then(d => setSessions(d.sessions || []))
      .catch(() => {})
  }, [])

  useEffect(() => { refresh() }, [refresh])
  return { sessions, refresh }
}

export function useWorkspaceFiles() {
  const [files, setFiles] = useState<FileEntry[]>([])
  const [currentPath, setCurrentPath] = useState('')

  const browse = useCallback((dir = '') => {
    setCurrentPath(dir)
    const url = dir ? `/workspace/files?path=${encodeURIComponent(dir)}` : '/workspace/files'
    fetchJSON<{ files: FileEntry[] }>(url)
      .then(d => setFiles(d.files || []))
      .catch(() => setFiles([]))
  }, [])

  useEffect(() => { browse() }, [browse])
  useEffect(() => {
    const id = setInterval(() => browse(currentPath), 30000)
    return () => clearInterval(id)
  }, [browse, currentPath])

  return { files, currentPath, browse }
}

export function useAgentStatus() {
  const [status, setStatus] = useState<{ online: number; total: number }>({ online: 0, total: 3 })

  const refresh = useCallback(() => {
    fetchJSON<StatusResponse>('/status')
      .then(d => {
        const agents = ['watchman', 'shield', 'scribe'] as const
        const online = agents.filter(a => d[a]?.status === 'ok').length
        setStatus({ online, total: agents.length })
      })
      .catch(() => setStatus({ online: 0, total: 3 }))
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 15000)
    return () => clearInterval(id)
  }, [refresh])

  return status
}

/** Per-agent online/offline status map */
export function useAgentStatusMap() {
  const [statusMap, setStatusMap] = useState<Record<string, boolean>>({})

  const refresh = useCallback(() => {
    fetchJSON<StatusResponse>('/status')
      .then(d => {
        const map: Record<string, boolean> = { orchestrator: true }
        for (const name of ['watchman', 'shield', 'scribe'] as const) {
          map[name] = d[name]?.status === 'ok'
        }
        setStatusMap(map)
      })
      .catch(() => setStatusMap({}))
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 15000)
    return () => clearInterval(id)
  }, [refresh])

  return statusMap
}

export function useLLMCheck() {
  const [llmStatus, setLLMStatus] = useState<LLMStatus | null>(null)
  const [checking, setChecking] = useState(false)

  const check = useCallback(() => {
    setChecking(true)
    fetchJSON<LLMStatus>('/status/llm')
      .then(d => { setLLMStatus(d); setChecking(false) })
      .catch(() => { setLLMStatus(null); setChecking(false) })
  }, [])

  return { llmStatus, checking, check }
}
