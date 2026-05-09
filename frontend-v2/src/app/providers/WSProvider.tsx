import { useEffect, useState, createContext, useContext } from 'react';
import { wsEngine, type ChannelName } from '@/shared/ws';

interface WSContextValue {
  status: 'connecting' | 'connected' | 'disconnected' | 'error' | 'fatal';
}

const WSContext = createContext<WSContextValue>({ status: 'disconnected' });

export function useWSStatus() {
  return useContext(WSContext);
}

const WS_CHANNELS: Array<{ channel: ChannelName; path: string }> = [
  { channel: 'market', path: '/ws/realtime' },
  { channel: 'orders', path: '/ws/pnl' },
  { channel: 'system', path: '/ws/signals' },
  { channel: 'ai', path: '/ws/regime' },
];

export function WSProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<WSContextValue['status']>('disconnected');

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;

    for (const { channel, path } of WS_CHANNELS) {
      wsEngine.connect(channel, `${protocol}//${host}${path}`);
    }

    const unsub = wsEngine.onStatus(setStatus);
    return () => {
      unsub();
      wsEngine.disconnectAll();
    };
  }, []);

  return <WSContext.Provider value={{ status }}>{children}</WSContext.Provider>;
}
