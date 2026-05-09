import { create } from 'zustand';
import { apiGet, apiPost } from '@/api/client';
import type { StrategyInfo, BacktestResult } from '@/types';

interface StrategyState {
  strategies: StrategyInfo[];
  selectedStrategy: string | null;
  backtestResult: BacktestResult | null;
  backtestRunning: boolean;
  backtestLogs: string[];
  fetchStrategies: () => Promise<void>;
  selectStrategy: (name: string) => void;
  runBacktest: (params: { symbol: string; start_date: string; end_date: string; initial_capital: number }) => Promise<void>;
  clearResult: () => void;
}

export const useStrategyStore = create<StrategyState>((set, get) => ({
  strategies: [],
  selectedStrategy: null,
  backtestResult: null,
  backtestRunning: false,
  backtestLogs: [],

  fetchStrategies: async () => {
    try {
      const data = await apiGet<{ strategies: StrategyInfo[] }>('/strategies/list');
      set({ strategies: Array.isArray(data?.strategies) ? data.strategies : [] });
    } catch { /* silent */ }
  },

  selectStrategy: (name) => set({ selectedStrategy: name }),

  runBacktest: async (params) => {
    const strategyName = get().selectedStrategy;
    if (!strategyName) return;
    set({ backtestRunning: true, backtestResult: null, backtestLogs: [] });
    const logs: string[] = [];
    const addLog = (msg: string) => {
      logs.push(msg);
      set({ backtestLogs: [...logs] });
    };
    addLog(`[${new Date().toLocaleTimeString()}] Loading price data for ${params.symbol}...`);
    try {
      addLog(`[${new Date().toLocaleTimeString()}] Running strategy: ${strategyName}`);
      addLog(`[${new Date().toLocaleTimeString()}] Period: ${params.start_date} ~ ${params.end_date}`);
      const data = await apiPost<BacktestResult>('/backtest/run', {
        symbol: params.symbol,
        strategy_type: strategyName,
        start_date: params.start_date,
        end_date: params.end_date,
        initial_capital: params.initial_capital,
      });
      addLog(`[${new Date().toLocaleTimeString()}] Processing ${data.total_trades} trades...`);
      addLog(`[${new Date().toLocaleTimeString()}] Computing performance metrics...`);
      addLog(`[${new Date().toLocaleTimeString()}] Done.`);
      set({ backtestResult: data, backtestRunning: false });
    } catch (e) {
      addLog(`[ERROR] ${(e as Error).message}`);
      set({ backtestRunning: false });
    }
  },

  clearResult: () => set({ backtestResult: null, backtestLogs: [] }),
}));
