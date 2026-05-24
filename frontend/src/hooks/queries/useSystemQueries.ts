import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/api/client';

export const systemKeys = {
  all: ['system'] as const,
  health: () => [...systemKeys.all, 'health'] as const,
  status: () => [...systemKeys.all, 'status'] as const,
  metrics: () => [...systemKeys.all, 'metrics'] as const,
  readiness: () => [...systemKeys.all, 'readiness'] as const,
};

export function useSystemHealth() {
  return useQuery({
    queryKey: systemKeys.health(),
    queryFn: () => apiGet<{
      status: string;
      checks: Record<string, string>;
      timestamp: string;
    }>('/system/health'),
    staleTime: 60_000,
  });
}

export function useSystemStatus() {
  return useQuery({
    queryKey: systemKeys.status(),
    queryFn: () => apiGet<{
      uptime: number;
      cpu_usage: number;
      memory_usage: number;
      active_connections: number;
    }>('/system/status'),
    staleTime: 30_000,
  });
}

export function useReadiness() {
  return useQuery({
    queryKey: systemKeys.readiness(),
    queryFn: () => apiGet<{
      status: string;
      checks: Record<string, string>;
      timestamp: string;
    }>('/readiness'),
    staleTime: 60_000,
  });
}
