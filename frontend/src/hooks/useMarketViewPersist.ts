import { useState, useCallback, useEffect } from 'react';

interface MarketViewState {
  sortKey: string;
  sortDir: string;
  activeTab: string;
  changeRangeIdx: number;
  sectorFilter: string;
  contentTab: string;
}

const STORAGE_KEY = 'quant-market-view';
const DEFAULT: MarketViewState = {
  sortKey: 'symbol',
  sortDir: 'asc',
  activeTab: 'all',
  changeRangeIdx: 0,
  sectorFilter: '',
  contentTab: 'market',
};

function load(): MarketViewState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT;
    const parsed = JSON.parse(raw) as Partial<MarketViewState>;
    return { ...DEFAULT, ...parsed };
  } catch {
    return DEFAULT;
  }
}

function save(state: MarketViewState): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {}
}

export function useMarketViewPersist() {
  const [state, setState] = useState<MarketViewState>(load);

  const update = useCallback(<K extends keyof MarketViewState>(key: K, value: MarketViewState[K]) => {
    setState(prev => {
      const next = { ...prev, [key]: value };
      save(next);
      return next;
    });
  }, []);

  useEffect(() => {
    save(state);
  }, []);

  return { view: state, update };
}
