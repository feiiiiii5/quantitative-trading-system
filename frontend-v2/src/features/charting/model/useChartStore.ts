import { create } from 'zustand';
import type { KlineInterval } from '@/entities/tick';
import type { ChartState } from './types';

export const useChartStore = create<ChartState>((set) => ({
  symbol: '000001.SZ',
  interval: '1d' as KlineInterval,
  indicators: [],
  signals: [],

  setSymbol: (symbol) => set({ symbol }),
  setInterval: (interval) => set({ interval }),
  addIndicator: (indicator) =>
    set((state) => ({ indicators: [...state.indicators, indicator] })),
  removeIndicator: (type) =>
    set((state) => ({ indicators: state.indicators.filter((i) => i.type !== type) })),
  setSignals: (signals) => set({ signals }),
}));
