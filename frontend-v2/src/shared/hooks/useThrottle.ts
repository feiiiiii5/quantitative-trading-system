import { useCallback, useRef } from 'react';

export function useThrottle<T extends (...args: unknown[]) => void>(fn: T, delay: number): T {
  const lastCall = useRef(0);
  return useCallback((...args: unknown[]) => {
    const now = Date.now();
    if (now - lastCall.current >= delay) {
      lastCall.current = now;
      fn(...args);
    }
  }, [fn, delay]) as T;
}
