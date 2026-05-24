import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/api/client';

export const stockKeys = {
  all: ['stock'] as const,
  detail: (symbol: string) => [...stockKeys.all, 'detail', symbol] as const,
  history: (symbol: string, period?: string) => [...stockKeys.all, 'history', symbol, period] as const,
  indicators: (symbol: string) => [...stockKeys.all, 'indicators', symbol] as const,
  fundamentals: (symbol: string) => [...stockKeys.all, 'fundamentals', symbol] as const,
  analysis: (symbol: string) => [...stockKeys.all, 'analysis', symbol] as const,
};

export function useStockRealtime(symbol: string) {
  return useQuery({
    queryKey: stockKeys.detail(symbol),
    queryFn: () => apiGet<{
      symbol: string;
      name: string;
      price: number;
      change: number;
      change_pct: number;
      volume: number;
      turnover: number;
      open: number;
      high: number;
      low: number;
      prev_close: number;
      pe_ttm?: number;
      pb?: number;
      market_cap?: number;
    }>(`/stock/realtime/${symbol}`),
    enabled: symbol.length > 0,
    staleTime: 10_000,
  });
}

export function useStockHistory(symbol: string, period: string = '1y') {
  return useQuery({
    queryKey: stockKeys.history(symbol, period),
    queryFn: () => apiGet<Array<{ date: string; open: number; high: number; low: number; close: number; volume: number }>>(
      `/stock/history/${symbol}`,
      { period, kline_type: 'daily', adjust: 'qfq' },
    ),
    enabled: symbol.length > 0,
    staleTime: 120_000,
  });
}

export function useStockIndicators(symbol: string) {
  return useQuery({
    queryKey: stockKeys.indicators(symbol),
    queryFn: () => apiGet<Record<string, number[]>>(`/stock/indicators/${symbol}`, { indicators: 'all' }),
    enabled: symbol.length > 0,
    staleTime: 120_000,
  });
}

export function useStockFundamentals(symbol: string) {
  return useQuery({
    queryKey: stockKeys.fundamentals(symbol),
    queryFn: () => apiGet<{
      pe_ttm: number;
      pb: number;
      roe: number;
      revenue_growth: number;
      profit_growth: number;
      debt_ratio: number;
      gross_margin: number;
    }>(`/stock/fundamentals/${symbol}`),
    enabled: symbol.length > 0,
    staleTime: 600_000,
  });
}

export function useStockAnalysis(symbol: string) {
  return useQuery({
    queryKey: stockKeys.analysis(symbol),
    queryFn: () => apiGet<{
      trend: string;
      momentum: string;
      support: number[];
      resistance: number[];
      signals: string[];
    }>(`/stock/analysis/${symbol}`),
    enabled: symbol.length > 0,
    staleTime: 120_000,
  });
}
