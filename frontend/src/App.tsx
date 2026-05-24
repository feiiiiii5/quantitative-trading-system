import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { AppLayout } from '@/components/layout/AppLayout';
import { installGlobalErrorHandler } from '@/utils/globalErrorHandler';

installGlobalErrorHandler();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      gcTime: 600_000,
      refetchOnWindowFocus: false,
      retry: 2,
    },
  },
});

const DashboardPage = lazy(() => import('@/pages/dashboard/DashboardPage').then(m => ({ default: m.DashboardPage })));
const MarketPage = lazy(() => import('@/pages/market/MarketPage').then(m => ({ default: m.MarketPage })));
const StrategyPage = lazy(() => import('@/pages/strategy/StrategyPage').then(m => ({ default: m.StrategyPage })));
const RiskPage = lazy(() => import('@/pages/risk/RiskPage').then(m => ({ default: m.RiskPage })));
const TerminalPage = lazy(() => import('@/pages/terminal/TerminalPage').then(m => ({ default: m.TerminalPage })));
const AboutPage = lazy(() => import('@/pages/about/AboutPage').then(m => ({ default: m.AboutPage })));
const StockDetailPage = lazy(() => import('@/pages/stock/StockDetailPage').then(m => ({ default: m.StockDetailPage })));

function PageSpinner() {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      height: '100vh', background: '#0a0a0f', color: 'rgba(255,255,255,0.5)',
      fontSize: '0.875rem',
    }}>
      Loading...
    </div>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary>
        <BrowserRouter>
          <Suspense fallback={<PageSpinner />}>
            <Routes>
              <Route element={<AppLayout />}>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/market" element={<MarketPage />} />
                <Route path="/strategy" element={<StrategyPage />} />
                <Route path="/risk" element={<RiskPage />} />
                <Route path="/terminal" element={<TerminalPage />} />
                <Route path="/about" element={<AboutPage />} />
                <Route path="/stock/:symbol" element={<StockDetailPage />} />
              </Route>
            </Routes>
          </Suspense>
        </BrowserRouter>
      </ErrorBoundary>
      {import.meta.env.DEV && <ReactQueryDevtools initialIsOpen={false} />}
    </QueryClientProvider>
  );
}
