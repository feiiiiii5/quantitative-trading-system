import { useState, useEffect, useCallback } from 'react';
import { BrowserRouter, Routes, Route, Outlet, useNavigate } from 'react-router-dom';
import { Sidebar } from '@/components/layout/Sidebar';
import { Topbar } from '@/components/layout/Topbar';
import { SearchModal } from '@/components/ui/SearchModal';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { useHotkeys } from '@/hooks/useHotkeys';
import { DashboardPage } from '@/pages/dashboard/DashboardPage';
import { MarketPage } from '@/pages/market/MarketPage';
import { StrategyPage } from '@/pages/strategy/StrategyPage';
import { RiskPage } from '@/pages/risk/RiskPage';
import { TerminalPage } from '@/pages/terminal/TerminalPage';
import { AboutPage } from '@/pages/about/AboutPage';

function AppHotkeys({ onSearchOpen }: { onSearchOpen: () => void }) {
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

function AppLayout() {
  const [searchOpen, setSearchOpen] = useState(false);

  const onSearchOpen = useCallback(() => setSearchOpen(true), []);
  const onSearchClose = useCallback(() => setSearchOpen(false), []);
  const onEscape = useCallback(() => setSearchOpen(false), []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onEscape();
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onEscape]);

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100vw', overflow: 'hidden', background: 'var(--bg-void)' }}>
      <Sidebar />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative', zIndex: 1 }}>
        <Topbar onSearchOpen={onSearchOpen} />
        <main style={{ flex: 1, overflow: 'auto' }}>
          <ErrorBoundary>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
      <SearchModal open={searchOpen} onClose={onSearchClose} />
      <AppHotkeys onSearchOpen={onSearchOpen} />
    </div>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/market" element={<MarketPage />} />
          <Route path="/strategy" element={<StrategyPage />} />
          <Route path="/risk" element={<RiskPage />} />
          <Route path="/terminal" element={<TerminalPage />} />
          <Route path="/about" element={<AboutPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
