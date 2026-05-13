import { useState, useEffect, useRef, useCallback } from 'react';
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
  const prevSymbolsRef = useRef<string>('');

  useEffect(() => {
    const key = symbols.join(',');
    if (key === prevSymbolsRef.current) return;
    const prev = prevSymbolsRef.current;
    prevSymbolsRef.current = key;

    if (symbols.length > 0) {
      wsManager.subscribeSymbols(symbols);
    }
    return () => {
      const prevSymbols = prev ? prev.split(',') : [];
      if (prevSymbols.length > 0) {
        wsManager.unsubscribeSymbols(prevSymbols);
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
