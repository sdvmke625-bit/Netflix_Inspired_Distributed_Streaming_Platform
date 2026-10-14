import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getMovie } from '../services/movieCatalogSocket'

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

function MovieDetails()
{
  const { id } = useParams()
  const navigate = useNavigate()
  const [movie, setMovie] = useState<Movie | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const fetchMovie = async () => {
      try
      {
        const data = await getMovie(Number(id))
        setMovie(data as Movie)
      }
      catch
      {
        setError('Failed to load movie details')
      }
      finally
      {
        setLoading(false)
      }
    }

    fetchMovie()
  }, [id])
  if (loading)
  {
    return <p className="details-status">Loading movie details...</p>
  }
  if (error)
  {
    return <p className="details-error">{error}</p>
  }
  if (!movie)
  {
    return <p className="details-error">Movie not found</p>
  }
  return (
    <div className="movie-details">
      <h1 className="details-title">{movie.title}</h1>
      <p className="details-meta">Genre: {movie.genre}</p>
      <p className="details-meta">Duration: {movie.duration} seconds</p>
      <p className="details-meta">Release Date: {movie.release_date}</p>
      <p className="details-description">{movie.description}</p>
      <button className="details-watch-button" onClick={() => navigate(`/watch/${movie.id}`)}>
        Watch
      </button>
      <button className="details-back-button" onClick={() => navigate('/search')}>
        Back to Movies
      </button>
    </div>
  )
}

export default MovieDetails
