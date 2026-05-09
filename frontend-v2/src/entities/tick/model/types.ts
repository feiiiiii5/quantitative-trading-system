export interface TickData {
  symbol: string;
  price: number;
  volume: number;
  timestamp: number;
  change: number;
  changePct: number;
  high: number;
  low: number;
  open: number;
  prevClose: number;
}

export interface KlineBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export type KlineInterval = '1m' | '5m' | '15m' | '1h' | '4h' | '1d' | '1w';
