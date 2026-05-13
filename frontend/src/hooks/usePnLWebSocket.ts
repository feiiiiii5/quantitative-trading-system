import { useEffect, useState, useRef, useCallback } from 'react';

interface PnLPosition {
  symbol: string;
  current_price: number;
  entry_price: number;
  shares: number;
  market_value: number;
  cost: number;
  pnl: number;
  pnl_pct: number;
  change_pct: number;
}

interface PnLSummary {
  total_pnl: number;
  total_cost: number;
  total_market_value: number;
  total_pnl_pct: number;
  position_count: number;
}

interface PnLData {
  positions: PnLPosition[];
  summary: PnLSummary;
}

export function usePnLWebSocket(positions: Array<{ symbol: string; entry_price: number; shares: number }>) {
  const [pnlData, setPnlData] = useState<PnLData | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelay = useRef(1000);
  const positionsRef = useRef(positions);
  positionsRef.current = positions;
  const mountedRef = useRef(true);

  const cleanup = useCallback(() => {
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
    if (wsRef.current) {
      wsRef.current.onopen = null;
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.onmessage = null;
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    cleanup();

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/ws/pnl`;
    const ws = new WebSocket(url);

    ws.onopen = () => {
      if (!mountedRef.current) { ws.close(); return; }
      setConnected(true);
      reconnectDelay.current = 1000;
      const pos = positionsRef.current;
      if (pos.length > 0) {
        ws.send(JSON.stringify({ type: 'get_pnl', positions: pos }));
      }
    };

    ws.onmessage = (event) => {
      if (!mountedRef.current) return;
      try {
        const msg = JSON.parse(event.data) as { type: string; data: PnLPosition[]; summary: PnLSummary };
        if (msg.type === 'pnl' && msg.data) {
          setPnlData({ positions: msg.data, summary: msg.summary });
        }
      } catch { /* ignore */ }
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setConnected(false);
      reconnectTimer.current = setTimeout(() => {
        reconnectDelay.current = Math.min(reconnectDelay.current * 2, 30000);
        connect();
      }, reconnectDelay.current);
    };

    ws.onerror = () => ws.close();
    wsRef.current = ws;
  }, [cleanup]);

  useEffect(() => {
    mountedRef.current = true;
    if (positions.length > 0) {
      connect();
    }
    return () => {
      mountedRef.current = false;
      cleanup();
    };
  }, [positions.length > 0, connect, cleanup]);

  const refresh = useCallback(() => {
    const pos = positionsRef.current;
    if (wsRef.current?.readyState === WebSocket.OPEN && pos.length > 0) {
      wsRef.current.send(JSON.stringify({ type: 'get_pnl', positions: pos }));
    }
  }, []);

  return { pnlData, connected, refresh };
}
