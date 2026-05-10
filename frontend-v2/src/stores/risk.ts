import { create } from 'zustand';
import { apiGet } from '@/api/client';
import type { RiskLevel, RiskAlert, RiskMetrics } from '@/types';

interface RiskState {
  riskLevel: RiskLevel;
  var95: number;
  cvar: number;
  maxDrawdown: number;
  sharpe: number;
  beta: number;
  alerts: RiskAlert[];
  killSwitchActive: boolean;
  metrics: RiskMetrics | null;
  setRiskLevel: (level: RiskLevel) => void;
  setMetrics: (m: RiskMetrics) => void;
  addAlert: (alert: RiskAlert) => void;
  clearAlerts: () => void;
  triggerKillSwitch: () => void;
  resetKillSwitch: () => void;
  fetchMetrics: () => Promise<void>;
}

export const useRiskStore = create<RiskState>((set) => ({
  riskLevel: 'LOW',
  var95: 0,
  cvar: 0,
  maxDrawdown: 0,
  sharpe: 0,
  beta: 1,
  alerts: [],
  killSwitchActive: false,
  metrics: null,

  setRiskLevel: (level) => set({ riskLevel: level }),
  setMetrics: (m) => set({
    metrics: m,
    riskLevel: m.riskLevel,
    var95: m.var95,
    cvar: m.cvar,
    maxDrawdown: m.maxDrawdown,
    sharpe: m.sharpe,
    beta: m.beta,
  }),
  addAlert: (alert) => set((s) => ({ alerts: [alert, ...s.alerts].slice(0, 50) })),
  clearAlerts: () => set({ alerts: [] }),
  triggerKillSwitch: () => set({ killSwitchActive: true }),
  resetKillSwitch: () => set({ killSwitchActive: false }),
  fetchMetrics: async () => {
    try {
      const data = await apiGet<RiskMetrics>('/risk/metrics');
      if (data) set({
        metrics: data,
        riskLevel: data.riskLevel,
        var95: data.var95,
        cvar: data.cvar,
        maxDrawdown: data.maxDrawdown,
        sharpe: data.sharpe,
        beta: data.beta,
      });
    } catch { /* fallback handled by page */ }
  },
}));
