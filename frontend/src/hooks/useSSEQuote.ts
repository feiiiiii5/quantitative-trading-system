import { useEffect, useState, useRef } from 'react';

interface SSEQuoteData {
  symbol: string;
  price: number;
  change: number;
  change_pct: number;
  volume: number;
  amount: number;
}

export function useSSEQuote(symbol: string) {
  const [quote, setQuote] = useState<SSEQuoteData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!symbol) return;

    const url = `/sse/realtime?symbols=${encodeURIComponent(symbol)}`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as SSEQuoteData;
        if (data.symbol === symbol) {
          setQuote(data);
          setError(null);
        }
      } catch {
        // ignore non-JSON messages (keepalive etc.)
      }
    };

    es.onerror = () => {
      setError('SSE connection lost');
      es.close();
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [symbol]);

  return { quote, error };
}
