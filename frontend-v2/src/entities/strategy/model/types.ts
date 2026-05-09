export type StrategyStatus = 'running' | 'paused' | 'stopped' | 'error';

export interface Strategy {
  id: string;
  name: string;
  description: string;
  symbols: string[];
  status: StrategyStatus;
  capital: number;
  unrealizedPnl: number;
  realizedPnl: number;
  totalPnl: number;
  position?: {
    side: 'long' | 'short' | 'flat';
    qty: number;
    avgEntryPrice: number;
    currentPrice: number;
  };
  metrics: {
    sharpe30d: number;
    maxDrawdown: number;
    winRate: number;
    profitFactor: number;
  };
  parameters: Record<string, unknown>;
  parameterSchema?: Record<string, unknown>;
  equityCurve?: Array<{ time: number; value: number }>;
  startedAt?: number;
  updatedAt: number;
}

export interface StrategySignal {
  strategyId: string;
  symbol: string;
  side: 'buy' | 'sell';
  price: number;
  timestamp: number;
  confidence?: number;
}
