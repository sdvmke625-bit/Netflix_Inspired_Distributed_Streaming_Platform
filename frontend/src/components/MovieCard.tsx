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

interface MovieCardProps 
{
  movie: Movie
  onSelect: (movie: Movie) => void
}

function MovieCard({ movie, onSelect }: MovieCardProps) 
{
  return (
  <div className="movie-card" onClick={() => onSelect(movie)}>
    <h2 className="movie-card-title">{movie.title}</h2>
    <p className="movie-card-meta">Genre: {movie.genre}</p>
    <p className="movie-card-meta">Duration: {movie.duration} seconds</p>
  </div>
)
}

export default MovieCard