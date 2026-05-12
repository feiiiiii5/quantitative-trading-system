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
  const symbolsRef = useRef(symbols);
  symbolsRef.current = symbols;

  useEffect(() => {
    if (symbols.length > 0) {
      wsManager.subscribeSymbols(symbols);
    }
    return () => {
      if (symbolsRef.current.length > 0) {
        wsManager.unsubscribeSymbols(symbolsRef.current);
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
