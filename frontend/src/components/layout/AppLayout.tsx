import { useState, useCallback, useEffect, memo } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { Sidebar } from '@/components/layout/Sidebar';
import { Topbar } from '@/components/layout/Topbar';
import { CommandPalette } from '@/components/CommandPalette';
import { KeyboardShortcuts } from '@/components/KeyboardShortcuts';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { ToastContainer } from '@/components/ui/ToastContainer';
import { useHotkeys } from '@/hooks/useHotkeys';
import { wsManager } from '@/services/websocket';
import { useMarketStore } from '@/stores/market';
import { useToastStore } from '@/stores/toast';
import type { QuoteMessage, IndexMessage } from '@/types/websocket';
import type { StockQuote } from '@/types';
import '@/styles/base.css';

type StockPatch = Partial<StockQuote>;

function LayoutHotkeys({ onSearchOpen }: { onSearchOpen: () => void }) {
  const navigate = useNavigate();
  useHotkeys({
    'cmd+k': onSearchOpen,
    'cmd+1': () => navigate('/'),
    'cmd+2': () => navigate('/market'),
    'cmd+3': () => navigate('/strategy'),
    'cmd+4': () => navigate('/risk'),
    'cmd+5': () => navigate('/terminal'),
  });
  return null;
}

export const AppLayout = memo(function AppLayout() {
  const [cmdOpen, setCmdOpen] = useState(false);

  const onCmdOpen = useCallback(() => setCmdOpen(true), []);
  const onCmdClose = useCallback(() => setCmdOpen(false), []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setCmdOpen(false);
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setCmdOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/ws/realtime`;
    wsManager.connect(wsUrl);

    const unsubQuote = wsManager.subscribe('quote', (msg) => {
      const m = msg as QuoteMessage;
      if (m.symbol) {
        useMarketStore.getState().updateStock(m.symbol, m as StockPatch);
      }
    });

    const unsubIndex = wsManager.subscribe('index', (msg) => {
      const m = msg as IndexMessage;
      if (m.data) {
        useMarketStore.getState().updateIndices(m.data);
      }
    });

    const unsubConn = wsManager.onConnectionChange((connected) => {
      useMarketStore.getState().setWsConnected(connected);
      if (connected) {
        const symbols = wsManager.getSubscribedSymbols();
        if (symbols.length > 0) {
          wsManager.subscribeSymbols(symbols);
        }
      } else {
        useToastStore.getState().addToast({
          type: 'warn',
          title: 'WebSocket Disconnected',
          body: 'Real-time data feed interrupted. Falling back to REST polling.',
          duration: 5000,
        });
      }
    });

    return () => {
      unsubQuote();
      unsubIndex();
      unsubConn();
      wsManager.disconnect();
    };
  }, []);

  return (
    <div
      style={{
        display: 'flex',
        height: '100vh',
        width: '100vw',
        overflow: 'hidden',
        background: 'var(--bg-base)',
      }}
    >
      <Sidebar />
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          position: 'relative',
          zIndex: 1,
        }}
      >
        <Topbar onSearchOpen={onCmdOpen} />
        <main
          style={{
            flex: 1,
            overflow: 'auto',
            minHeight: 0,
          }}
        >
          <ErrorBoundary>
        <Outlet />
      </ErrorBoundary>
      <ToastContainer />
        </main>
      </div>
      <CommandPalette open={cmdOpen} onClose={onCmdClose} />
      <KeyboardShortcuts />
      <LayoutHotkeys onSearchOpen={onCmdOpen} />
    </div>
  );
});
