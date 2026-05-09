import { create } from 'zustand';
import type { Strategy, StrategyStatus } from '@/entities/strategy';

interface StrategyState {
  strategies: Map<string, Strategy>;
  activeStrategyId: string | null;

  setStrategies: (strategies: Strategy[]) => void;
  updateStrategy: (id: string, partial: Partial<Strategy>) => void;
  setActiveStrategy: (id: string | null) => void;
  updateStatus: (id: string, status: StrategyStatus) => void;
  updatePnl: (id: string, unrealized: number, realized: number) => void;
}

export const useStrategyStore = create<StrategyState>((set) => ({
  strategies: new Map(),
  activeStrategyId: null,

  setStrategies: (strategies) =>
    set({
      strategies: new Map(strategies.map((s) => [s.id, s])),
    }),

  updateStrategy: (id, partial) =>
    set((state) => {
      const strategies = new Map(state.strategies);
      const existing = strategies.get(id);
      if (existing) {
        strategies.set(id, { ...existing, ...partial });
      }
      return { strategies };
    }),

  setActiveStrategy: (id) => set({ activeStrategyId: id }),

  updateStatus: (id, status) =>
    set((state) => {
      const strategies = new Map(state.strategies);
      const existing = strategies.get(id);
      if (existing) {
        strategies.set(id, { ...existing, status });
      }
      return { strategies };
    }),

  updatePnl: (id, unrealized, realized) =>
    set((state) => {
      const strategies = new Map(state.strategies);
      const existing = strategies.get(id);
      if (existing) {
        strategies.set(id, {
          ...existing,
          unrealizedPnl: unrealized,
          realizedPnl: realized,
          totalPnl: unrealized + realized,
        });
      }
      return { strategies };
    }),
}));
