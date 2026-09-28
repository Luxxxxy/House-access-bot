import type { ApiError, AuthContext } from './types';

const API = import.meta.env.VITE_API_BASE_URL || '/api/v1';

export async function api<T>(path: string, auth: AuthContext, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (auth.authorization) headers.set('Authorization', auth.authorization);
  if (auth.demoUserId) headers.set('X-Demo-User', String(auth.demoUserId));
  const response = await fetch(`${API}${path}`, { ...init, headers });
  if (!response.ok) {
    let message = `Ошибка запроса (${response.status})`;
    try {
      const data = await response.json();
      message = data?.error?.message || data?.detail || message;
    } catch { /* use generic message */ }
    const error = new Error(String(message)) as ApiError;
    error.status = response.status;
    throw error;
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const json = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
});
