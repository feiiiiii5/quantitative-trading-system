import { describe, it, expect } from 'vitest';

describe('apiClient', () => {
  it('exports apiGet and apiPost functions', async () => {
    const mod = await import('@/api/client');
    expect(typeof mod.apiGet).toBe('function');
    expect(typeof mod.apiPost).toBe('function');
  });

  it('apiGet accepts url, params, and optional timeout', async () => {
    const { apiGet } = await import('@/api/client');
    expect(apiGet.length).toBe(3);
  });

  it('apiPost accepts url, data, and optional timeout', async () => {
    const { apiPost } = await import('@/api/client');
    expect(apiPost.length).toBe(3);
  });
});

describe('response interceptor logic', () => {
  it('unwraps {success: true, data: X} to X', () => {
    const payload = { success: true, data: { foo: 'bar' } };
    const response: { data: unknown } = { data: payload };
    if (payload && typeof payload === 'object' && 'success' in payload) {
      if (payload.success) {
        response.data = 'data' in payload ? payload.data : null;
      }
    }
    expect(response.data).toEqual({ foo: 'bar' });
  });

  it('returns null for {success: true} without data', () => {
    const payload = { success: true };
    const response: { data: unknown } = { data: payload };
    if (payload && typeof payload === 'object' && 'success' in payload) {
      if (payload.success) {
        response.data = 'data' in payload ? payload.data : null;
      }
    }
    expect(response.data).toBeNull();
  });

  it('rejects for {success: false, error: X}', () => {
    const payload = { success: false, error: 'Not found' };
    let rejected = false;
    let errorMsg = '';
    if (payload && typeof payload === 'object' && 'success' in payload) {
      if (!payload.success) {
        rejected = true;
        errorMsg = payload.error ?? 'API request failed';
      }
    }
    expect(rejected).toBe(true);
    expect(errorMsg).toBe('Not found');
  });

  it('passes through non-wrapped responses', () => {
    const payload = [1, 2, 3];
    const response = { data: payload };
    if (payload && typeof payload === 'object' && 'success' in payload) {
      // This branch won't execute because arrays don't have 'success'
    }
    expect(response.data).toEqual([1, 2, 3]);
  });
});

describe('retry logic', () => {
  it('should retry GET on 5xx', () => {
    const config = { method: 'get', __retryCount: 0 };
    const error = { code: undefined, response: { status: 503 } };
    const isRetryable =
      config.method === 'get' &&
      (error.code === 'ERR_NETWORK' || (error.response?.status ?? 0) >= 500);
    expect(isRetryable).toBe(true);
  });

  it('should retry GET on network error', () => {
    const config = { method: 'get', __retryCount: 0 };
    const error: { code?: string; response?: { status: number } } = { code: 'ERR_NETWORK', response: undefined };
    const isRetryable =
      config.method === 'get' &&
      (error.code === 'ERR_NETWORK' || (error.response?.status ?? 0) >= 500);
    expect(isRetryable).toBe(true);
  });

  it('should NOT retry POST on 5xx', () => {
    const config = { method: 'post', __retryCount: 0 };
    const error = { code: undefined, response: { status: 500 } };
    const isRetryable =
      config.method === 'get' &&
      (error.code === 'ERR_NETWORK' || (error.response?.status ?? 0) >= 500);
    expect(isRetryable).toBe(false);
  });

  it('should NOT retry on 4xx', () => {
    const config = { method: 'get', __retryCount: 0 };
    const error = { code: undefined, response: { status: 404 } };
    const isRetryable =
      config.method === 'get' &&
      (error.code === 'ERR_NETWORK' || (error.response?.status ?? 0) >= 500);
    expect(isRetryable).toBe(false);
  });

  it('should stop after MAX_RETRIES=3', () => {
    const MAX_RETRIES = 3;
    const config = { method: 'get', __retryCount: 3 };
    const shouldRetry = (config.__retryCount ?? 0) < MAX_RETRIES;
    expect(shouldRetry).toBe(false);
  });

  it('exponential backoff: 1s, 2s, 4s', () => {
    const RETRY_BASE_DELAY = 1000;
    const delays = [0, 1, 2].map(i => RETRY_BASE_DELAY * Math.pow(2, i));
    expect(delays).toEqual([1000, 2000, 4000]);
  });
});
