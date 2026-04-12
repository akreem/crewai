import { useState, type FormEvent } from 'react'
import { login } from '../lib/api'
import './Login.css'

export default function Login() {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!password.trim()) return
    setLoading(true)
    setError('')
    try {
      const ok = await login(password)
      if (ok) {
        window.location.href = '/'
      } else {
        setError('Wrong password')
        setLoading(false)
      }
    } catch {
      setError('Connection error')
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={handleSubmit}>
        <div className="logo">Sentinel</div>
        <div className="subtitle">Enter password to continue</div>
        <div className="form-group">
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            autoFocus
          />
        </div>
        <button className="login-btn" disabled={loading} type="submit">
          {loading ? 'Signing in...' : 'Sign in'}
        </button>
        <div className="error-msg">{error}</div>
      </form>
    </div>
  )
}
