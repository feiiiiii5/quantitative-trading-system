import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios';

const MAX_RETRIES = 3;
const RETRY_BASE_DELAY = 1000;

interface RetryConfig extends InternalAxiosRequestConfig {
  __retryCount?: number;
}

const etagCache = new Map<string, { etag: string; data: unknown; timestamp: number }>();
const ETAG_CACHE_MAX = 64;
const ETAG_CACHE_TTL_MS = 30_000;

const pendingRequests = new Map<string, AbortController>();

function cancelPending(url: string): void {
  const existing = pendingRequests.get(url);
  if (existing) {
    existing.abort();
    pendingRequests.delete(url);
  }
}

function pruneEtagCache(): void {
  if (etagCache.size <= ETAG_CACHE_MAX) return;
  const now = Date.now();
  const expired = [...etagCache.entries()]
    .filter(([, v]) => now - v.timestamp > ETAG_CACHE_TTL_MS)
    .map(([k]) => k);
  for (const k of expired) etagCache.delete(k);
  if (etagCache.size > ETAG_CACHE_MAX) {
    const sorted = [...etagCache.entries()].sort((a, b) => a[1].timestamp - b[1].timestamp);
    const toRemove = sorted.slice(0, etagCache.size - ETAG_CACHE_MAX);
    for (const [k] of toRemove) etagCache.delete(k);
  }
}

const apiClient = axios.create({
  baseURL: '/api',
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
  validateStatus: (status) => (status >= 200 && status < 300) || status === 304,
});

apiClient.interceptors.response.use(
  (response) => {
    if (response.status === 304) {
      const cacheKey = response.config.url ?? '';
      const cached = etagCache.get(cacheKey);
      if (cached) {
        response.data = cached.data;
        return response;
      }
      return Promise.reject(new Error('304 with no cache'));
    }

    const payload = response.data;
    if (payload && typeof payload === 'object' && 'success' in payload) {
      if (payload.success) {
        response.data = 'data' in payload ? payload.data : null;
      } else {
        return Promise.reject(new Error(payload.error ?? 'API request failed'));
      }
    }

    const etag = response.headers?.['etag'];
    if (etag && response.config.method === 'get') {
      const cacheKey = response.config.url ?? '';
      etagCache.set(cacheKey, { etag, data: response.data, timestamp: Date.now() });
      pruneEtagCache();
    }

    return response;
  },
  async (error: AxiosError) => {
    const config = error.config as RetryConfig | undefined;
    if (!config) return Promise.reject(error);

    const isRetryable =
      config.method === 'get' &&
      !axios.isCancel(error) &&
      (error.code === 'ERR_NETWORK' || (error.response?.status ?? 0) >= 500);

    if (isRetryable) {
      const retryCount = config.__retryCount ?? 0;
      if (retryCount < MAX_RETRIES) {
        config.__retryCount = retryCount + 1;
        const delay = RETRY_BASE_DELAY * Math.pow(2, retryCount);
        await new Promise(r => setTimeout(r, delay));
        return apiClient.request(config);
      }
    }

    return Promise.reject(error);
  },
);

export async function apiGet<T>(url: string, params?: Record<string, unknown>, timeout?: number): Promise<T> {
  cancelPending(url);
  const ac = new AbortController();
  pendingRequests.set(url, ac);

  const cached = etagCache.get(url);
  const headers: Record<string, string> = {};
  if (cached?.etag) {
    headers['If-None-Match'] = cached.etag;
  }
  try {
    const res = await apiClient.get<T>(url, { params, timeout, headers, signal: ac.signal });
    return res.data;
  } catch (err) {
    if (axios.isCancel(err)) {
      return new Promise<T>(() => {});
    }
    throw err;
  } finally {
    if (pendingRequests.get(url) === ac) {
      pendingRequests.delete(url);
    }
  }
}

export async function apiPost<T>(url: string, data?: unknown, timeout?: number): Promise<T> {
  const res = await apiClient.post<T>(url, data, { timeout });
  return res.data;
}
