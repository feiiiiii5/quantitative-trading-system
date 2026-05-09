export type BacktestStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface BacktestJob {
  jobId: string;
  strategy: string;
  symbols: string[];
  status: BacktestStatus;
  progress: number;
  currentDate?: string;
  startedAt: number;
  completedAt?: number;
}

export interface BacktestMetrics {
  totalReturn: number;
  cagr: number;
  sharpeRatio: number;
  sortinoRatio: number;
  calmarRatio: number;
  maxDrawdown: number;
  maxDrawdownDuration: number;
  winRate: number;
  profitFactor: number;
  avgTradeDuration: number;
  totalTrades: number;
  avgTradePnl: number;
  bestTrade: number;
  worstTrade: number;
}

export interface BacktestResult {
  jobId: string;
  metrics: BacktestMetrics;
  equityCurve: Array<{ time: number; value: number }>;
  drawdownCurve: Array<{ time: number; value: number }>;
  monthlyReturns: number[][];
  tradePnlDistribution: Array<{ range: string; count: number }>;
  trades: Array<{
    id: string;
    symbol: string;
    side: string;
    entryDate: string;
    exitDate: string;
    entryPrice: number;
    exitPrice: number;
    qty: number;
    pnl: number;
    pnlPct: number;
  }>;
}

export interface BacktestConfig {
  strategy: string;
  symbols: string[];
  startDate: string;
  endDate: string;
  capital: number;
  commission: number;
  slippage: 'market' | 'realistic' | 'zero';
  parameters: Record<string, unknown>;
}
