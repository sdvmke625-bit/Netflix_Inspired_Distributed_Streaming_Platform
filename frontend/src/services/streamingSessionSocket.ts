const STREAMING_SESSION_WS_URL =
  import.meta.env.VITE_STREAMING_SESSION_WS_URL || 'ws://127.0.0.1:8001/ws/sessions/'

export interface Session {
  id: number
  movie_id: number
  movie_duration: number
  playback_position: number
  status: string
  started_at?: string
  updated_at: string
  user?: number
}

type PendingRequest = {
  resolve: (value: unknown) => void
  reject: (reason: unknown) => void
  operation?: string
}

export interface StreamingSessionClient {
  connect(token?: string): Promise<void>
  listSessions(): Promise<Session[]>
  createSession(movieId: number, movieDuration?: number): Promise<Session>
  updateSession(
    sessionId: number,
    updates: { playback_position?: number; status?: string }
  ): Promise<Session>
  close(): void
}

class StreamingSessionClientImpl implements StreamingSessionClient {
  private socket: WebSocket | null = null
  private pendingRequests: PendingRequest[] = []
  private isAuthenticated = false
  private isClosed = false

  connect(authToken?: string): Promise<void> {
    const token = authToken || localStorage.getItem('access_token')

    if (!token) {
      return Promise.reject(new Error('Authentication required'))
    }

    this.isClosed = false
    this.isAuthenticated = false

    return new Promise((resolve, reject) => {
      try {
        this.socket = new WebSocket(STREAMING_SESSION_WS_URL)
      } catch {
        reject(new Error('Could not connect to Streaming Session Service'))
        return
      }

      this.pendingRequests.push({
        resolve: () => resolve(),
        reject,
        operation: 'authenticate',
      })

      this.socket.onopen = () => {
        try {
          this.socket?.send(
            JSON.stringify({
              operation: 'authenticate',
              token,
            })
          )
        } catch {
          this.drainPending(new Error('Failed to send authentication message'))
        }
      }

      this.socket.onmessage = (event) => {
        let response: {
          status?: string
          operation?: string
          data?: unknown
          message?: string
        }

        try {
          response = JSON.parse(event.data)
        } catch {
          const pending = this.pendingRequests.shift()
          pending?.reject(new Error('Invalid response from Streaming Session Service'))
          return
        }

        const pending = this.pendingRequests.shift()
        if (!pending) {
          return
        }

        if (response.status !== 'success') {
          pending.reject(new Error(response.message || 'Streaming session request failed'))
          return
        }

        if (pending.operation === 'authenticate') {
          this.isAuthenticated = true
          pending.resolve(undefined)
          return
        }

        pending.resolve(response.data)
      }

      this.socket.onerror = () => {
        if (!this.isClosed) {
          this.drainPending(new Error('Could not connect to Streaming Session Service'))
        }
      }

      this.socket.onclose = () => {
        if (!this.isClosed) {
          this.drainPending(
            new Error('Streaming Session WebSocket connection closed unexpectedly')
          )
        }
      }
    })
  }

  private drainPending(error: Error) {
    while (this.pendingRequests.length > 0) {
      const pending = this.pendingRequests.shift()
      pending?.reject(error)
    }
  }

  private sendOperation<T>(operation: string, payload: Record<string, unknown>): Promise<T> {
    if (this.isClosed || !this.socket || this.socket.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error('Streaming Session WebSocket is not connected'))
    }

    if (!this.isAuthenticated) {
      return Promise.reject(new Error('Authentication required'))
    }

    return new Promise<T>((resolve, reject) => {
      this.pendingRequests.push({
        resolve: resolve as (value: unknown) => void,
        reject,
        operation,
      })

      try {
        this.socket?.send(
          JSON.stringify({
            operation,
            ...payload,
          })
        )
      } catch {
        const pending = this.pendingRequests.pop()
        pending?.reject(new Error(`Failed to send ${operation} request`))
      }
    })
  }

  listSessions(): Promise<Session[]> {
    return this.sendOperation<Session[]>('list_sessions', {}).then((data) =>
      Array.isArray(data) ? data : []
    )
  }

  createSession(movieId: number, movieDuration?: number): Promise<Session> {
    const payload: Record<string, unknown> = { movie_id: movieId }
    if (movieDuration !== undefined) {
      payload.movie_duration = movieDuration
    }
    return this.sendOperation<Session>('create_session', payload)
  }

  updateSession(
    sessionId: number,
    updates: { playback_position?: number; status?: string }
  ): Promise<Session> {
    const payload: Record<string, unknown> = {
      session_id: sessionId,
      ...updates,
    }
    return this.sendOperation<Session>('update_session', payload)
  }

  close(): void {
    this.isClosed = true
    if (this.socket) {
      this.socket.onopen = null
      this.socket.onmessage = null
      this.socket.onerror = null
      this.socket.onclose = null
      try {
        this.socket.close()
      } catch {
        // Ignore close error on teardown
      }
      this.socket = null
    }
    this.drainPending(new Error('Streaming Session WebSocket closed'))
  }
}

export function createStreamingSessionClient(): StreamingSessionClient {
  return new StreamingSessionClientImpl()
}

export async function listSessions(): Promise<Session[]> {
  const client = createStreamingSessionClient()
  try {
    await client.connect()
    return await client.listSessions()
  } finally {
    client.close()
  }
}

export async function createSession(
  movieId: number,
  movieDuration?: number
): Promise<Session> {
  const client = createStreamingSessionClient()
  try {
    await client.connect()
    return await client.createSession(movieId, movieDuration)
  } finally {
    client.close()
  }
}

export async function updateSession(
  sessionId: number,
  updates: {
    status?: string
    playback_position?: number
  }
): Promise<Session> {
  const client = createStreamingSessionClient()
  try {
    await client.connect()
    return await client.updateSession(sessionId, updates)
  } finally {
    client.close()
  }
}
