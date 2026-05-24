import { useState, useEffect, useRef } from 'react';
import { wsManager } from '@/services/websocket';

export function useWebSocket(channel: string, handler: (data: unknown) => void) {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    const stableHandler = (data: unknown) => handlerRef.current(data);
    const unsub = wsManager.subscribe(channel, stableHandler);
    return unsub;
  }, [channel]);
}

export function useWebSocketSubscription(symbols: string[]) {
  const symbolsRef = useRef<string[]>(symbols);
  symbolsRef.current = symbols;

  useEffect(() => {
    if (symbols.length > 0) {
      wsManager.subscribeSymbols(symbols);
    }
    return () => {
      const prev = symbolsRef.current;
      if (prev.length > 0) {
        wsManager.unsubscribeSymbols(prev);
      }
    };
  }, [symbols.join(',')]);
}

export function useWsConnectionState(): boolean {
  const [connected, setConnected] = useState(wsManager.isConnected());

  useEffect(() => {
    const unsub = wsManager.onConnectionChange(setConnected);
    return unsub;
  }, []);

  return connected;
}
