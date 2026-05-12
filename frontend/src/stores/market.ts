import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { apiGet } from '@/api/client';
import { dedup } from '@/utils/dedup';
import type { StockQuote, IndexQuote, SectorData, BreadthData } from '@/types';

interface MarketState {
  indices: IndexQuote[];
  stocks: StockQuote[];
  sectors: SectorData[];
  breadth: BreadthData | null;
  northFlow: number | null;
  wsConnected: boolean;
  loading: boolean;
  error: string | null;
  fetchIndices: () => Promise<void>;
  fetchStocks: () => Promise<void>;
  fetchSectors: () => Promise<void>;
  fetchBreadth: () => Promise<void>;
  updateIndices: (data: IndexQuote[]) => void;
  updateStock: (symbol: string, patch: Partial<StockQuote>) => void;
  setWsConnected: (v: boolean) => void;
  searchStocks: (query: string) => Promise<Array<{ symbol: string; name: string; code: string; market: string }>>;
}

export const useMarketStore = create<MarketState>()(devtools((set, get) => ({
  indices: [],
  stocks: [],
  sectors: [],
  breadth: null,
  northFlow: null,
  wsConnected: false,
  loading: false,
  error: null,

  fetchIndices: async () => {
    const { wsConnected } = get();
    if (wsConnected) return;
    set({ loading: true, error: null });
    try {
      const data = await dedup('market:overview', () => apiGet<Record<string, unknown>>('/market/overview'));
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
      set({ indices: parsed, northFlow, loading: false, error: null });
    } catch (e) {
      set({ loading: false, error: (e as Error).message });
    }
  },

  fetchStocks: async () => {
    const { wsConnected } = get();
    if (wsConnected) {
      set({ loading: false });
      return;
    }
    set({ loading: true, error: null });
    try {
      const data = await dedup('market:stocks', () => apiGet<StockQuote[]>('/market/stocks'));
      set({ stocks: Array.isArray(data) ? data : [], loading: false, error: null });
    } catch (e) {
      set({ stocks: [], loading: false, error: (e as Error).message });
    }
  },

  fetchSectors: async () => {
    set({ loading: true, error: null });
    try {
      const data = await apiGet<Record<string, unknown>>('/market/heatmap');
      const items: SectorData[] = Object.entries(data ?? {}).map(([key, val]) => ({
        name: (val as Record<string, unknown>)?.name ?? key,
        change_pct: (val as Record<string, unknown>)?.change_pct ?? 0,
        amount: (val as Record<string, unknown>)?.amount ?? 0,
        volume: (val as Record<string, unknown>)?.volume ?? 0,
      }));
      set({ sectors: items, loading: false, error: null });
    } catch (e) {
      set({ loading: false, error: (e as Error).message });
    }
  },

  fetchBreadth: async () => {
    set({ loading: true, error: null });
    try {
      const symbols = 'sh000001,sz399001,sz399006,sh000300,sh000905,sh000688';
      const raw = await apiGet<{
        advance_decline: Record<string, unknown>;
        percent_above_ma: Record<string, unknown>;
      }>('/market/breadth', { symbols });
      const ad = raw?.advance_decline;
      const pma = raw?.percent_above_ma;
      if (!ad) { set({ breadth: null, loading: false, error: null }); return; }
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
        loading: false,
        error: null,
      });
    } catch (e) {
      set({ breadth: null, loading: false, error: (e as Error).message });
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
}), { name: 'MarketStore', enabled: import.meta.env.DEV }));
