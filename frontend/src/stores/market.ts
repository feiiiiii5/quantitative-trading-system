import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { apiGet } from '@/api/client';
import { dedup } from '@/utils/dedup';
import type { StockQuote, IndexQuote, SectorData, BreadthData } from '@/types';

interface OverviewResponse {
  cn_indices?: Record<string, { name: string; price: number; change: number; change_pct: number }>;
  northbound?: { net_inflow: number; sh_inflow: number; sz_inflow: number };
  north_flow?: number;
  market_breadth?: { advancing: number; declining: number; flat: number };
  sentiment?: number;
}

interface SectorItem {
  name: string;
  change_pct: number;
  amount: number;
  volume: number;
}

const BREADTH_SYMBOLS = 'sh000001,sz399001,sz399006,sh000300,sh000905,sh000688';

const stockMap = new Map<string, StockQuote>();

function syncStocksFromMap(): StockQuote[] {
  return Array.from(stockMap.values());
}

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
  batchUpdateStocks: (updates: Array<{ symbol: string; patch: Partial<StockQuote> }>) => void;
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
      const data = await dedup('market:overview', () => apiGet<OverviewResponse>('/market/overview'));
      const cnIndices = data?.cn_indices ?? {};
      const northbound = data?.northbound;
      const northFlow = northbound
        ? northbound.net_inflow ?? null
        : data?.north_flow ?? null;
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
    set({ loading: true, error: null });
    try {
      const data = await dedup('market:stocks', () => apiGet<StockQuote[]>('/market/stocks'));
      const list = Array.isArray(data) ? data : [];
      stockMap.clear();
      for (const s of list) stockMap.set(s.symbol, s);
      set({ stocks: syncStocksFromMap(), loading: false, error: null });
    } catch (e) {
      set({ loading: false, error: (e as Error).message });
    }
  },

  fetchSectors: async () => {
    set({ loading: true, error: null });
    try {
      const data = await apiGet<Record<string, SectorItem>>('/market/heatmap');
      const items: SectorData[] = Object.entries(data ?? {}).map(([key, val]) => ({
        name: val.name ?? key,
        change_pct: val.change_pct ?? 0,
        amount: val.amount ?? 0,
        volume: val.volume ?? 0,
      }));
      set({ sectors: items, loading: false, error: null });
    } catch (e) {
      set({ loading: false, error: (e as Error).message });
    }
  },

  fetchBreadth: async () => {
    set({ loading: true, error: null });
    try {
      const raw = await apiGet<{
        advance_decline?: Record<string, unknown>;
        percent_above_ma?: Record<string, unknown>;
      }>('/market/breadth', { symbols: BREADTH_SYMBOLS });
      const ad = raw?.advance_decline;
      const pma = raw?.percent_above_ma;
      if (!ad || 'error' in ad) { set({ breadth: null, loading: false, error: null }); return; }
      const num = (v: unknown, fallback = 0): number => typeof v === 'number' && isFinite(v) ? v : fallback;
      const str = (v: unknown, fallback = 'neutral'): string => typeof v === 'string' ? v : fallback;
      set({
        breadth: {
          advancing: num(ad.advancing),
          declining: num(ad.declining),
          unchanged: num(ad.unchanged),
          total_stocks: num(ad.total_stocks),
          breadth_score: num(ad.breadth_score),
          limit_up: num(ad.limit_up),
          limit_down: num(ad.limit_down),
          advance_decline_ratio: num(ad.advance_decline_ratio),
          advance_decline_spread: num(ad.advance_decline_spread),
          regime: str(ad.regime),
          avg_advance_pct: num(ad.avg_advance_pct),
          avg_decline_pct: num(ad.avg_decline_pct),
          thrust_ratio: num(ad.thrust_ratio),
          pct_above_ma: num(pma?.pct_above_ma),
          ma_signal: str(pma?.signal),
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
    const existing = stockMap.get(symbol);
    if (existing) {
      stockMap.set(symbol, { ...existing, ...patch } as StockQuote);
      set({ stocks: syncStocksFromMap() });
    }
  },

  batchUpdateStocks: (updates) => {
    let changed = false;
    for (const { symbol, patch } of updates) {
      const existing = stockMap.get(symbol);
      if (existing) {
        stockMap.set(symbol, { ...existing, ...patch } as StockQuote);
        changed = true;
      }
    }
    if (changed) set({ stocks: syncStocksFromMap() });
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
