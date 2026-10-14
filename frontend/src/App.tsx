import { useCallback, useEffect, useState } from 'react'
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom'
import Browse from './components/Browse'
import ContinueWatching from './components/ContinueWatching'
import MovieDetails from './components/Moviedetails'
import Login from './components/Login'
import Watch from './components/Watch'
import {
  getAccessTokenExpiration,
  hasUnexpiredAccessToken,
} from './services/authToken'

function App()
{
  const [isAuthenticated, setIsAuthenticated] = useState(() => {
    const token = localStorage.getItem('access_token')
    if (hasUnexpiredAccessToken(token)) {
      return true
    }

    if (token) {
      localStorage.removeItem('access_token')
    }
    return false
  })
  const navigate = useNavigate()
  const location = useLocation()

  const handleLogin = () => {
    setIsAuthenticated(true)
    navigate('/')
  }

  const handleLogout = useCallback(() => {
    localStorage.removeItem('access_token')
    setIsAuthenticated(false)
    navigate('/login', { replace: true })
  }, [navigate])

  useEffect(() => {
    if (!isAuthenticated) {
      return
    }

    const token = localStorage.getItem('access_token')
    const expiration = getAccessTokenExpiration(token)
    const delay =
      expiration === null ? 0 : Math.max(0, expiration * 1000 - Date.now())
    const timeout = window.setTimeout(handleLogout, delay)
    return () => window.clearTimeout(timeout)
  }, [isAuthenticated, handleLogout])

  return (
    <div>
      <nav className="app-nav">
        {!isAuthenticated && location.pathname !== '/login' && (
          <button className="nav-button" onClick={() => navigate('/login')}>
            Login
          </button>
        )}

        {isAuthenticated && (
          <button className="nav-button logout-button" onClick={handleLogout}>
            Logout
          </button>
        )}
      </nav>

      <Routes>
        <Route
          path="/login"
          element={
            isAuthenticated ? (
              <Navigate to="/" replace />
            ) : (
              <Login onLogin={handleLogin} />
            )
          }
        />

        <Route
          path="/"
          element={
            isAuthenticated ? (
              <ContinueWatching />
            ) : (
              <Navigate to="/login" replace />
            )
          }
        />

        <Route
          path="/search"
          element={
            isAuthenticated ? (
              <Browse />
            ) : (
              <Navigate to="/login" replace />
            )
          }
        />

        <Route
          path="/movie/:id"
          element={
            isAuthenticated ? (
              <MovieDetails />
            ) : (
              <Navigate to="/login" replace />
            )
          }
        />

        <Route
          path="/watch/:id"
          element={
            isAuthenticated ? (
              <Watch />
            ) : (
              <Navigate to="/login" replace />
            )
          }
        />
      </Routes>
    </div>
  )
}

export default App