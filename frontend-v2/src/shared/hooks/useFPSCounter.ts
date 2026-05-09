import { useEffect, useRef, useState } from 'react';

export function useFPSCounter(): number {
  const [fps, setFps] = useState(60);
  const framesRef = useRef(0);
  const lastTimeRef = useRef(performance.now());
  const lowFpsStartRef = useRef<number | null>(null);

  useEffect(() => {
    let rafId: number;

    const tick = () => {
      framesRef.current++;
      const now = performance.now();
      const elapsed = now - lastTimeRef.current;

      if (elapsed >= 1000) {
        const currentFps = Math.round((framesRef.current * 1000) / elapsed);
        setFps(currentFps);
        framesRef.current = 0;
        lastTimeRef.current = now;

        if (currentFps < 30) {
          if (lowFpsStartRef.current === null) {
            lowFpsStartRef.current = now;
          } else if (now - lowFpsStartRef.current > 1000) {
            console.warn(`[FPS] Frame rate below 30 FPS for >1s: ${currentFps} FPS`);
          }
        } else {
          lowFpsStartRef.current = null;
        }
      }

      rafId = requestAnimationFrame(tick);
    };

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, []);

  return fps;
}
