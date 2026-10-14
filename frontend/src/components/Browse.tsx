import { useEffect, useState } from 'react'
import MovieCard from './MovieCard'
import { listMovies } from '../services/movieCatalogSocket'
import { useNavigate } from 'react-router-dom'

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

function Browse()
{
  const navigate = useNavigate()
  const [movies, setMovies] = useState<Movie[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [genre, setGenre] = useState('')

  useEffect(() => {
    const fetchMovies = async () => {
      setLoading(true)
      setError('')

      try
      {
        const data = await listMovies(search, genre)
        setMovies(data as Movie[])
      }
      catch
      {
        setError('Failed to load movies')
      }
      finally
      {
        setLoading(false)
      }
    }

    fetchMovies()
  }, [search, genre])

  return (
    <div className="browse-page">
      <h1 className="browse-title">Browse Movies</h1>
      <p className="browse-subtitle">Search and discover movies from the catalog.</p>
      <button
        className="browse-continue-button"
        onClick={() => navigate('/')}
      >
        Back to Continue Watching
      </button>
      <div className="browse-controls">
        <input
          type="text"
          placeholder="Search movies..."
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select
          value={genre}
          onChange={(event) => setGenre(event.target.value)}
        >
          <option value="">All Genres</option>
          <option value="Adventure">Adventure</option>
          <option value="Drama">Drama</option>
          <option value="Nature">Nature</option>
          <option value="Romance">Romance</option>
          <option value="Mystery">Mystery</option>
          <option value="Thriller">Thriller</option>
          <option value="Documentary">Documentary</option>
          <option value="Experimental">Experimental</option>
          <option value="Urban">Urban</option>
          <option value="Family">Family</option>
        </select>
      </div>
      {loading && <p className="browse-status">Loading movies...</p>}
      {error && <p className="browse-error">{error}</p>}
      {!loading && !error &&
      (
        <div className="movie-grid">
          {movies.map((movie) =>
          (
            <MovieCard
              key={movie.id}
              movie={movie}
              onSelect={() => navigate(`/movie/${movie.id}`)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export default Browse