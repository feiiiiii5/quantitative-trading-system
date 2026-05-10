import { create } from 'zustand';
import { apiGet } from '@/api/client';
import type { StockQuote, IndexQuote, SectorData, BreadthData } from '@/types';

interface MarketState {
  indices: IndexQuote[];
  stocks: StockQuote[];
  sectors: SectorData[];
  breadth: BreadthData | null;
  northFlow: number | null;
  wsConnected: boolean;
  loading: boolean;
  fetchIndices: () => Promise<void>;
  fetchStocks: () => Promise<void>;
  fetchSectors: () => Promise<void>;
  fetchBreadth: () => Promise<void>;
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
  northFlow: null,
  wsConnected: false,
  loading: false,

  fetchIndices: async () => {
    try {
      const data = await apiGet<Record<string, unknown>>('/market/overview');
      const cnIndices = (data?.cn_indices ?? {}) as Record<string, IndexQuote>;
      const northbound = data?.northbound as Record<string, unknown> | undefined;
      const northFlow = northbound && typeof northbound === 'object' && 'net_inflow' in northbound
        ? (northbound.net_inflow as number) ?? null
        : (data?.north_flow as number) ?? null;
      const parsed = Object.entries(cnIndices).map(([code, val]) => ({
        name: val.name ?? code,
        code,
        price: val.price ?? 0,
        change: val.change ?? 0,
        change_pct: val.change_pct ?? 0,
      }));
      set({ indices: parsed, northFlow });
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

  fetchBreadth: async () => {
    try {
      const symbols = 'sh000001,sz399001,sz399006,sh000300,sh000905,sh000688';
      const raw = await apiGet<{
        advance_decline: Record<string, unknown>;
        percent_above_ma: Record<string, unknown>;
      }>('/market/breadth', { symbols });
      const ad = raw?.advance_decline;
      const pma = raw?.percent_above_ma;
      if (!ad) { set({ breadth: null }); return; }
      set({
        breadth: {
          advancing: (ad.advancing as number) ?? 0,
          declining: (ad.declining as number) ?? 0,
          unchanged: (ad.unchanged as number) ?? 0,
          total_stocks: (ad.total_stocks as number) ?? 0,
          breadth_score: (ad.breadth_score as number) ?? 0,
          limit_up: (ad.limit_up as number) ?? 0,
          limit_down: (ad.limit_down as number) ?? 0,
          advance_decline_ratio: (ad.advance_decline_ratio as number) ?? 0,
          advance_decline_spread: (ad.advance_decline_spread as number) ?? 0,
          regime: (ad.regime as string) ?? 'neutral',
          avg_advance_pct: (ad.avg_advance_pct as number) ?? 0,
          avg_decline_pct: (ad.avg_decline_pct as number) ?? 0,
          thrust_ratio: (ad.thrust_ratio as number) ?? 0,
          pct_above_ma: (pma?.pct_above_ma as number) ?? 0,
          ma_signal: (pma?.signal as string) ?? 'neutral',
        },
      });
    } catch {
      set({ breadth: null });
    }
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
