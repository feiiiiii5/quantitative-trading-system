import { create } from 'zustand';
import { apiGet } from '@/api/client';
import type { StockQuote, IndexQuote, SectorData } from '@/types';

interface MarketState {
  indices: IndexQuote[];
  stocks: StockQuote[];
  sectors: SectorData[];
  loading: boolean;
  fetchIndices: () => Promise<void>;
  fetchStocks: () => Promise<void>;
  fetchSectors: () => Promise<void>;
  searchStocks: (query: string) => Promise<Array<{ symbol: string; name: string; code: string; market: string }>>;
}

export const useMarketStore = create<MarketState>((set) => ({
  indices: [],
  stocks: [],
  sectors: [],
  loading: false,

  fetchIndices: async () => {
    try {
      const data = await apiGet<Record<string, Record<string, IndexQuote>>>('/market/overview');
      const cnIndices = data?.cn_indices ?? {};
      const parsed = Object.entries(cnIndices).map(([code, val]) => ({
        name: val.name ?? code,
        code,
        price: val.price ?? 0,
        change: val.change ?? 0,
        change_pct: val.change_pct ?? 0,
      }));
      set({ indices: parsed });
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

  searchStocks: async (query: string) => {
    if (!query || query.length < 1) return [];
    try {
      const data = await apiGet<Array<{ symbol: string; name: string; code: string; market: string }>>('/search', { q: query });
      return Array.isArray(data) ? data : [];
    } catch {
      return [];
    }
  },
}));
