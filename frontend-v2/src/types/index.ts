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
  turnover?: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
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

export interface PortfolioSummary {
  total_positions: number;
  total_value: number;
  avg_change_pct: number;
  positions: Array<{
    symbol: string;
    name: string;
    price: number;
    change_pct: number;
  }>;
}

export interface NewsItem {
  title: string;
  source: string;
  time: string;
  url: string;
  sentiment?: number;
  sentiment_label?: string;
  related_symbols?: string[];
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
