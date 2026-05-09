import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/shared/api';
import type { Strategy } from '@/entities/strategy';

export function useStrategies() {
  return useQuery({
    queryKey: ['strategies'],
    queryFn: async () => {
      const { data } = await apiClient.get<Strategy[]>('/performance');
      return data;
    },
    staleTime: 10_000,
  });
}

export function useBacktestStrategyList() {
  return useQuery({
    queryKey: ['backtest-strategies'],
    queryFn: async () => {
      const { data } = await apiClient.get('/backtest/strategies');
      return data;
    },
    staleTime: 60_000,
  });
}

export function useUpdateStrategyParams() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, params }: { id: string; params: Record<string, unknown> }) => {
      const { data } = await apiClient.put(`/backtest/param_grid`, {
        strategy_id: id,
        parameters: params,
      });
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['strategies'] });
    },
  });
}
