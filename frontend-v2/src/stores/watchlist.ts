import { create } from 'zustand';

interface WatchlistState {
  symbols: string[];
  add: (symbol: string) => void;
  remove: (symbol: string) => void;
  reorder: (symbols: string[]) => void;
  toggle: (symbol: string) => void;
}

function loadFromStorage(): string[] {
  try {
    const raw = localStorage.getItem('qc_watchlist');
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function saveToStorage(symbols: string[]): void {
  try { localStorage.setItem('qc_watchlist', JSON.stringify(symbols)); } catch { /* silent */ }
}

export const useWatchlistStore = create<WatchlistState>((set) => ({
  symbols: loadFromStorage(),

  add: (symbol) => set((s) => {
    if (s.symbols.includes(symbol)) return s;
    const next = [...s.symbols, symbol];
    saveToStorage(next);
    return { symbols: next };
  }),

  remove: (symbol) => set((s) => {
    const next = s.symbols.filter(x => x !== symbol);
    saveToStorage(next);
    return { symbols: next };
  }),

  reorder: (symbols) => set(() => {
    saveToStorage(symbols);
    return { symbols };
  }),

  toggle: (symbol) => set((s) => {
    const next = s.symbols.includes(symbol)
      ? s.symbols.filter(x => x !== symbol)
      : [...s.symbols, symbol];
    saveToStorage(next);
    return { symbols: next };
  }),
}));
