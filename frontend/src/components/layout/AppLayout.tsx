import { useState, useCallback, useEffect, memo } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { Sidebar } from '@/components/layout/Sidebar';
import { Topbar } from '@/components/layout/Topbar';
import { SearchModal } from '@/components/ui/SearchModal';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { useHotkeys } from '@/hooks/useHotkeys';
import '@/styles/base.css';

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
  const [searchOpen, setSearchOpen] = useState(false);

  const onSearchOpen = useCallback(() => setSearchOpen(true), []);
  const onSearchClose = useCallback(() => setSearchOpen(false), []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSearchOpen(false);
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
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
        <Topbar onSearchOpen={onSearchOpen} />
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
        </main>
      </div>
      <SearchModal open={searchOpen} onClose={onSearchClose} />
      <LayoutHotkeys onSearchOpen={onSearchOpen} />
    </div>
  );
});
