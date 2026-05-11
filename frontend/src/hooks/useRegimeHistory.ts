import { useState, useEffect } from 'react';
import { apiGet } from '@/api/client';

export interface RegimePeriod {
  start: string;
  end: string;
  regime: 'BULL' | 'BEAR' | 'CHOP' | 'VOLATILE';
}

export function useRegimeHistory(symbol: string, start: string, end: string) {
  const [regimeHistory, setRegimeHistory] = useState<RegimePeriod[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    apiGet<RegimePeriod[]>(`/regime/history?symbol=${encodeURIComponent(symbol)}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`)
      .then(data => {
        if (!cancelled && Array.isArray(data)) {
          setRegimeHistory(data);
        }
      })
      .catch(() => { /* regime data optional */ })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [symbol, start, end]);

  return { regimeHistory, loading };
}
