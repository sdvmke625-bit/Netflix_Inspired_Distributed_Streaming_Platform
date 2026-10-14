

const MOVIE_CATALOG_WS_URL =
  import.meta.env.VITE_MOVIE_CATALOG_WS_URL || 'ws://127.0.0.1:8000/ws/movies/'

type MovieCatalogRequest = {
  operation: 'list_movies' | 'get_movie'
  title?: string
  genre?: string
  movie_id?: number
}

type MovieCatalogResponse = {
  status: 'success' | 'error' | 'not_found'
  operation?: string
  data?: unknown
  message?: string
}

function sendMovieCatalogRequest(request: MovieCatalogRequest): Promise<MovieCatalogResponse> {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(MOVIE_CATALOG_WS_URL)
    let settled = false

    const settle = (callback: () => void) => {
      if (settled) {
        return
      }

      settled = true
      callback()
    }

    socket.onopen = () => {
      socket.send(JSON.stringify(request))
    }

    socket.onmessage = (event) => {
      let response: MovieCatalogResponse

      try {
        response = JSON.parse(event.data) as MovieCatalogResponse
      } catch {
        settle(() => reject(new Error('Invalid response from Movie Catalog')))
        socket.close()
        return
      }

      settle(() => resolve(response))
      socket.close()
    }

    socket.onerror = () => {
      settle(() => reject(new Error('Could not connect to Movie Catalog')))
    }

    socket.onclose = () => {
      if (!settled) {
        settle(() => reject(new Error('Movie Catalog WebSocket connection closed unexpectedly')))
      }
    }
  })
}

export async function listMovies(title = '', genre = ''): Promise<unknown[]> {
  const response = await sendMovieCatalogRequest({
    operation: 'list_movies',
    title,
    genre,
  })

  if (response.status !== 'success') {
    throw new Error(response.message || 'Failed to load movies')
  }

  return Array.isArray(response.data) ? response.data : []
}

export async function getMovie(movieId: number): Promise<unknown> {
  const response = await sendMovieCatalogRequest({
    operation: 'get_movie',
    movie_id: movieId,
  })

  if (response.status === 'not_found') {
    throw new Error(response.message || 'Movie not found')
  }

  if (response.status !== 'success') {
    throw new Error(response.message || 'Failed to load movie')
  }

  return response.data
}