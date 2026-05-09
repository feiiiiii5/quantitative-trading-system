import { create } from 'zustand';
import type { OrderSide, OrderType } from '@/entities/order';

interface OrderFormState {
  symbol: string;
  side: OrderSide;
  type: OrderType;
  qty: number;
  price: number;
  stopPrice: number;

  setSymbol: (symbol: string) => void;
  setSide: (side: OrderSide) => void;
  setType: (type: OrderType) => void;
  setQty: (qty: number) => void;
  setPrice: (price: number) => void;
  setStopPrice: (price: number) => void;
  reset: () => void;
}

const initial = {
  symbol: '',
  side: 'buy' as OrderSide,
  type: 'limit' as OrderType,
  qty: 0,
  price: 0,
  stopPrice: 0,
};

export const useOrderEntryStore = create<OrderFormState>((set) => ({
  ...initial,
  setSymbol: (symbol) => set({ symbol }),
  setSide: (side) => set({ side }),
  setType: (type) => set({ type }),
  setQty: (qty) => set({ qty }),
  setPrice: (price) => set({ price }),
  setStopPrice: (stopPrice) => set({ stopPrice }),
  reset: () => set(initial),
}));
