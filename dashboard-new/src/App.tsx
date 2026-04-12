import { useEffect, useState } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { checkAuth } from './lib/api'
import Login from './components/Login'
import ChatView from './components/ChatView'
import AgentManagement from './components/AgentManagement'

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null)

  useEffect(() => {
    checkAuth().then(setAuthed)
  }, [])

  // Loading
  if (authed === null) return null

  return (
    <Routes>
      <Route path="/login" element={authed ? <Navigate to="/" /> : <Login />} />
      <Route path="/agents" element={authed ? <AgentManagement /> : <Navigate to="/login" />} />
      <Route path="/chat/:sessionId" element={authed ? <ChatView /> : <Navigate to="/login" />} />
      <Route path="/" element={authed ? <ChatView /> : <Navigate to="/login" />} />
    </Routes>
  )
}
