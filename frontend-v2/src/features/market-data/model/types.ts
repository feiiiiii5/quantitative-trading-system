export interface DepthLevel {
  price: number;
  size: number;
  total: number;
}

export interface DepthData {
  bids: DepthLevel[];
  asks: DepthLevel[];
  spread: number;
  midPrice: number;
}

export interface TradeRecord {
  id: string;
  price: number;
  qty: number;
  side: 'buy' | 'sell';
  timestamp: number;
}
