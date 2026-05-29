import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/api/client';

export interface ChipData {
  symbol: string;
  current_price: number;
  avg_cost: number;
  profit_ratio: number;
  concentration: number;
  support_price: number;
  resistance_price: number;
  peak_price: number;
  prices: number[];
  distribution: number[];
  chip_bands: Array<{ range: string; price_low: number; price_high: number; weight: number }>;
  fire: Record<string, unknown>;
}

export interface NewsItem {
  title: string;
  source: string;
  url: string;
  time: string;
  content: string;
  sentiment: number;
  sentiment_label: string;
  related_symbols: string[];
}

export interface SentimentData {
  sentiment: {
    fear_greed_index: number;
    label: string;
    news_sentiment: number;
    volume_sentiment: number;
    momentum_sentiment: number;
    breadth_sentiment: number;
  };
  summary: { total: number; bullish: number; bearish: number; neutral: number };
}

export interface GarchData {
  current_volatility: number;
  long_run_volatility: number;
  persistence: number;
  omega: number;
  alpha: number;
  beta: number;
  forecast_5d: number;
  forecast_10d: number;
  forecast_22d: number;
  forecast_series: Array<{ day: number; volatility_annualized: number }>;
}

export interface HmmData {
  current_state: number;
  current_label: string;
  state_probabilities: Record<string, number>;
  states: Array<{
    label: string;
    mean_daily_return: number;
    annualized_volatility: number;
    weight: number;
  }>;
}

export interface RollingRiskPoint {
  date: string;
  sharpe: number;
  sortino: number;
  calmar: number;
  volatility: number;
  max_drawdown: number;
  var_95: number;
  cvar_95: number;
  win_rate: number;
}

export interface RollingRiskData {
  symbol: string;
  window: number;
  latest: RollingRiskPoint;
  history: RollingRiskPoint[];
}

export interface SeasonalityData {
  symbol: string;
  period: string;
  monthly_returns: Record<string, number>;
  day_of_week_returns: Record<string, number>;
  best_month: string;
  worst_month: string;
  best_day: string;
  worst_day: string;
  monthly_sharpe: Record<string, number>;
  turn_of_month_effect: {
    tom_avg_return: number;
    non_tom_avg_return: number;
    tom_win_rate: number;
    non_tom_win_rate: number;
  };
  seasonality_strength: number;
}

export const stockDetailKeys = {
  all: ['stock-detail'] as const,
  chip: (symbol: string) => [...stockDetailKeys.all, 'chip', symbol] as const,
  news: (symbol: string) => [...stockDetailKeys.all, 'news', symbol] as const,
  sentiment: (symbol: string) => [...stockDetailKeys.all, 'sentiment', symbol] as const,
  garch: (symbol: string) => [...stockDetailKeys.all, 'garch', symbol] as const,
  hmm: (symbol: string) => [...stockDetailKeys.all, 'hmm', symbol] as const,
  rollingRisk: (symbol: string) => [...stockDetailKeys.all, 'rolling-risk', symbol] as const,
  seasonality: (symbol: string) => [...stockDetailKeys.all, 'seasonality', symbol] as const,
};

export function useChipDistribution(symbol: string) {
  return useQuery({
    queryKey: stockDetailKeys.chip(symbol),
    queryFn: () => apiGet<ChipData>(`/chip/${symbol}`),
    enabled: symbol.length > 0,
    staleTime: 120_000,
  });
}

export function useStockNews(symbol: string) {
  return useQuery({
    queryKey: stockDetailKeys.news(symbol),
    queryFn: () => apiGet<NewsItem[]>(`/news/stock/${symbol}`, { limit: 10 }),
    enabled: symbol.length > 0,
    staleTime: 60_000,
  });
}

export function useNewsSentiment(symbol: string) {
  return useQuery({
    queryKey: stockDetailKeys.sentiment(symbol),
    queryFn: () => apiGet<SentimentData>('/news/sentiment', { symbol }),
    enabled: symbol.length > 0,
    staleTime: 60_000,
  });
}

export function useGarchVolatility(symbol: string) {
  return useQuery({
    queryKey: stockDetailKeys.garch(symbol),
    queryFn: () => apiGet<GarchData>(`/volatility/garch/${symbol}`),
    enabled: symbol.length > 0,
    staleTime: 120_000,
  });
}

export function useHmmRegime(symbol: string) {
  return useQuery({
    queryKey: stockDetailKeys.hmm(symbol),
    queryFn: () => apiGet<HmmData>(`/regime/hmm/${symbol}`),
    enabled: symbol.length > 0,
    staleTime: 120_000,
  });
}

export function useRollingRisk(symbol: string) {
  return useQuery({
    queryKey: stockDetailKeys.rollingRisk(symbol),
    queryFn: () => apiGet<RollingRiskData>(`/rolling-risk/${symbol}`),
    enabled: symbol.length > 0,
    staleTime: 120_000,
  });
}

export function useSeasonality(symbol: string) {
  return useQuery({
    queryKey: stockDetailKeys.seasonality(symbol),
    queryFn: () => apiGet<SeasonalityData>(`/seasonality/${symbol}`),
    enabled: symbol.length > 0,
    staleTime: 600_000,
  });
}
