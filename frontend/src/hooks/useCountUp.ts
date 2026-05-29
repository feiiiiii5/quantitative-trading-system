import { useState, useEffect, useRef } from 'react';

export function useCountUp(target: number, duration = 300): number {
  const [display, setDisplay] = useState(target);
  const prev = useRef(target);
  useEffect(() => {
    const start = prev.current;
    const diff = target - start;
    if (Math.abs(diff) < 0.001) return;
    let rafId: number;
    let cancelled = false;
    const startTime = performance.now();
    const animate = (now: number) => {
      if (cancelled) return;
      const progress = Math.min((now - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(start + diff * eased);
      if (progress < 1) {
        rafId = requestAnimationFrame(animate);
      } else {
        prev.current = target;
      }
    };
    rafId = requestAnimationFrame(animate);
    return () => {
      cancelled = true;
      cancelAnimationFrame(rafId);
    };
  }, [target, duration]);
  return display;
}
