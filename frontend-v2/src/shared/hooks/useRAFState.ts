import { useCallback, useRef, useState } from 'react';

export function useRAFState<T>(initial: T): [T, (value: T | ((prev: T) => T)) => void] {
  const [state, setState] = useState(initial);
  const rafId = useRef<number>(0);

  const setRAFState = useCallback((value: T | ((prev: T) => T)) => {
    cancelAnimationFrame(rafId.current);
    rafId.current = requestAnimationFrame(() => {
      setState(value);
    });
  }, []);

  return [state, setRAFState];
}
