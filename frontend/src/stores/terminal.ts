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
    try {
      const raw = await dedup(`terminal:orderbook:${symbol}`, () => apiGet<{ bids: Array<{ price: number; volume: number }>; asks: Array<{ price: number; volume: number }>; symbol: string; timestamp: number }>(`/stock/orderbook/${symbol}`));
      if (raw?.bids && raw?.asks && Array.isArray(raw.bids) && Array.isArray(raw.asks)) {
        const bids: OrderBookEntry[] = raw.bids.map((b) => ({
          price: Number(b.price ?? 0),
          quantity: Math.floor(Number(b.volume ?? 0)),
          orders: Math.max(1, Math.floor(Number(b.volume ?? 0) / 100)),
        }));
        const asks: OrderBookEntry[] = raw.asks.map((a) => ({
          price: Number(a.price ?? 0),
          quantity: Math.floor(Number(a.volume ?? 0)),
          orders: Math.max(1, Math.floor(Number(a.volume ?? 0) / 100)),
        }));
        set({ orderBook: { bids, asks } });
        return;
      }
    } catch (e) {
      // 静默降级：保持空委托簿
    }
    set({ orderBook: { bids: [], asks: [] } });
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
    } catch {
      set({ trades: [] });
    }
  },
}), { name: 'TerminalStore', enabled: import.meta.env.DEV }));
