import { create } from 'zustand';
import { apiGet } from '@/api/client';
import type { StockQuote, IndexQuote, SectorData } from '@/types';

interface MarketState {
  indices: IndexQuote[];
  stocks: StockQuote[];
  sectors: SectorData[];
  breadth: { advance_count: number; decline_count: number; flat_count: number; total_amount: number } | null;
  wsConnected: boolean;
  loading: boolean;
  fetchIndices: () => Promise<void>;
  fetchStocks: () => Promise<void>;
  fetchSectors: () => Promise<void>;
  updateIndices: (data: IndexQuote[]) => void;
  updateStock: (symbol: string, patch: Partial<StockQuote>) => void;
  setWsConnected: (v: boolean) => void;
  searchStocks: (query: string) => Promise<Array<{ symbol: string; name: string; code: string; market: string }>>;
}

export const useMarketStore = create<MarketState>((set, get) => ({
  indices: [],
  stocks: [],
  sectors: [],
  breadth: null,
  wsConnected: false,
  loading: false,

  fetchIndices: async () => {
    try {
      const data = await apiGet<Record<string, Record<string, IndexQuote>>>('/market/overview');
      const cnIndices = data?.cn_indices ?? {};
      const breadth = (data as Record<string, unknown>)?.market_breadth as MarketState['breadth'];
      const parsed = Object.entries(cnIndices).map(([code, val]) => ({
        name: val.name ?? code,
        code,
        price: val.price ?? 0,
        change: val.change ?? 0,
        change_pct: val.change_pct ?? 0,
      }));
      set({ indices: parsed, breadth: breadth ?? null });
    } catch { /* silent */ }
  },

  fetchStocks: async () => {
    set({ loading: true });
    try {
      const data = await apiGet<StockQuote[]>('/market/stocks');
      set({ stocks: Array.isArray(data) ? data : [], loading: false });
    } catch {
      set({ stocks: [], loading: false });
    }
  },

  fetchSectors: async () => {
    try {
      const data = await apiGet<{ items: SectorData[] }>('/market/heatmap');
      set({ sectors: data?.items ?? [] });
    } catch { /* silent */ }
  },

  updateIndices: (data) => set({ indices: data }),

  updateStock: (symbol, patch) => {
    const stocks = get().stocks;
    const idx = stocks.findIndex(s => s.symbol === symbol);
    if (idx >= 0) {
      const next = [...stocks];
      const existing = next[idx];
      if (existing) {
        next[idx] = { ...existing, ...patch } as typeof existing;
        set({ stocks: next });
      }
    }
  },

  setWsConnected: (v) => set({ wsConnected: v }),

  searchStocks: async (query: string) => {
    if (!query) return [];
    try {
      const data = await apiGet<Array<{ symbol: string; name: string; code: string; market: string }>>('/search', { q: query });
      return Array.isArray(data) ? data : [];
    } catch {
      return [];
    }
  },
}));
