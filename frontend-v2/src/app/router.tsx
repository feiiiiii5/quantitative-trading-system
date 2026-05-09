import { lazy, Suspense } from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';

const TerminalPage = lazy(() => import('@/pages/terminal'));
const BacktesterPage = lazy(() => import('@/pages/backtester'));
const StrategiesPage = lazy(() => import('@/pages/strategies'));
const RiskPage = lazy(() => import('@/pages/risk'));
const SettingsPage = lazy(() => import('@/pages/settings'));

function LoadingFallback() {
  return (
    <div className="flex items-center justify-center h-screen bg-[var(--bg-base)]">
      <div className="text-[var(--text-muted)] text-[var(--font-size-sm)]">Loading...</div>
    </div>
  );
}

function withSuspense(Component: React.LazyExoticComponent<React.ComponentType>) {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <Component />
    </Suspense>
  );
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Navigate to="/terminal" replace />,
  },
  {
    path: '/terminal',
    element: withSuspense(TerminalPage),
  },
  {
    path: '/backtester',
    element: withSuspense(BacktesterPage),
  },
  {
    path: '/strategies',
    element: withSuspense(StrategiesPage),
  },
  {
    path: '/risk',
    element: withSuspense(RiskPage),
  },
  {
    path: '/settings',
    element: withSuspense(SettingsPage),
  },
]);
