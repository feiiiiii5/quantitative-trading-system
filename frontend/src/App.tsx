import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AppLayout } from '@/components/layout/AppLayout';
import { DashboardPage } from '@/pages/dashboard/DashboardPage';
import { MarketPage } from '@/pages/market/MarketPage';
import { StrategyPage } from '@/pages/strategy/StrategyPage';
import { RiskPage } from '@/pages/risk/RiskPage';
import { TerminalPage } from '@/pages/terminal/TerminalPage';
import { AboutPage } from '@/pages/about/AboutPage';
import { StockDetailPage } from '@/pages/stock/StockDetailPage';

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
          <Route path="/stock/:symbol" element={<StockDetailPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
