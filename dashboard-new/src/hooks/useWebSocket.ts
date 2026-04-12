import { useEffect, useRef, useCallback, useState } from 'react'
import { getWSUrl } from '../lib/api'
import type { WSEvent } from '../lib/types'

export function useWebSocket(onMessage: (ev: WSEvent) => void) {
  const wsRef = useRef<WebSocket | null>(null)
  const onMsgRef = useRef(onMessage)
  const [connected, setConnected] = useState(false)
  onMsgRef.current = onMessage

  useEffect(() => {
    let cancelled = false
    let reconnectTimer: ReturnType<typeof setTimeout>

    function connect() {
      if (cancelled) return
      const ws = new WebSocket(getWSUrl())
      wsRef.current = ws

      ws.onopen = () => setConnected(true)
      ws.onclose = (e) => {
        setConnected(false)
        if (e.code === 4001) {
          window.location.href = '/login'
          return
        }
        if (!cancelled) reconnectTimer = setTimeout(connect, 2000)
      }
      ws.onerror = () => {}
      ws.onmessage = (evt) => {
        const data: WSEvent = JSON.parse(evt.data)
        onMsgRef.current(data)
      }
    }

    connect()
    return () => {
      cancelled = true
      clearTimeout(reconnectTimer)
      wsRef.current?.close()
    }
  }, [])

  const send = useCallback((data: object) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(data))
    }
  }, [])

  return { send, connected }
}
