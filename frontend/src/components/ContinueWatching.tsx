import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getMovie } from '../services/movieCatalogSocket'
import { createStreamingSessionClient } from '../services/streamingSessionSocket'

interface Movie
{
  id: number
  title: string
  description: string
  genre: string
  duration: number
  release_date: string
  video_url: string
}

interface Session
{
  id: number
  movie_id: number
  playback_position: number
  movie_duration: number
  status: string
  updated_at: string
}

interface ContinueWatchingItem
{
  movie: Movie
  progress: number
}

function ContinueWatching()
{
  const navigate = useNavigate()
  const [items, setItems] = useState<ContinueWatchingItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const client = createStreamingSessionClient()
    let cancelled = false

    const fetchContinueWatching = async () => {
      const token = localStorage.getItem('access_token')

      if (!token)
      {
        setLoading(false)
        return
      }

      try
      {
        await client.connect(token)
        if (cancelled)
        {
          return
        }

        const sessions = await client.listSessions() as Session[]

        const latestSessionsMap = new Map<number, Session>()

        const sortedSessions = [...sessions].sort((a, b) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime() ||
          b.id - a.id
        )

        for (const session of sortedSessions)
        {
          if (!latestSessionsMap.has(session.movie_id))
          {
            latestSessionsMap.set(session.movie_id, session)
          }
        }

        const latestSessions = Array.from(latestSessionsMap.values()).filter(
          (session) =>
            session.status !== 'ended' &&
            session.playback_position > 0 &&
            session.movie_duration > 0 &&
            session.playback_position < session.movie_duration
        )

        const movieResults = await Promise.all(
          latestSessions.map(async (session) => {
            try
            {
              const movie = await getMovie(session.movie_id) as Movie

              const progress = Math.min(
                100,
                (session.playback_position / session.movie_duration) * 100
              )

              return { movie, progress }
            }
            catch
            {
              return null
            }
          })
        )

        const validResults = movieResults.filter(
          (result): result is ContinueWatchingItem => result !== null
        )

        if (!cancelled)
        {
          setItems(validResults)
        }
      }
      catch
      {
        if (!cancelled)
        {
          setError('Failed to load Continue Watching')
        }
      }
      finally
      {
        client.close()
        if (!cancelled)
        {
          setLoading(false)
        }
      }
    }

    fetchContinueWatching()

    return () => {
      cancelled = true
      client.close()
    }
  }, [])

  return (
    <div className="continue-watching-page">
      <div className="continue-watching-header">
        <div>
          <h1 className="continue-watching-page-title">Continue Watching</h1>
          <p className="continue-watching-page-subtitle">
            Pick up where you left off.
          </p>
        </div>

        <button
          className="continue-watching-browse-button"
          onClick={() => navigate('/search')}
        >
          Browse Movies
        </button>
      </div>

      {loading && (
        <p className="browse-status">Loading Continue Watching...</p>
      )}

      {error && (
        <p className="browse-error">{error}</p>
      )}

      {!loading && !error && items.length === 0 && (
        <div className="continue-watching-empty">
          <h2>Nothing to continue yet.</h2>
          <p>Start watching a movie and your progress will appear here.</p>
          <button
            className="continue-watching-browse-button"
            onClick={() => navigate('/search')}
          >
            Browse Movies
          </button>
        </div>
      )}

      {!loading && !error && items.length > 0 && (
        <div className="continue-watching-grid">
          {items.map((item) => (
            <div
              className="continue-watching-card"
              key={item.movie.id}
              onClick={() => navigate(`/watch/${item.movie.id}`)}
            >
              <div className="continue-watching-card-content">
                <h3 className="continue-watching-card-title">
                  {item.movie.title}
                </h3>
                <p className="continue-watching-card-meta">
                  {item.movie.genre} · {item.movie.duration} seconds
                </p>
                <div className="continue-watching-progress-track">
                  <div
                    className="continue-watching-progress-bar"
                    style={{ width: `${item.progress}%` }}
                  />
                </div>
                <p className="continue-watching-progress-text">
                  {Math.round(item.progress)}% watched
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default ContinueWatching