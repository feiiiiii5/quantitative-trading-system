import { create } from 'zustand';
import { apiGet } from '@/api/client';
import { dedup } from '@/utils/dedup';
import type { OrderBookEntry, TradeRecord, ExecutionStats } from '@/types';

interface TerminalState {
  orderBook: { bids: OrderBookEntry[]; asks: OrderBookEntry[] };
  trades: TradeRecord[];
  executionStats: ExecutionStats | null;
  selectedSymbol: string;
  setOrderBook: (data: { bids: OrderBookEntry[]; asks: OrderBookEntry[] }) => void;
  addTrade: (trade: TradeRecord) => void;
  setExecutionStats: (stats: ExecutionStats) => void;
  setSelectedSymbol: (symbol: string) => void;
  fetchOrderBook: (symbol: string) => Promise<void>;
  fetchTrades: (symbol: string) => Promise<void>;
}

export const useTerminalStore = create<TerminalState>((set) => ({
  orderBook: { bids: [], asks: [] },
  trades: [],
  executionStats: null,
  selectedSymbol: '',

  setOrderBook: (data) => set({ orderBook: data }),
  addTrade: (trade) => set((s) => ({ trades: [trade, ...s.trades].slice(0, 50) })),
  setExecutionStats: (stats) => set({ executionStats: stats }),
  setSelectedSymbol: (symbol) => set({ selectedSymbol: symbol }),
  fetchOrderBook: async (symbol) => {
    try {
      const data = await dedup(`terminal:orderbook:${symbol}`, () => apiGet<{ bids: OrderBookEntry[]; asks: OrderBookEntry[] }>('/terminal/orderbook', { symbol }));
      if (data) set({ orderBook: data });
    } catch { /* fallback handled by page */ }
  },
  fetchTrades: async (symbol) => {
    try {
      const data = await dedup(`terminal:trades:${symbol}`, () => apiGet<TradeRecord[]>('/terminal/trades', { symbol }));
      if (Array.isArray(data)) set({ trades: data.slice(0, 50) });
    } catch { /* fallback handled by page */ }
  },
}));
