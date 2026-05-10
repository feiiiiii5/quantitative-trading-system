export interface KlineBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface StockQuote {
  symbol: string;
  name: string;
  price: number;
  change: number;
  change_pct: number;
  volume: number;
  amount: number;
  pe?: number;
  pb?: number;
  turnover?: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  sector?: string;
}

export interface IndexQuote {
  name: string;
  code: string;
  price: number;
  change: number;
  change_pct: number;
}

export interface StrategyInfo {
  name: string;
  aliases: string[];
  description: string;
}

export interface BacktestResult {
  total_return: number;
  annual_return: number;
  sharpe_ratio: number;
  max_drawdown: number;
  calmar_ratio: number;
  win_rate: number;
  profit_factor: number;
  total_trades: number;
  equity_curve: Array<{ date: string; value: number }>;
  trades: Array<Record<string, unknown>>;
}

export interface SectorData {
  name: string;
  change_pct: number;
  volume: number;
  amount: number;
  leading_stock?: string;
}

export interface MarketOverview {
  advance_count: number;
  decline_count: number;
  flat_count: number;
  total_amount: number;
  north_flow?: number;
}

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export interface RiskAlert {
  id: string;
  level: RiskLevel;
  message: string;
  value: number;
  timestamp: number;
}

export interface RiskMetrics {
  riskLevel: RiskLevel;
  var95: number;
  cvar: number;
  maxDrawdown: number;
  sharpe: number;
  beta: number;
  riskDecomposition: Array<{ source: string; contribution: number }>;
  correlationMatrix: { labels: string[]; values: number[][] };
  historicalVol: number[];
  impliedVol: number[];
  volDates: string[];
}

export interface OrderBookEntry {
  price: number;
  quantity: number;
  orders: number;
}

export interface TradeRecord {
  id: string;
  price: number;
  quantity: number;
  amount: number;
  direction: 'BUY' | 'SELL';
  time: string;
}

export interface ExecutionStats {
  vwap: number;
  twap: number;
  avgSlippage: number;
  fillRate: number;
}

export type SignalAction = 'BUY' | 'SELL' | 'HOLD';

export interface SignalItem {
  symbol: string;
  name: string;
  action: SignalAction;
  change_pct: number;
  confidence?: number;
  reason?: string;
}
