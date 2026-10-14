import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getMovie } from '../services/movieCatalogSocket'
import {
  createStreamingSessionClient,
  type StreamingSessionClient,
  type Session,
} from '../services/streamingSessionSocket'

const pauseSessionOnLeave = async (
  client: StreamingSessionClient | null,
  session: Session | null,
  video: HTMLVideoElement | null,
) => {
  if (!session || session.status === 'ended' || !video || video.ended || !client)
  {
    return
  }

  const position = Math.floor(video.currentTime)

  try
  {
    await client.updateSession(session.id, {
      status: 'paused',
      playback_position: position,
    })
  }
  catch
  {
    // The page is being left, so there is no UI state to update.
  }
}

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

function Watch()
{
  const { id } = useParams()
  const navigate = useNavigate()
  const [movie, setMovie] = useState<Movie | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [session, setSession] = useState<Session | null>(null)
  const sessionRef = useRef<Session | null>(null)
  const sessionClientRef = useRef<StreamingSessionClient | null>(null)
  const sessionCreationMovieId = useRef<number | null>(null)
  const completedSessionIdRef = useRef<number | null>(null)
  const replacementSessionPromiseRef = useRef<Promise<Session> | null>(null)
  const lastSyncedPosition = useRef<number | null>(null)
  const pendingSyncPositionRef = useRef<number | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const isUnmountingRef = useRef(false)
  const sessionRequestChainRef = useRef<Promise<void>>(Promise.resolve())
  const resumeSessionIdRef = useRef<number | null>(null)
  const [socketReady, setSocketReady] = useState(false)

  useEffect(() => {
    const fetchMovie = async () => {
      if (isUnmountingRef.current)
      {
        return
      }
      try
      {
        const data = await getMovie(Number(id))
        setMovie(data as Movie)
      }
      catch
      {
        setError('Failed to load movie')
      }
      finally
      {
        setLoading(false)
      }
    }

    fetchMovie()
  }, [id])

  useEffect(() => {
    const token = localStorage.getItem('access_token')
    const client = createStreamingSessionClient()
    sessionClientRef.current = client
    isUnmountingRef.current = false

    const connect = async () => {
      if (!token)
      {
        setError('Failed to load streaming session')
        return
      }

      try
      {
        await client.connect(token)
        if (!isUnmountingRef.current)
        {
          setSocketReady(true)
        }
      }
      catch
      {
        if (!isUnmountingRef.current)
        {
          setError('Failed to load streaming session')
        }
      }
    }

    connect()

    const currentVideo = videoRef.current
    const handlePageLeave = () => {
      pauseSessionOnLeave(sessionClientRef.current, sessionRef.current, currentVideo)
    }

    window.addEventListener('pagehide', handlePageLeave)

    return () => {
      isUnmountingRef.current = true
      window.removeEventListener('pagehide', handlePageLeave)
      void pauseSessionOnLeave(
        sessionClientRef.current,
        sessionRef.current,
        currentVideo,
      ).finally(() => {
        client.close()
      })
    }
  }, [])

  useEffect(() => {
    if (!movie || !socketReady)
    {
      return
    }

    if (sessionCreationMovieId.current === movie.id)
    {
      return
    }

    sessionCreationMovieId.current = movie.id
    const loadSession = async () => {
      if (isUnmountingRef.current)
      {
        return
      }
      try
      {
        const client = sessionClientRef.current

        if (!client)
        {
          throw new Error('Failed to load sessions')
        }

        const sessions = await client.listSessions()

        const movieSessions = sessions.filter(
          (item: Session) => item.movie_id === movie.id && item.status !== 'ended'
        )

        movieSessions.sort(
          (a: Session, b: Session) =>
            new Date(b.updated_at).getTime() -
            new Date(a.updated_at).getTime()
        )

        if (movieSessions.length > 0)
        {
          sessionRef.current = movieSessions[0]
          setSession(movieSessions[0])
          return
        }

        const data = await client.createSession(movie.id, movie.duration)
        sessionRef.current = data
        setSession(data)
      }
      catch
      {
        setError('Failed to load streaming session')
      }
    }

    loadSession()
  }, [movie, socketReady])

  useEffect(() => {
    if (!session)
    {
      return
    }

    if (resumeSessionIdRef.current === session.id)
    {
      return
    }

    const video = videoRef.current

    if (!video)
    {
      return
    }

    resumeSessionIdRef.current = session.id

    const setResumePosition = () => {
      if (session.playback_position > 0 && !video.ended)
      {
        video.currentTime = session.playback_position
        lastSyncedPosition.current = session.playback_position
      }
    }

    if (video.readyState >= 1)
    {
      setResumePosition()
      return
    }

    video.addEventListener('loadedmetadata', setResumePosition)

    return () => {
      video.removeEventListener('loadedmetadata', setResumePosition)
    }
  }, [session])

  const updateSession = (updates: {
    status?: string
    playback_position?: number
  }) => {
    const currentSession = sessionRef.current

    if (!currentSession || isUnmountingRef.current)
    {
      return
    }

    if (
      currentSession.status === 'ended' ||
      completedSessionIdRef.current === currentSession.id
    )
    {
      return
    }

    const client = sessionClientRef.current

    const request = sessionRequestChainRef.current
      .catch(() => {
        // Continue even if an earlier session update failed.
      })
      .then(async () => {
        if (isUnmountingRef.current || !client)
        {
          return
        }

        const data = await client.updateSession(currentSession.id, updates)

        if (isUnmountingRef.current)
        {
          return
        }

        if (
          updates.playback_position !== undefined &&
          pendingSyncPositionRef.current === updates.playback_position
        )
        {
          pendingSyncPositionRef.current = null
          lastSyncedPosition.current = updates.playback_position
        }

        if (sessionRef.current?.id === currentSession.id)
        {
          sessionRef.current = data
          setSession(data)
        }
      })
      .catch(() => {
        if (!isUnmountingRef.current)
        {
          setError('Failed to update streaming session')
        }
      })

    sessionRequestChainRef.current = request
  }

  const handlePlay = async () => {
    const currentSession = sessionRef.current

    if (
      !currentSession ||
      (currentSession.status !== 'ended' &&
        completedSessionIdRef.current !== currentSession.id)
    )
    {
      updateSession({ status: 'playing' })
      return
    }

    const client = sessionClientRef.current

    if (!client || !movie)
    {
      setError('Failed to load streaming session')
      return
    }

    let replacementPromise = replacementSessionPromiseRef.current

    if (!replacementPromise)
    {
      replacementPromise = client.createSession(movie.id, movie.duration)
      replacementSessionPromiseRef.current = replacementPromise
    }

    try
    {
      const replacementSession = await replacementPromise

      if (isUnmountingRef.current)
      {
        return
      }

      if (sessionRef.current?.id === currentSession.id)
      {
        sessionRef.current = replacementSession
        setSession(replacementSession)
        completedSessionIdRef.current = null
        const position = Math.floor(videoRef.current?.currentTime ?? 0)
        updateSession(
          position > 0
            ? { status: 'playing', playback_position: position }
            : { status: 'playing' }
        )
      }
    }
    catch
    {
      if (!isUnmountingRef.current)
      {
        setError('Failed to load streaming session')
      }
    }
    finally
    {
      if (replacementSessionPromiseRef.current === replacementPromise)
      {
        replacementSessionPromiseRef.current = null
      }
    }
  }

  const handleBack = async () => {
    await pauseSessionOnLeave(
      sessionClientRef.current,
      sessionRef.current,
      videoRef.current,
    )
    navigate(`/movie/${id}`)
  }

  if (loading)
  {
    return <p>Loading movie...</p>
  }

  if (error)
  {
    return <p>{error}</p>
  }

  if (!movie)
  {
    return <p>Movie not found</p>
  }

  return (
    <div>
      <h1 style={{ marginLeft: '80px' }}>{movie.title}</h1>

      <div
        className="watch-player-container"
        style={{
          width: '100%',
          maxWidth: '1140px',
          margin: '0 auto',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'stretch',
        }}
      >
        <button
          className="watch-back-button"
          onClick={handleBack}
          style={{
            position: 'static',
            top: 'auto',
            right: 'auto',
            bottom: 'auto',
            left: 'auto',
            float: 'none',
            alignSelf: 'flex-start',
            display: 'block',
            width: 'fit-content',
            margin: '0 0 16px 0',
            padding: '10px 18px',
            boxSizing: 'border-box',
            transform: 'none',
          }}
        >
          Back to Movie
        </button>

        <video
          controls
          ref={videoRef}
          width="800"
          style={{
            display: 'block',
            width: '100%',
            maxWidth: '100%',
            height: 'auto',
            margin: 0,
          }}
          onPlay={handlePlay}
          onPause={(event) => {
            if (event.currentTarget.ended)
            {
              return
            }

            const position = Math.floor(event.currentTarget.currentTime)
            pendingSyncPositionRef.current = null
            lastSyncedPosition.current = position

            updateSession({
              status: 'paused',
              playback_position: position,
            })
          }}
          onTimeUpdate={(event) => {
            const position = Math.floor(event.currentTarget.currentTime)

            if (
              position > 0 &&
              position % 5 === 0 &&
              lastSyncedPosition.current !== position &&
              pendingSyncPositionRef.current !== position
            )
            {
              pendingSyncPositionRef.current = position

              updateSession({
                playback_position: position,
              })
            }
          }}
          onEnded={(event) => {
            const position = Math.floor(event.currentTarget.duration)
            pendingSyncPositionRef.current = null
            lastSyncedPosition.current = position

            updateSession({
              status: 'ended',
              playback_position: position,
            })

            const currentSession = sessionRef.current
            if (currentSession)
            {
              completedSessionIdRef.current = currentSession.id
              sessionRef.current = {
                ...currentSession,
                playback_position: position,
                status: 'ended',
              }
              setSession(sessionRef.current)
            }
          }}
        >
          <source src={movie.video_url} type="video/mp4" />
          Your browser does not support the video element.
        </video>
      </div>
    </div>
  )
}

export default Watch