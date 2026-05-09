export interface Position {
  symbol: string;
  side: 'long' | 'short';
  qty: number;
  avgEntryPrice: number;
  currentPrice: number;
  unrealizedPnl: number;
  unrealizedPnlPct: number;
  marketValue: number;
  weight: number;
}

export interface PortfolioSummary {
  totalValue: number;
  cash: number;
  unrealizedPnl: number;
  realizedPnl: number;
  dailyPnl: number;
  dailyPnlPct: number;
  positions: Position[];
}
