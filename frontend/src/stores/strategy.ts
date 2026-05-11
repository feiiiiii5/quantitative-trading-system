import { create } from 'zustand';
import { apiGet } from '@/api/client';
import type { StrategyInfo, BacktestResult } from '@/types';

export function isBacktestResult(x: unknown): x is BacktestResult {
  if (typeof x !== 'object' || x === null) return false;
  const obj = x as Record<string, unknown>;
  return (
    typeof obj.total_return === 'number' &&
    typeof obj.annual_return === 'number' &&
    typeof obj.sharpe_ratio === 'number' &&
    typeof obj.max_drawdown === 'number' &&
    Array.isArray(obj.equity_curve)
  );
}

type CategorizedStrategies = Record<string, StrategyInfo[]>;

interface StrategyState {
  strategies: StrategyInfo[];
  categorizedStrategies: CategorizedStrategies;
  selectedStrategy: string | null;
  backtestResult: BacktestResult | null;
  backtestHistory: BacktestResult[];
  backtestRunning: boolean;
  backtestLogs: string[];
  fetchStrategies: () => Promise<void>;
  fetchCategorizedStrategies: () => Promise<void>;
  selectStrategy: (name: string) => void;
  runBacktest: (params: { symbol: string; start_date: string; end_date: string; initial_capital: number }) => Promise<void>;
  fetchBacktestHistory: () => Promise<void>;
  clearResult: () => void;
}

let runBacktestAbortController: AbortController | null = null;

export const useStrategyStore = create<StrategyState>((set, get) => ({
  strategies: [],
  categorizedStrategies: {},
  selectedStrategy: null,
  backtestResult: null,
  backtestHistory: [],
  backtestRunning: false,
  backtestLogs: [],

  fetchStrategies: async () => {
    try {
      const data = await apiGet<Record<string, { name: string; type: string; version: string; param_space?: Record<string, unknown> }>>('/backtest/strategies');
      if (data && typeof data === 'object' && !Array.isArray(data)) {
        const list = Object.values(data).map(v => ({
          name: v.name,
          aliases: [] as string[],
          description: `${v.type} v${v.version}`,
        }));
        set({ strategies: list });
      } else if (Array.isArray(data)) {
        set({ strategies: data });
      }
    } catch { /* silent */ }
  },

  fetchCategorizedStrategies: async () => {
    try {
      const data = await apiGet<{ strategies: Array<{ name: string; key: string; category: string; has_param_space: boolean; has_vectorized: boolean }> }>('/backtest/strategies/categorized');
      if (data?.strategies && Array.isArray(data.strategies)) {
        const grouped: CategorizedStrategies = {};
        for (const s of data.strategies) {
          const cat = s.category ?? 'other';
          if (!grouped[cat]) grouped[cat] = [];
          grouped[cat].push({ name: s.name, aliases: [s.key], description: `${s.category} strategy` });
        }
        set({ categorizedStrategies: grouped });
      }
    } catch { /* silent */ }
  },

  selectStrategy: (name) => set({ selectedStrategy: name }),

  runBacktest: async (params) => {
    const strategyName = get().selectedStrategy;
    if (!strategyName) return;

    runBacktestAbortController?.abort();
    const ac = new AbortController();
    runBacktestAbortController = ac;

    set({ backtestRunning: true, backtestResult: null, backtestLogs: [] });
    const logs: string[] = [];
    const addLog = (msg: string) => {
      logs.push(msg);
      set({ backtestLogs: [...logs] });
    };

    try {
      const response = await fetch('/api/backtest/run/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          strategy: strategyName,
          symbol: params.symbol,
          start_date: params.start_date,
          end_date: params.end_date,
          initial_capital: params.initial_capital,
        }),
        signal: ac.signal,
      });

      if (!response.ok) {
        throw new Error(`Backtest request failed: ${response.status} ${response.statusText}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('Response body is not readable');
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (ac.signal.aborted) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;

          if (trimmed.startsWith('data:')) {
            const payload = trimmed.slice(5).trim();
            if (payload === '[DONE]') continue;

            try {
              const parsed = JSON.parse(payload);
              if (parsed.type === 'log' && typeof parsed.message === 'string') {
                addLog(parsed.message);
              } else if (parsed.type === 'result' && parsed.data) {
                if (isBacktestResult(parsed.data)) set({ backtestResult: parsed.data });
              } else if (parsed.total_trades !== undefined) {
                if (isBacktestResult(parsed)) set({ backtestResult: parsed });
              }
            } catch {
              addLog(payload);
            }
          } else {
            addLog(trimmed);
          }
        }
      }

      if (buffer.trim()) {
        const trimmed = buffer.trim();
        if (trimmed.startsWith('data:')) {
          const payload = trimmed.slice(5).trim();
          try {
            const parsed = JSON.parse(payload);
            if (parsed.type === 'result' && parsed.data) {
              if (isBacktestResult(parsed.data)) set({ backtestResult: parsed.data });
            } else if (parsed.total_trades !== undefined) {
              if (isBacktestResult(parsed)) set({ backtestResult: parsed });
            }
          } catch {
            addLog(payload);
          }
        } else {
          addLog(trimmed);
        }
      }

      if (!ac.signal.aborted) {
        addLog(`[${new Date().toLocaleTimeString()}] Done.`);
      }
    } catch (e) {
      if (ac.signal.aborted) return;
      addLog(`[ERROR] ${(e as Error).message}`);
    } finally {
      if (!ac.signal.aborted) {
        set({ backtestRunning: false });
      }
      if (runBacktestAbortController === ac) {
        runBacktestAbortController = null;
      }
    }
  },

  fetchBacktestHistory: async () => {
    try {
      const data = await apiGet<BacktestResult[]>('/backtest/result/history');
      set({ backtestHistory: Array.isArray(data) ? data : [] });
    } catch { /* silent */ }
  },

  clearResult: () => set({ backtestResult: null, backtestLogs: [] }),
}));
