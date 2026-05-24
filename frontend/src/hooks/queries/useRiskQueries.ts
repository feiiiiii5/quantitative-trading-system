import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from '@/api/client';

export const riskKeys = {
  all: ['risk'] as const,
  portfolio: () => [...riskKeys.all, 'portfolio'] as const,
  exposure: () => [...riskKeys.all, 'exposure'] as const,
  drawdown: (symbol: string) => [...riskKeys.all, 'drawdown', symbol] as const,
  efficientFrontier: () => [...riskKeys.all, 'efficient-frontier'] as const,
  monteCarloVaR: () => [...riskKeys.all, 'monte-carlo-var'] as const,
  correlation: () => [...riskKeys.all, 'correlation'] as const,
  blackLitterman: () => [...riskKeys.all, 'black-litterman'] as const,
  kelly: (params: string) => [...riskKeys.all, 'kelly', params] as const,
};

export function useRiskPortfolio() {
  return useQuery({
    queryKey: riskKeys.portfolio(),
    queryFn: () => apiGet<{
      var_95: number;
      cvar_95: number;
      beta: number;
      symbols: string[];
      position_count: number;
      annualized_vol: number;
    }>('/risk/portfolio'),
    staleTime: 120_000,
  });
}

export function useRiskExposure() {
  return useQuery({
    queryKey: riskKeys.exposure(),
    queryFn: () => apiGet<{
      sectors: Record<string, number>;
      concentration: number;
      position_count: number;
      diversification_score: number;
    }>('/risk/exposure'),
    staleTime: 60_000,
  });
}

export function useDrawdownAnalysis(symbol: string) {
  return useQuery({
    queryKey: riskKeys.drawdown(symbol),
    queryFn: () => apiGet<{
      symbol: string;
      period: string;
      episodes: Array<{
        start_idx: number;
        trough_idx: number;
        end_idx: number;
        depth: number;
        duration_bars: number;
        recovery_bars: number;
        recovered: boolean;
      }>;
      avg_recovery_bars: number;
      recovery_rate: number;
      total_episodes: number;
    }>(`/drawdown/analysis/${symbol}`),
    staleTime: 120_000,
  });
}

export function useEfficientFrontier() {
  return useQuery({
    queryKey: riskKeys.efficientFrontier(),
    queryFn: () => apiPost<{
      symbols: string[];
      period: string;
      risk_free_rate: number;
      frontier: Array<{ return: number; volatility: number; sharpe_ratio: number; weights: Record<string, number> }>;
      optimal_portfolios: {
        min_variance: { return: number; volatility: number; sharpe_ratio: number; weights: Record<string, number> } | null;
        max_sharpe: { return: number; volatility: number; sharpe_ratio: number; weights: Record<string, number> } | null;
      };
    }>('/portfolio/efficient-frontier', { symbols: ['600519', '000001', '601318'], n_points: 15 }),
    staleTime: 600_000,
  });
}

export function useMonteCarloVaR() {
  return useQuery({
    queryKey: riskKeys.monteCarloVaR(),
    queryFn: () => apiPost<{
      var_95: number;
      var_99: number;
      cvar_95: number;
      cvar_99: number;
      mean_portfolio_return: number;
      std_portfolio_return: number;
      n_simulations: number;
      confidence_levels: Record<string, number>;
      method: string;
      message: string;
    }>('/portfolio/monte-carlo-var', { symbols: ['600519', '000001', '601318'], n_simulations: 1000, time_horizon: 22 }),
    staleTime: 600_000,
  });
}

export function useCorrelationMatrix() {
  return useQuery({
    queryKey: riskKeys.correlation(),
    queryFn: () => apiPost<{
      symbols: string[];
      period: string;
      full_correlation: Record<string, Record<string, number>>;
      rolling_correlation: Record<string, Record<string, number>>;
      rolling_window: number;
    }>('/correlation/matrix', { symbols: ['600519', '000001', '601318'], period: '3mo' }),
    staleTime: 600_000,
  });
}

export function useBlackLitterman() {
  return useQuery({
    queryKey: riskKeys.blackLitterman(),
    queryFn: () => apiPost<{
      posterior_returns: Record<string, number>;
      weights: Record<string, number>;
      expected_return: number;
      expected_volatility: number;
      sharpe_ratio: number;
      message: string;
    }>('/portfolio/black-litterman', { symbols: ['600519', '000001', '601318'], market_portfolio: '600519' }),
    staleTime: 600_000,
  });
}

export function useKellyCalculator(winRate: number, avgWin: number, avgLoss: number) {
  return useQuery({
    queryKey: riskKeys.kelly(`${winRate}-${avgWin}-${avgLoss}`),
    queryFn: () => apiGet<{
      kelly_full: number;
      suggested_fraction: number;
      fraction_type: string;
      win_rate: number;
      win_loss_ratio: number;
      expected_value: number;
      ruin_probability: number;
      max_position_pct: number;
    }>('/position/kelly', { win_rate: winRate, avg_win: avgWin, avg_loss: avgLoss }),
    enabled: winRate > 0 && avgWin > 0 && avgLoss > 0,
    staleTime: 60_000,
  });
}

export function useRunStressTest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (symbols: string[]) => apiPost<{
      scenarios: Array<{
        name: string;
        portfolio_impact: number;
        portfolio_volatility: number;
        max_drawdown: number;
        recovery_days: number;
      }>;
      summary: { worst_case: number; average_impact: number; stress_score: number };
    }>('/portfolio/stress/run', {
      positions: symbols.map(s => ({ symbol: s, value: 10000 })),
    }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: riskKeys.all });
    },
  });
}
