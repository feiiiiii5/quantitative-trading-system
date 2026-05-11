import { useState, useEffect, useRef } from 'react';

export function useTickFlash(value: number): 'up' | 'down' | null {
  const [flash, setFlash] = useState<'up' | 'down' | null>(null);
  const prev = useRef(value);

  useEffect(() => {
    if (value === prev.current) return;
    setFlash(value > prev.current ? 'up' : 'down');
    prev.current = value;
    const id = setTimeout(() => setFlash(null), 500);
    return () => clearTimeout(id);
  }, [value]);

  return flash;
}
