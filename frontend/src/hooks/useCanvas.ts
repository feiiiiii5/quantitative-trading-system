import { useRef, useEffect, useCallback } from 'react';

export function useCanvas(
  draw: (ctx: CanvasRenderingContext2D, w: number, h: number) => void,
  deps: React.DependencyList = [],
) {
  const ref = useRef<HTMLCanvasElement>(null);
  const drawRef = useRef(draw);
  drawRef.current = draw;

  const redraw = useCallback(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    drawRef.current(ctx, rect.width, rect.height);
  }, []);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    let rafId: number;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(redraw);
    });
    observer.observe(canvas);
    redraw();
    return () => {
      observer.disconnect();
      cancelAnimationFrame(rafId);
    };
  }, [redraw]);

  useEffect(() => {
    redraw();
  }, deps);

  return { ref, redraw };
}
