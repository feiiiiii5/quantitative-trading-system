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
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelay = useRef(1000);

  useEffect(() => {
    if (!symbol) return;

    const connect = () => {
      const url = `/api/sse/realtime?symbols=${encodeURIComponent(symbol)}`;
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
        es.close();
        setError('SSE connection lost');
        if (reconnectTimer.current) clearTimeout(reconnectTimer.current);  // 清除旧定时器，防止并发重连
        reconnectTimer.current = setTimeout(() => {
          reconnectDelay.current = Math.min(reconnectDelay.current * 2, 30000);
          connect();
        }, reconnectDelay.current);
      };

      es.addEventListener('open', () => {
        reconnectDelay.current = 1000;
      });
    };

    connect();

    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
    };
  }, [symbol]);

  return { quote, error };
}
