import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/shared/api';
import type { BacktestConfig, BacktestResult } from '../model/types';

export function useBacktestStatus(jobId: string | null) {
  return useQuery({
    queryKey: ['backtest-status', jobId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/backtest/result/${jobId}`);
      return data;
    },
    enabled: !!jobId,
    refetchInterval: (query) => {
      if (query.state.data?.status === 'completed' || query.state.data?.status === 'failed') {
        return false;
      }
      return 2000;
    },
  });
}

export function useRunBacktest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (config: BacktestConfig) => {
      const { data } = await apiClient.post<{ task_id: string }>('/backtest/run', config);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['backtest-history'] });
    },
  });
}

export function useBacktestResult(jobId: string | null) {
  return useQuery({
    queryKey: ['backtest-result', jobId],
    queryFn: async () => {
      const { data } = await apiClient.get<BacktestResult>(`/backtest/result/${jobId}`);
      return data;
    },
    enabled: !!jobId,
  });
}

export function useBacktestStrategies() {
  return useQuery({
    queryKey: ['backtest-strategies'],
    queryFn: async () => {
      const { data } = await apiClient.get('/backtest/strategies');
      return data;
    },
    staleTime: 60_000,
  });
}
