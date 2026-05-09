import { useEffect, useRef, useState } from 'react';
import { wsEngine } from '@/shared/ws';
import type { TickData } from '@/entities/tick';

const MAX_TICKS = 500;

export function useBufferedMarketData(symbol: string): TickData[] {
  const bufferRef = useRef<TickData[]>([]);
  const [ticks, setTicks] = useState<TickData[]>([]);

  useEffect(() => {
    bufferRef.current = [];

    const unsub = wsEngine.subscribe<TickData>(`tick.${symbol}`, (t) => {
      bufferRef.current.push(t);
    });

    let rafId: number;
    const flush = () => {
      if (bufferRef.current.length > 0) {
        const buffered = bufferRef.current.splice(0);
        setTicks((prev) => [...prev.slice(-(MAX_TICKS - buffered.length)), ...buffered]);
      }
      rafId = requestAnimationFrame(flush);
    };
    rafId = requestAnimationFrame(flush);

    return () => {
      unsub();
      cancelAnimationFrame(rafId);
    };
  }, [symbol]);

  return ticks;
}
