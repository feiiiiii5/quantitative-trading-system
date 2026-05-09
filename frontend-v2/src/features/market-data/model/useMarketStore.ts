import { create } from 'zustand';
import type { TickData, KlineBar } from '@/entities/tick';
import type { DepthData, TradeRecord } from './types';

interface MarketState {
  quotes: Map<string, TickData>;
  klines: Map<string, KlineBar[]>;
  depths: Map<string, DepthData>;
  recentTrades: Map<string, TradeRecord[]>;

  updateQuote: (symbol: string, quote: TickData) => void;
  updateKlines: (symbol: string, bars: KlineBar[]) => void;
  appendKline: (symbol: string, bar: KlineBar) => void;
  updateDepth: (symbol: string, depth: DepthData) => void;
  appendTrade: (symbol: string, trade: TradeRecord) => void;
}

const MAX_TRADES = 100;
const MAX_KLINES = 2000;

export const useMarketStore = create<MarketState>((set) => ({
  quotes: new Map(),
  klines: new Map(),
  depths: new Map(),
  recentTrades: new Map(),

  updateQuote: (symbol, quote) =>
    set((state) => {
      const quotes = new Map(state.quotes);
      quotes.set(symbol, quote);
      return { quotes };
    }),

  updateKlines: (symbol, bars) =>
    set((state) => {
      const klines = new Map(state.klines);
      klines.set(symbol, bars.slice(-MAX_KLINES));
      return { klines };
    }),

  appendKline: (symbol, bar) =>
    set((state) => {
      const klines = new Map(state.klines);
      const existing = klines.get(symbol) ?? [];
      const last = existing[existing.length - 1];
      if (last && last.time === bar.time) {
        existing[existing.length - 1] = bar;
      } else {
        existing.push(bar);
      }
      klines.set(symbol, existing.slice(-MAX_KLINES));
      return { klines };
    }),

  updateDepth: (symbol, depth) =>
    set((state) => {
      const depths = new Map(state.depths);
      depths.set(symbol, depth);
      return { depths };
    }),

  appendTrade: (symbol, trade) =>
    set((state) => {
      const recentTrades = new Map(state.recentTrades);
      const trades = [...(recentTrades.get(symbol) ?? []), trade].slice(-MAX_TRADES);
      recentTrades.set(symbol, trades);
      return { recentTrades };
    }),
}));
