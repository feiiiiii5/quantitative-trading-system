import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
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

const DEFAULT_STRATEGIES: StrategyInfo[] = [
  { name: 'dual_ma', aliases: ['双均线'], description: 'Trend following strategy' },
  { name: 'rsi_reversal', aliases: ['RSI反转'], description: 'Mean reversion strategy' },
  { name: 'bollinger_breakout', aliases: ['布林突破'], description: 'Volatility breakout strategy' },
  { name: 'macd_divergence', aliases: ['MACD背离'], description: 'Momentum divergence strategy' },
  { name: 'turtle_trading', aliases: ['海龟交易'], description: 'Trend following with ATR' },
];

function inferCategory(name: string, description: string): string {
  const text = `${name} ${description}`.toLowerCase();
  if (text.includes('趋势') || text.includes('均线') || text.includes('ma') || text.includes('trend') || text.includes('adaptive') || text.includes('turtle')) return '趋势跟踪';
  if (text.includes('均值') || text.includes('回归') || text.includes('rsi') || text.includes('reversion') || text.includes('bollinger') || text.includes('mean')) return '均值回归';
  if (text.includes('动量') || text.includes('momentum') || text.includes('macd') || text.includes('kdj')) return '动量策略';
  if (text.includes('量') || text.includes('obv') || text.includes('volume') || text.includes('pricevolume')) return '量价策略';
  if (text.includes('形态') || text.includes('pattern')) return '形态策略';
  if (text.includes('波动') || text.includes('volatility') || text.includes('squeeze')) return '波动率策略';
  return '其他';
}

const DEFAULT_CATEGORIZED: CategorizedStrategies = DEFAULT_STRATEGIES.reduce<CategorizedStrategies>((acc, s) => {
  const cat = inferCategory(s.name, s.description);
  if (!acc[cat]) acc[cat] = [];
  acc[cat].push(s);
  return acc;
}, {});

function fetchWithTimeout(url: string, init: RequestInit, ms: number): Promise<Response> {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), ms);
  if (init.signal) {
    init.signal.addEventListener('abort', () => controller.abort());
  }
  return fetch(url, { ...init, signal: controller.signal }).finally(() => clearTimeout(id));
}

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

export const useStrategyStore = create<StrategyState>()(devtools((set, get) => ({
  strategies: [],
  categorizedStrategies: {},
  selectedStrategy: null,
  backtestResult: null,
  backtestHistory: [],
  backtestRunning: false,
  backtestLogs: [],

  fetchStrategies: async () => {
    try {
      const data = await apiGet<{ total: number; strategies: Array<{ name: string; aliases: string[]; description: string }> }>('/strategies/list');
      if (data?.strategies && Array.isArray(data.strategies)) {
        set({ strategies: data.strategies });
      } else {
        set({ strategies: DEFAULT_STRATEGIES });
      }
    } catch {
      set({ strategies: DEFAULT_STRATEGIES });
    }
  },

  fetchCategorizedStrategies: async () => {
    try {
      const data = await apiGet<{ total: number; strategies: Array<{ name: string; aliases: string[]; description: string }> }>('/strategies/list');
      if (data?.strategies && Array.isArray(data.strategies)) {
        const grouped: CategorizedStrategies = {};
        for (const s of data.strategies) {
          const cat = inferCategory(s.name, s.description);
          if (!grouped[cat]) grouped[cat] = [];
          grouped[cat].push({ name: s.name, aliases: s.aliases, description: s.description });
        }
        set({ categorizedStrategies: grouped });
      }
    } catch {
      set({ categorizedStrategies: DEFAULT_CATEGORIZED });
    }
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
      const jobResponse = await fetchWithTimeout('/api/backtest/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          strategy_name: strategyName,
          strategy_type: strategyName,
          symbol: params.symbol,
          start_date: params.start_date,
          end_date: params.end_date,
          initial_capital: params.initial_capital,
        }),
        signal: ac.signal,
      }, 30_000);

      if (!jobResponse.ok) {
        throw new Error(`Backtest request failed: ${jobResponse.status} ${jobResponse.statusText}`);
      }

      const jobData = await jobResponse.json();
      const jobId = jobData?.job_id;
      if (!jobId) {
        throw new Error(jobData?.error ?? 'No job_id returned from backtest stream endpoint');
      }

      addLog(`Job created: ${jobId}`);

      const sseResponse = await fetchWithTimeout(`/api/backtest/stream/${jobId}`, { signal: ac.signal }, 60_000);
      if (!sseResponse.ok) {
        throw new Error(`SSE connection failed: ${sseResponse.status}`);
      }

      const reader = sseResponse.body?.getReader();
      if (!reader) {
        throw new Error('Response body is not readable');
      }

      try {
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
                } else if (parsed.type === 'progress' && typeof parsed.message === 'string') {
                  addLog(parsed.message);
                } else if (parsed.type === 'result' && parsed.data) {
                  if (isBacktestResult(parsed.data)) set({ backtestResult: parsed.data });
                } else if (parsed.type === 'error') {
                  addLog(`[ERROR] ${parsed.message ?? 'Unknown error'}`);
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
      } finally {
        try { reader.cancel(); } catch {}
        try { reader.releaseLock(); } catch {}
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
      const data = await apiGet<BacktestResult[]>('/backtest/history');
      set({ backtestHistory: Array.isArray(data) ? data : [] });
    } catch {}
  },

  clearResult: () => set({ backtestResult: null, backtestLogs: [] }),
}), { name: 'StrategyStore', enabled: import.meta.env.DEV }));
