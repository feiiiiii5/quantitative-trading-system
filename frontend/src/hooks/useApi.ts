import { useState, useEffect, useRef, useCallback } from 'react';
import { apiGet, apiPost } from '@/api/client';

interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

interface UseApiOptions {
  immediate?: boolean;
  timeout?: number;
}

export function useApiGet<T>(
  url: string,
  params?: Record<string, unknown>,
  options: UseApiOptions = {},
) {
  const { immediate = true, timeout } = options;
  const [state, setState] = useState<ApiState<T>>({ data: null, loading: immediate, error: null });
  const acRef = useRef<AbortController | null>(null);

  const paramsKey = JSON.stringify(params);

  const execute = useCallback(async () => {
    acRef.current?.abort();
    const ac = new AbortController();
    acRef.current = ac;

    setState({ data: null, loading: true, error: null });

    try {
      const data = await apiGet<T>(url, params, timeout);
      if (!ac.signal.aborted) {
        setState({ data, loading: false, error: null });
      }
    } catch (e) {
      if (!ac.signal.aborted) {
        setState({ data: null, loading: false, error: (e as Error).message });
      }
    }
  }, [url, paramsKey, timeout]);

  useEffect(() => {
    if (immediate) {
      execute();
    }
    return () => {
      acRef.current?.abort();
    };
  }, [execute, immediate]);

  return { ...state, refetch: execute };
}

export function useApiPost<T>(
  url: string,
  body?: unknown,
  options: UseApiOptions = {},
) {
  const { immediate = false, timeout } = options;
  const [state, setState] = useState<ApiState<T>>({ data: null, loading: false, error: null });
  const acRef = useRef<AbortController | null>(null);

  const execute = useCallback(async (overrideBody?: unknown) => {
    acRef.current?.abort();
    const ac = new AbortController();
    acRef.current = ac;

    setState({ data: null, loading: true, error: null });

    try {
      const data = await apiPost<T>(url, overrideBody ?? body, timeout);
      if (!ac.signal.aborted) {
        setState({ data, loading: false, error: null });
      }
    } catch (e) {
      if (!ac.signal.aborted) {
        setState({ data: null, loading: false, error: (e as Error).message });
      }
    }
  }, [url, body, timeout]);

  useEffect(() => {
    if (immediate) {
      execute();
    }
    return () => {
      acRef.current?.abort();
    };
  }, [execute, immediate]);

  return { ...state, execute };
}
