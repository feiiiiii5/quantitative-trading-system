import { create } from 'zustand';
import type { Alert } from '@/entities/alert';

interface RiskExposure {
  totalExposure: number;
  maxExposure: number;
  exposureByAsset: Record<string, number>;
  var95: number;
  var99: number;
  currentDrawdown: number;
  maxDrawdown: number;
  circuitBreaker: 'active' | 'warning' | 'tripped';
}

interface RiskState {
  exposure: RiskExposure | null;
  alerts: Alert[];
  unreadAlertCount: number;

  setExposure: (exposure: RiskExposure) => void;
  addAlert: (alert: Alert) => void;
  markAlertRead: (id: string) => void;
  clearAlerts: () => void;
}

export const useRiskStore = create<RiskState>((set) => ({
  exposure: null,
  alerts: [],
  unreadAlertCount: 0,

  setExposure: (exposure) => set({ exposure }),

  addAlert: (alert) =>
    set((state) => ({
      alerts: [alert, ...state.alerts].slice(0, 200),
      unreadAlertCount: state.unreadAlertCount + (alert.read ? 0 : 1),
    })),

  markAlertRead: (id) =>
    set((state) => ({
      alerts: state.alerts.map((a) => (a.id === id ? { ...a, read: true } : a)),
      unreadAlertCount: Math.max(0, state.unreadAlertCount - 1),
    })),

  clearAlerts: () => set({ alerts: [], unreadAlertCount: 0 }),
}));
