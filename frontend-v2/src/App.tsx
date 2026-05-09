import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Outlet } from 'react-router-dom';
import { Sidebar } from '@/components/layout/Sidebar';
import { Topbar } from '@/components/layout/Topbar';
import { SearchModal } from '@/components/ui/SearchModal';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { DashboardPage } from '@/pages/dashboard/DashboardPage';
import { MarketPage } from '@/pages/market/MarketPage';
import { StrategyPage } from '@/pages/strategy/StrategyPage';
import { AboutPage } from '@/pages/about/AboutPage';

function AppLayout() {
  const [searchOpen, setSearchOpen] = useState(false);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, []);

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100vw', overflow: 'hidden', background: 'var(--bg-void)' }}>
      <Sidebar />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative', zIndex: 1 }}>
        <Topbar onSearchOpen={() => setSearchOpen(true)} />
        <main style={{ flex: 1, overflow: 'auto' }}>
          <ErrorBoundary>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
      <SearchModal open={searchOpen} onClose={() => setSearchOpen(false)} />
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
          <Route path="/about" element={<AboutPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
