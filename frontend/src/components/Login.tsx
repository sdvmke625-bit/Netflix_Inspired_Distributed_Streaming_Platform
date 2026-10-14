import { useState } from 'react'

interface LoginProps
{
  onLogin: () => void
}

function Login({ onLogin }: LoginProps)
{
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleLogin = async (event: React.FormEvent) => {
    event.preventDefault()
    setError('')
    setLoading(true)

    try
    {
      const loginUrl =
        (import.meta.env.VITE_STREAMING_SESSION_HTTP_URL || 'http://127.0.0.1:8001') +
        '/api/login/'

      const response = await fetch(loginUrl,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          username: username.trim(),
          password: password.trim(),
        }),
      })

      const data = await response.json()

      if (!response.ok)
      {
        throw new Error(data.detail || data.error || 'Login failed')
      }

      localStorage.setItem('access_token', data.access)
      onLogin()
    }
    catch (error)
    {
      if (error instanceof Error)
      {
        setError(error.message)
      }
      else
      {
        setError('Login failed')
      }
    }
    finally
    {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <h1 className="login-title">Login</h1>

      <form className="login-form" onSubmit={handleLogin}>
        <div className="login-field">
          <label>Username</label>
          <input
            type="text"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            onBlur={() => setUsername(username.trim())}
            required
          />
        </div>

        <div className="login-field">
          <label>Password</label>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            onBlur={() => setPassword(password.trim())}
            required
          />
        </div>

        <button className="login-button" type="submit" disabled={loading}>
          {loading ? 'Logging in...' : 'Login'}
        </button>
      </form>

      {error && <p className="login-error">{error}</p>}
    </div>
  )
}

export default Login
