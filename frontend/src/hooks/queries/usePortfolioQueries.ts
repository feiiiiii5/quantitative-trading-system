import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from '@/api/client';

export const portfolioKeys = {
  all: ['portfolio'] as const,
  risk: () => [...portfolioKeys.all, 'risk'] as const,
  riskDashboard: () => [...portfolioKeys.all, 'risk', 'dashboard'] as const,
  summary: () => [...portfolioKeys.all, 'summary'] as const,
  holdings: () => [...portfolioKeys.all, 'holdings'] as const,
  correlation: () => [...portfolioKeys.all, 'correlation'] as const,
  diversification: () => [...portfolioKeys.all, 'diversification'] as const,
  attribution: () => [...portfolioKeys.all, 'attribution'] as const,
  stressScenarios: () => [...portfolioKeys.all, 'stress', 'scenarios'] as const,
  equity: () => [...portfolioKeys.all, 'equity'] as const,
};

export function usePortfolioRiskDashboard() {
  return useQuery({
    queryKey: portfolioKeys.riskDashboard(),
    queryFn: () => apiGet<{
      positions: Array<{ symbol: string; name: string; shares: number; avg_cost: number; current_price: number; weight: number; pnl: number; pnl_pct: number }>;
      total_value: number;
      daily_pnl_pct: number;
      position_count: number;
      risk_metrics: {
        portfolio_volatility: number;
        portfolio_sharpe: number;
        portfolio_sortino: number;
        var_95: number;
        cvar_95: number;
        max_drawdown: number;
        annual_return: number;
      };
      concentration: Record<string, number>;
      drawdown: { current_drawdown: number; max_drawdown: number; drawdown_status: string };
      stress_summary: Array<{ scenario: string; impact: number }>;
      riskDecomposition?: Array<{ source: string; contribution: number }>;
      correlationMatrix?: { labels: string[]; values: number[][] };
      historicalVol?: number[];
      impliedVol?: number[];
      volDates?: string[];
    }>('/portfolio/risk/dashboard'),
    staleTime: 30_000,
  });
}

export function usePortfolioSummary() {
  return useQuery({
    queryKey: portfolioKeys.summary(),
    queryFn: () => apiGet<{
      total_value: number;
      daily_pnl: number;
      daily_pnl_pct: number;
      total_pnl: number;
      total_pnl_pct: number;
      cash: number;
      positions_count: number;
    }>('/portfolio/summary'),
    staleTime: 15_000,
  });
}

export function usePortfolioHoldings() {
  return useQuery({
    queryKey: portfolioKeys.holdings(),
    queryFn: () => apiGet<{
      cash: number;
      total_assets: number;
      current_positions: Record<string, { market_value: number }>;
    }>('/trading/account'),
    staleTime: 15_000,
  });
}

export function usePortfolioDiversification() {
  return useQuery({
    queryKey: portfolioKeys.diversification(),
    queryFn: () => apiGet<Record<string, unknown>>('/portfolio/diversification'),
    staleTime: 60_000,
  });
}

export function usePortfolioAttribution() {
  return useQuery({
    queryKey: portfolioKeys.attribution(),
    queryFn: () => apiGet<Record<string, unknown>>('/portfolio/attribution'),
    staleTime: 60_000,
  });
}

export function useStressScenarios() {
  return useQuery({
    queryKey: portfolioKeys.stressScenarios(),
    queryFn: () => apiGet<Array<{ name: string; description: string; impact: number }>>('/portfolio/stress/scenarios'),
    staleTime: 300_000,
  });
}

export function useBuyStock() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { symbol: string; shares: number; price?: number }) =>
      apiPost('/trading/buy', params),
    onMutate: async (_params) => {
      await qc.cancelQueries({ queryKey: portfolioKeys.holdings() });
      const prev = qc.getQueryData(portfolioKeys.holdings());
      return { prev };
    },
    onError: (_err, _params, context) => {
      if (context?.prev) qc.setQueryData(portfolioKeys.holdings(), context.prev);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: portfolioKeys.all });
      qc.invalidateQueries({ queryKey: ['trading'] });
    },
  });
}

export function useSellStock() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { symbol: string; shares: number; price?: number }) =>
      apiPost('/trading/sell', params),
    onMutate: async (_params) => {
      await qc.cancelQueries({ queryKey: portfolioKeys.holdings() });
      const prev = qc.getQueryData(portfolioKeys.holdings());
      return { prev };
    },
    onError: (_err, _params, context) => {
      if (context?.prev) qc.setQueryData(portfolioKeys.holdings(), context.prev);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: portfolioKeys.all });
      qc.invalidateQueries({ queryKey: ['trading'] });
    },
  });
}
