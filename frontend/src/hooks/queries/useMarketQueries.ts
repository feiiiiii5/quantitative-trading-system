import { useQuery, useQueries, queryOptions } from '@tanstack/react-query';
import { apiGet } from '@/api/client';
import type { StockQuote } from '@/types';

export const marketKeys = {
  all: ['market'] as const,
  overview: () => [...marketKeys.all, 'overview'] as const,
  stocks: (market?: string) => [...marketKeys.all, 'stocks', market] as const,
  indices: () => [...marketKeys.all, 'indices'] as const,
  sectors: () => [...marketKeys.all, 'sectors'] as const,
  breadth: (symbols: string) => [...marketKeys.all, 'breadth', symbols] as const,
};

export const marketOptions = {
  overview: () => queryOptions({
    queryKey: marketKeys.overview(),
    queryFn: () => apiGet<{
      cn_indices: Record<string, { name: string; price: number; change_pct: number; change: number }>;
      hk_indices: Record<string, { name: string; price: number; change_pct: number; change: number }>;
      us_indices: Record<string, { name: string; price: number; change_pct: number; change: number }>;
      northbound: { total_net: number; sh_buy: number; sh_sell: number; sz_buy: number; sz_sell: number; top_stocks: unknown[] } | null;
      temperature: number;
      timestamp: number;
      market_breadth: { up: number; down: number; flat: number; advance_count: number; decline_count: number; total_amount: number; timestamp: number } | null;
    }>('/market/overview'),
    staleTime: 30_000,
  }),
  stocks: (market: string = 'A') => queryOptions({
    queryKey: marketKeys.stocks(market),
    queryFn: () => apiGet<StockQuote[]>('/market/stocks', { market }),
    staleTime: 60_000,
  }),
  sectors: () => queryOptions({
    queryKey: marketKeys.sectors(),
    queryFn: () => apiGet<{ market: string; items: Array<{ name: string; change_pct: number; amount: number; volume: number; value: number; leading_stock: string }>; timestamp: number }>('/market/heatmap'),
    staleTime: 120_000,
  }),
};

export function useMarketOverview() {
  return useQuery(marketOptions.overview());
}

export function useMarketStocks(market: string = 'A') {
  return useQuery(marketOptions.stocks(market));
}

export function useMarketIndices() {
  return useQuery({
    queryKey: marketKeys.indices(),
    queryFn: () => apiGet<{
      cn_indices?: Record<string, { name: string; price: number; change_pct: number; change: number }>;
    }>('/market/overview'),
    select: (data) => {
      const cn = data?.cn_indices ?? {};
      return Object.entries(cn).map(([code, v]) => ({
        name: v.name ?? code,
        code,
        price: v.price ?? 0,
        change: v.change ?? 0,
        change_pct: v.change_pct ?? 0,
      }));
    },
    staleTime: 30_000,
  });
}

export function useMarketSectors() {
  return useQuery(marketOptions.sectors());
}

export function useMarketBreadth(symbols: string) {
  return useQuery({
    queryKey: marketKeys.breadth(symbols),
    queryFn: () => apiGet<Record<string, { trend: string; ma_alignment: string }>>('/market/breadth', { symbols }),
    enabled: symbols.length > 0,
    staleTime: 120_000,
  });
}

export function useBatchMarketData() {
  return useQueries({
    queries: [
      marketOptions.overview(),
      marketOptions.stocks('A'),
      marketOptions.sectors(),
    ],
  });
}
