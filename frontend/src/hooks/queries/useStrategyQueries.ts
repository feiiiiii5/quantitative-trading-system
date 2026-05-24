import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/api/client';

export const strategyKeys = {
  all: ['strategy'] as const,
  list: () => [...strategyKeys.all, 'list'] as const,
  paramSpecs: (strategy: string) => [...strategyKeys.all, 'param-specs', strategy] as const,
  factorRegistry: () => [...strategyKeys.all, 'factor-registry'] as const,
  alphaList: () => [...strategyKeys.all, 'alpha-list'] as const,
  backtestHistory: () => [...strategyKeys.all, 'backtest-history'] as const,
};

export function useStrategyList() {
  return useQuery({
    queryKey: strategyKeys.list(),
    queryFn: () => apiGet<{
      total: number;
      strategies: Array<{ name: string; aliases: string[]; description: string }>;
    }>('/strategies/list'),
    staleTime: 120_000,
  });
}

export function useStrategyParamSpecs(strategy: string | null) {
  return useQuery({
    queryKey: strategyKeys.paramSpecs(strategy ?? ''),
    queryFn: () => apiGet<{
      strategies: Record<string, Record<string, { type: string; min: number; max: number; step: number; default: number }>>;
    }>('/strategy/param-specs'),
    enabled: strategy !== null,
    staleTime: 600_000,
  });
}

export function useFactorRegistry() {
  return useQuery({
    queryKey: strategyKeys.factorRegistry(),
    queryFn: async () => {
      const raw = await apiGet<{ factors: Array<{ name: string; category: string; description: string }>; categories: string[] }>('/factor/registry');
      return Array.isArray(raw) ? raw : raw.factors;
    },
    staleTime: 600_000,
  });
}

export function useAlphaList() {
  return useQuery({
    queryKey: strategyKeys.alphaList(),
    queryFn: () => apiGet<Array<{ name: string; expression: string; category: string; description: string }>>('/alpha/list'),
    staleTime: 600_000,
  });
}

export function useBacktestHistory() {
  return useQuery({
    queryKey: strategyKeys.backtestHistory(),
    queryFn: () => apiGet<Array<{
      id: string;
      strategy_name: string;
      symbol: string;
      start_date: string;
      end_date: string;
      created_at: string;
      sharpe_ratio: number;
      total_return: number;
      max_drawdown: number;
      result?: {
        total_return: number;
        annual_return: number;
        max_drawdown: number;
        sharpe_ratio: number;
        win_rate: number;
        profit_factor: number;
        total_trades: number;
      };
    }>>('/backtest/history'),
    staleTime: 60_000,
  });
}
