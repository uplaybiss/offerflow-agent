async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const formData = typeof FormData !== 'undefined' && init.body instanceof FormData
  const response = await fetch(path, {
    credentials: 'include',
    headers: formData ? init.headers : { 'Content-Type': 'application/json', ...(init.headers || {}) },
    ...init,
  })
  if (response.status === 204) return undefined as T
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = body?.detail
    throw new Error(typeof detail === 'object' ? detail.message : detail || `请求失败 (${response.status})`)
  }
  return body as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) => request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  upload: <T>(path: string, body: FormData) => request<T>(path, { method: 'POST', body }),
  stream: async (path: string, body: unknown, onEvent: (event: Record<string, unknown>) => void) => {
    const response = await fetch(path, {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}))
      const detail = payload?.detail
      throw new Error(typeof detail === 'object' ? detail.message : detail || `请求失败 (${response.status})`)
    }
    if (!response.body) throw new Error('浏览器不支持流式响应')
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
      const lines = buffer.split('\n'); buffer = lines.pop() || ''
      for (const line of lines) if (line.trim()) onEvent(JSON.parse(line))
      if (done) break
    }
    if (buffer.trim()) onEvent(JSON.parse(buffer))
  },
}

export const commandId = (prefix: string) => `${prefix}:${crypto.randomUUID()}`

let displayTimeZone = 'Asia/Shanghai'
export const setTimeZone = (value: string) => { displayTimeZone = value || 'Asia/Shanghai' }
export const formatTime = (value: string) => {
  if (!value) return '未设置'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.valueOf())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: displayTimeZone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(parsed)
}

export const toTimeInput = (value: string) => {
  if (!value) return ''
  const parsed = new Date(value)
  if (Number.isNaN(parsed.valueOf())) return value.slice(0, 16)
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: displayTimeZone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(parsed)
  const read = (type: Intl.DateTimeFormatPartTypes) => parts.find(part => part.type === type)?.value || ''
  return `${read('year')}-${read('month')}-${read('day')}T${read('hour')}:${read('minute')}`
}
