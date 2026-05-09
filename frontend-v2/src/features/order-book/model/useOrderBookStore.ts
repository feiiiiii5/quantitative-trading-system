import { create } from 'zustand';
import type { OrderBookLevel, OrderBookUpdate, GroupSize } from './types';

interface OrderBookState {
  symbol: string;
  bids: OrderBookLevel[];
  asks: OrderBookLevel[];
  spread: number;
  midPrice: number;
  groupSize: GroupSize;

  setSymbol: (symbol: string) => void;
  applyUpdate: (update: OrderBookUpdate) => void;
  setGroupSize: (size: GroupSize) => void;
}

export const useOrderBookStore = create<OrderBookState>((set) => ({
  symbol: '',
  bids: [],
  asks: [],
  spread: 0,
  midPrice: 0,
  groupSize: 0.01,

  setSymbol: (symbol) => set({ symbol }),
  applyUpdate: (update) =>
    set({
      bids: update.bids,
      asks: update.asks,
      spread: update.spread,
      midPrice: update.midPrice,
    }),
  setGroupSize: (groupSize) => set({ groupSize }),
}));
