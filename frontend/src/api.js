const API_BASE = '/api'

let authToken = localStorage.getItem('rag_auth_token') || null

export const api = {
  setToken(token) {
    authToken = token
    if (token) {
      localStorage.setItem('rag_auth_token', token)
    } else {
      localStorage.removeItem('rag_auth_token')
    }
  },

  getToken() {
    return authToken
  },

  _getHeaders() {
    const headers = { 'Content-Type': 'application/json' }
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`
    }
    return headers
  },

  async get(endpoint) {
    const res = await fetch(`${API_BASE}${endpoint}`, {
      headers: this._getHeaders()
    })
    if (res.status === 401) {
      this.setToken(null)
      window.dispatchEvent(new CustomEvent('auth:logout'))
      throw new Error('请重新登录')
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: `HTTP ${res.status}` }))
      throw new Error(err.message || `HTTP ${res.status}`)
    }
    return res.json()
  },

  async post(endpoint, data) {
    const res = await fetch(`${API_BASE}${endpoint}`, {
      method: 'POST',
      headers: this._getHeaders(),
      body: JSON.stringify(data)
    })
    if (res.status === 401) {
      this.setToken(null)
      window.dispatchEvent(new CustomEvent('auth:logout'))
      throw new Error('请重新登录')
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: `HTTP ${res.status}` }))
      throw new Error(err.message || `HTTP ${res.status}`)
    }
    return res.json()
  },

  async delete(endpoint) {
    const res = await fetch(`${API_BASE}${endpoint}`, {
      method: 'DELETE',
      headers: this._getHeaders()
    })
    if (res.status === 401) {
      this.setToken(null)
      window.dispatchEvent(new CustomEvent('auth:logout'))
      throw new Error('请重新登录')
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  },

  async uploadFile(endpoint, file) {
    const formData = new FormData()
    formData.append('file', file)
    const res = await fetch(`${API_BASE}${endpoint}`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${authToken}` },
      body: formData
    })
    if (res.status === 401) {
      this.setToken(null)
      window.dispatchEvent(new CustomEvent('auth:logout'))
      throw new Error('请重新登录')
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  },

  async *streamChat(message, conversationId) {
    const response = await fetch(`${API_BASE}/chat/stream`, {
      method: 'POST',
      headers: this._getHeaders(),
      body: JSON.stringify({ message, conversation_id: conversationId })
    })

    if (response.status === 401) {
      this.setToken(null)
      window.dispatchEvent(new CustomEvent('auth:logout'))
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      const text = decoder.decode(value)
      const lines = text.split('\n').filter(l => l.trim())

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6))
            yield data
          } catch {}
        }
      }
    }
  },

  async login(username, password) {
    const data = await this.post('/auth/login', { username, password })
    this.setToken(data.access_token)
    return data
  },

  async register(username, password) {
    const data = await this.post('/auth/register', { username, password })
    this.setToken(data.access_token)
    return data
  },

  async logout() {
    try {
      await this.post('/auth/logout')
    } catch {}
    this.setToken(null)
  },

  async getCurrentUser() {
    if (!authToken) return null
    try {
      return await this.get('/auth/me')
    } catch {
      return null
    }
  }
}
