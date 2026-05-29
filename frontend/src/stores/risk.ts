import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { apiGet } from '@/api/client';
import { dedup } from '@/utils/dedup';
import type { RiskLevel, RiskAlert, RiskMetrics } from '@/types';

interface RawDecompItem {
  source?: unknown;
  symbol?: unknown;
  contribution?: unknown;
  weight?: unknown;
}

interface RawCorrelationMatrix {
  labels?: unknown[];
  values?: unknown[][];
}

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
  error: string | null;
  setRiskLevel: (level: RiskLevel) => void;
  setMetrics: (m: RiskMetrics) => void;
  addAlert: (alert: RiskAlert) => void;
  clearAlerts: () => void;
  triggerKillSwitch: () => void;
  resetKillSwitch: () => void;
  fetchMetrics: () => Promise<void>;
  clearError: () => void;
}

export const useRiskStore = create<RiskState>()(devtools((set) => ({
  riskLevel: 'LOW',
  var95: 0,
  cvar: 0,
  maxDrawdown: 0,
  sharpe: 0,
  beta: 1,
  alerts: [],
  killSwitchActive: false,
  metrics: null,
  error: null,

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
      set({ error: null });
      const raw = await dedup('risk:metrics', () => apiGet<Record<string, unknown>>('/portfolio/risk/dashboard'));
      if (raw) {
        const rm = (raw.risk_metrics ?? {}) as Record<string, number>;
        const var95 = rm.var_95 ?? 0;
        const maxDrawdown = rm.max_drawdown ?? 0;
        const riskLevel: RiskLevel = var95 > 0.05 || maxDrawdown > 0.15 ? 'HIGH' : var95 > 0.03 || maxDrawdown > 0.08 ? 'MEDIUM' : 'LOW';

        const rawDecomp = raw.riskDecomposition ?? raw.risk_decomposition ?? [];
        const riskDecomposition = Array.isArray(rawDecomp)
          ? (rawDecomp as RawDecompItem[]).map((d) => ({ source: String(d.source ?? d.symbol ?? 'Unknown'), contribution: Number(d.contribution ?? d.weight ?? 0) }))
          : [];

        const rawCorr = raw.correlationMatrix ?? raw.correlation_matrix ?? { labels: [], values: [[]] };
        const corrData = rawCorr as RawCorrelationMatrix;
        const correlationMatrix = {
          labels: Array.isArray(corrData.labels) ? corrData.labels.map(String) : [],
          values: Array.isArray(corrData.values) ? corrData.values as number[][] : [[]],
        };

        const rawHistVol = raw.historicalVol ?? raw.historical_vol ?? [];
        const historicalVol = Array.isArray(rawHistVol) ? rawHistVol.map(Number) : [];

        const rawImplVol = raw.impliedVol ?? raw.implied_vol ?? [];
        const impliedVol = Array.isArray(rawImplVol) ? rawImplVol.map(Number) : [];

        const rawVolDates = raw.volDates ?? raw.vol_dates ?? [];
        const volDates = Array.isArray(rawVolDates) ? rawVolDates.map(String) : [];

        const data: RiskMetrics = {
          riskLevel,
          var95,
          cvar: rm.cvar_95 ?? 0,
          maxDrawdown,
          sharpe: rm.portfolio_sharpe ?? 0,
          beta: 1,
          riskDecomposition,
          correlationMatrix,
          historicalVol,
          impliedVol,
          volDates,
        };
        set({
          metrics: data,
          riskLevel: data.riskLevel,
          var95: data.var95,
          cvar: data.cvar,
          maxDrawdown: data.maxDrawdown,
          sharpe: data.sharpe,
          beta: data.beta,
        });
      }
    } catch (e) { set({ error: (e as Error).message }); }
  },
  clearError: () => set({ error: null }),
}), { name: 'RiskStore', enabled: import.meta.env.DEV }));
