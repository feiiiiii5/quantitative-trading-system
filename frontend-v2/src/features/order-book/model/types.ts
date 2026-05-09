export interface OrderBookLevel {
  price: number;
  size: number;
  total: number;
  depth: number;
}

export interface OrderBookUpdate {
  bids: OrderBookLevel[];
  asks: OrderBookLevel[];
  spread: number;
  midPrice: number;
}

export type GroupSize = 0.01 | 0.1 | 1 | 10 | 100;
