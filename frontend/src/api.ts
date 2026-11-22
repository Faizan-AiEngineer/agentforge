import { useQuery } from '@tanstack/react-query'

export const base = '/api/v1'

export async function request<T>(path: string, method = 'GET', body?: unknown, extraHeaders?: Record<string, string>): Promise<T> {
  let response: Response
  try {
    response = await fetch(base + path, {
      method,
      headers: { ...(body === undefined ? {} : { 'Content-Type': 'application/json' }), ...extraHeaders },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new Error('AgentForge could not reach the local backend.')
  }
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = data?.detail
    const message = typeof detail === 'string' ? detail
      : Array.isArray(detail) ? detail.map((item) => [...item.location, item.message].join(' · ')).join('\n')
        : 'The local service did not return a valid response.'
    throw new Error(message)
  }
  return data as T
}

export function useApi<T>(path: string, refresh = 0, enabled = true) {
  return useQuery({ queryKey: [path], queryFn: () => request<T>(path), enabled, refetchInterval: refresh || false })
}
