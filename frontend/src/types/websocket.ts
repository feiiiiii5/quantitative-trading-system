export interface QuoteMessage {
  type: 'quote';
  symbol: string;
  price: number;
  change: number;
  change_pct: number;
  volume: number;
  amount: number;
  [key: string]: unknown;
}

export interface IndexMessage {
  type: 'index';
  data: Array<{
    name: string;
    code: string;
    price: number;
    change: number;
    change_pct: number;
  }>;
}

export interface RegimeMessage {
  type: 'regime';
  symbol: string;
  regime: 'BULL' | 'BEAR' | 'CHOP' | 'VOLATILE';
  timestamp: string;
}

export interface AlertMessage {
  type: 'alert';
  level: 'info' | 'warn' | 'error';
  title: string;
  body?: string;
}

export type WSMessage = QuoteMessage | IndexMessage | RegimeMessage | AlertMessage;
