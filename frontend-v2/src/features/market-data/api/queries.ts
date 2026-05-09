import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/shared/api';
import type { TickData } from '@/entities/tick';
import type { KlineBar, KlineInterval } from '@/entities/tick';

export function useStockQuote(symbol: string) {
  return useQuery({
    queryKey: ['quote', symbol],
    queryFn: async () => {
      const { data } = await apiClient.get<TickData>(`/stock/realtime/${symbol}`);
      return data;
    },
    staleTime: 5_000,
    enabled: !!symbol,
  });
}

export function useStockHistory(symbol: string, interval: KlineInterval = '1d') {
  return useQuery({
    queryKey: ['history', symbol, interval],
    queryFn: async () => {
      const { data } = await apiClient.get<KlineBar[]>(`/stock/history/${symbol}`, {
        params: { interval, limit: 2000 },
      });
      return data;
    },
    staleTime: 30_000,
    enabled: !!symbol,
  });
}
