import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
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

function generateSimulatedOrderBook(
  _symbol: string,
  basePrice?: number,
  rng: () => number = Math.random,
): { bids: OrderBookEntry[]; asks: OrderBookEntry[] } {
  const price = basePrice ?? 10 + rng() * 90;
  const bids: OrderBookEntry[] = [];
  const asks: OrderBookEntry[] = [];
  for (let i = 0; i < 10; i++) {
    bids.push({
      price: price - (i + 1) * 0.01,
      quantity: Math.floor(rng() * 500 + 100),
      orders: Math.floor(rng() * 10 + 1),
    });
    asks.push({
      price: price + (i + 1) * 0.01,
      quantity: Math.floor(rng() * 500 + 100),
      orders: Math.floor(rng() * 10 + 1),
    });
  }
  return { bids, asks };
}

export const useTerminalStore = create<TerminalState>()(devtools((set) => ({
  orderBook: { bids: [], asks: [] },
  trades: [],
  executionStats: null,
  selectedSymbol: '',

  setOrderBook: (data) => set({ orderBook: data }),
  addTrade: (trade) => set((s) => ({ trades: [trade, ...s.trades].slice(0, 50) })),
  setExecutionStats: (stats) => set({ executionStats: stats }),
  setSelectedSymbol: (symbol) => set({ selectedSymbol: symbol }),
  fetchOrderBook: async (symbol) => {
    set({ orderBook: generateSimulatedOrderBook(symbol) });
  },
  fetchTrades: async (symbol) => {
    try {
      const raw = await dedup(`terminal:trades:${symbol}`, () => apiGet<{ trades: Array<Record<string, unknown>>; total: number }>('/trading/history'));
      if (raw?.trades && Array.isArray(raw.trades)) {
        const trades: TradeRecord[] = raw.trades.map((t) => ({
          id: String(t.id ?? ''),
          price: Number(t.price ?? 0),
          quantity: Number(t.shares ?? 0),
          amount: Number(t.amount ?? 0),
          direction: String(t.action ?? 'buy').toUpperCase() === 'SELL' ? 'SELL' : 'BUY',
          time: String(t.time ?? ''),
        }));
        set({ trades: trades.slice(0, 50) });
      }
    } catch { /* fallback handled by page */ }
  },
}), { name: 'TerminalStore', enabled: import.meta.env.DEV }));
