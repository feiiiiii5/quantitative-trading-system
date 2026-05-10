import { useEffect, useRef, useState, useCallback, memo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { createChart, CandlestickSeries, HistogramSeries, type IChartApi, type CandlestickData, type HistogramData, type Time } from 'lightweight-charts';
import { apiGet } from '@/api/client';
import { useCanvas } from '@/hooks/useCanvas';
import { formatPrice, formatPercent, formatVolume, formatAmount } from '@/utils/format';
import type { StockQuote } from '@/types';

interface MoneyFlowRealtime {
  symbol: string;
  name: string;
  price: number;
  change_pct: number;
  main_net_inflow: number;
  main_inflow: number;
  main_outflow: number;
  super_large_net: number;
  large_net: number;
  medium_net: number;
  small_net: number;
  main_pct: number;
}

interface MoneyFlowHistoryItem {
  date: string;
  main_inflow: number;
  main_outflow: number;
  main_net_inflow: number;
  super_large_net: number;
  large_net: number;
  medium_net: number;
  small_net: number;
}

interface MoneyFlowData {
  symbol: string;
  realtime: MoneyFlowRealtime;
  history: MoneyFlowHistoryItem[];
  pattern: {
    pattern: string;
    trend: string;
    total_main_net: number;
    avg_main_net: number;
    max_inflow: number;
    max_outflow: number;
  };
}

interface ChipData {
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

interface NewsItem {
  title: string;
  source: string;
  url: string;
  time: string;
  content: string;
  sentiment: number;
  sentiment_label: string;
  related_symbols: string[];
}

interface SentimentData {
  sentiment: {
    fear_greed_index: number;
    label: string;
    news_sentiment: number;
    volume_sentiment: number;
    momentum_sentiment: number;
    breadth_sentiment: number;
  };
  summary: {
    total: number;
    bullish: number;
    bearish: number;
    neutral: number;
  };
}

interface GarchData {
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

interface HmmData {
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

interface RollingRiskPoint {
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

interface RollingRiskData {
  symbol: string;
  window: number;
  latest: RollingRiskPoint;
  history: RollingRiskPoint[];
}

interface SeasonalityData {
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

interface KlineRaw {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

function msToTime(ts: number): Time {
  const d = new Date(ts);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}` as Time;
}

const MoneyFlowTab = memo(function MoneyFlowTab({ symbol }: { symbol: string }) {
  const [data, setData] = useState<MoneyFlowData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    apiGet<MoneyFlowData>(`/moneyflow/stock/${symbol}`)
      .then(d => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setError(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [symbol]);

  const { ref: chartRef, redraw: redrawChart } = useCanvas(
    useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
      if (!data) return;
      ctx.clearRect(0, 0, w, h);

      const history = data.history ?? [];
      if (history.length === 0) return;

      const padLeft = 8;
      const padRight = 8;
      const padTop = 28;
      const padBottom = 24;
      const chartW = w - padLeft - padRight;
      const chartH = h - padTop - padBottom;
      const barGroupWidth = chartW / history.length;
      const barWidth = Math.max(1, barGroupWidth * 0.35);
      const gap = Math.max(1, barGroupWidth * 0.1);

      ctx.font = '9px monospace';
      ctx.fillStyle = 'rgba(255,255,255,0.35)';
      ctx.textAlign = 'left';
      ctx.fillText('主力', padLeft, padTop - 10);
      ctx.fillStyle = '#FF1744';
      ctx.fillRect(padLeft + 24, padTop - 16, 8, 8);
      ctx.fillStyle = 'rgba(255,255,255,0.35)';
      ctx.fillText('散户', padLeft + 40, padTop - 10);
      ctx.fillStyle = '#0A84FF';
      ctx.fillRect(padLeft + 64, padTop - 16, 8, 8);

      const allValues = history.flatMap(d => [d.main_net_inflow, -(d.medium_net + d.small_net)]);
      const maxAbs = Math.max(1, ...allValues.map(Math.abs));
      const zeroY = padTop + chartH / 2;

      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(padLeft, zeroY);
      ctx.lineTo(w - padRight, zeroY);
      ctx.stroke();

      for (let i = 0; i < history.length; i++) {
        const item = history[i]!;
        const x = padLeft + i * barGroupWidth + barGroupWidth / 2;

        const mainH = (item.main_net_inflow / maxAbs) * (chartH / 2);
        ctx.fillStyle = item.main_net_inflow >= 0 ? '#FF1744' : '#00C853';
        if (mainH >= 0) {
          ctx.fillRect(x - barWidth - gap / 2, zeroY - mainH, barWidth, mainH);
        } else {
          ctx.fillRect(x - barWidth - gap / 2, zeroY, barWidth, -mainH);
        }

        const retailNet = -(item.medium_net + item.small_net);
        const retailH = (retailNet / maxAbs) * (chartH / 2);
        ctx.fillStyle = retailNet >= 0 ? '#FF1744' : '#00C853';
        if (retailH >= 0) {
          ctx.fillRect(x + gap / 2, zeroY - retailH, barWidth, retailH);
        } else {
          ctx.fillRect(x + gap / 2, zeroY, barWidth, -retailH);
        }

        if (i % Math.max(1, Math.floor(history.length / 6)) === 0) {
          ctx.fillStyle = 'rgba(255,255,255,0.35)';
          ctx.font = '8px monospace';
          ctx.textAlign = 'center';
          ctx.fillText(item.date.slice(5, 10), x, h - 6);
        }
      }
    }, [data]),
    [data],
  );

  useEffect(() => { redrawChart(); }, [data, redrawChart]);

  if (loading) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '200px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em' }}>LOADING...</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '200px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em' }}>资金流向数据暂无</span>
      </div>
    );
  }

  const rt = data.realtime;
  const retailNet = -(rt.medium_net + rt.small_net);
  const flowCategories = [
    { label: '超大单', value: rt.super_large_net },
    { label: '大单', value: rt.large_net },
    { label: '中单', value: rt.medium_net },
    { label: '小单', value: rt.small_net },
    { label: '合计', value: rt.main_net_inflow + retailNet },
  ];

  const maxFlow = Math.max(1, ...flowCategories.map(c => Math.abs(c.value)));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
      <canvas ref={chartRef} style={{ width: '100%', height: '260px', display: 'block' }} />

      <div style={{ display: 'flex', gap: 'var(--s4)', flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 140px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>主力净流入</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 600, color: rt.main_net_inflow >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
            {rt.main_net_inflow >= 0 ? '+' : ''}{formatAmount(rt.main_net_inflow)}
          </span>
        </div>
        <div style={{ flex: '1 1 140px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>散户净流入</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 600, color: retailNet >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
            {retailNet >= 0 ? '+' : ''}{formatAmount(retailNet)}
          </span>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {flowCategories.map(cat => {
          const pct = maxFlow > 0 ? (cat.value / maxFlow) * 100 : 0;
          const isPositive = cat.value >= 0;
          return (
            <div key={cat.label} style={{ display: 'flex', alignItems: 'center', gap: 'var(--s3)' }}>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: 'rgba(255,255,255,0.35)', width: '36px', flexShrink: 0 }}>{cat.label}</span>
              <div style={{ flex: 1, height: '16px', background: 'rgba(255,255,255,0.06)', borderRadius: '2px', overflow: 'hidden', position: 'relative' }}>
                <div style={{
                  position: 'absolute',
                  height: '100%',
                  width: `${Math.abs(pct)}%`,
                  background: isPositive ? '#FF1744' : '#00C853',
                  borderRadius: '2px',
                  opacity: 0.85,
                  left: isPositive ? '50%' : `${50 - Math.abs(pct)}%`,
                }} />
                <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: '1px', background: 'rgba(255,255,255,0.12)' }} />
              </div>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: isPositive ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums', width: '72px', textAlign: 'right', flexShrink: 0 }}>
                {cat.value >= 0 ? '+' : ''}{formatAmount(cat.value)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
});

const ChipDistributionTab = memo(function ChipDistributionTab({ symbol }: { symbol: string }) {
  const [data, setData] = useState<ChipData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    apiGet<ChipData>(`/chip/${symbol}`)
      .then(d => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setError(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [symbol]);

  const { ref: chartRef, redraw: redrawChart } = useCanvas(
    useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
      if (!data) return;
      ctx.clearRect(0, 0, w, h);

      const dist = data.distribution ?? [];
      const prices = data.prices ?? [];
      if (dist.length === 0 || prices.length === 0) return;
      const len = Math.min(dist.length, prices.length);

      const padLeft = 52;
      const padRight = 12;
      const padTop = 8;
      const padBottom = 28;
      const chartW = w - padLeft - padRight;
      const chartH = h - padTop - padBottom;

      const maxVol = Math.max(1e-10, ...dist.slice(0, len));
      const minPrice = Math.min(...prices.slice(0, len));
      const maxPrice = Math.max(...prices.slice(0, len));
      const priceRange = Math.max(0.01, maxPrice - minPrice);

      const barHeight = Math.max(2, (chartH / len) * 0.7);
      const barSpacing = chartH / len;

      const currentPrice = data.current_price;

      for (let i = 0; i < len; i++) {
        const vol = dist[i]!;
        const price = prices[i]!;
        const y = padTop + i * barSpacing + barSpacing / 2;
        const barW = (vol / maxVol) * chartW;

        const profitPct = currentPrice > 0 ? ((currentPrice - price) / currentPrice) * 100 : 0;
        let color: string;
        if (profitPct > 5) {
          color = '#FF1744';
        } else if (profitPct > 0) {
          color = 'rgba(255,23,68,0.6)';
        } else if (profitPct > -5) {
          color = 'rgba(0,200,83,0.6)';
        } else {
          color = '#00C853';
        }

        ctx.fillStyle = color;
        ctx.fillRect(padLeft, y - barHeight / 2, barW, barHeight);

        ctx.fillStyle = 'rgba(255,255,255,0.35)';
        ctx.font = '8px monospace';
        ctx.textAlign = 'right';
        ctx.fillText(price.toFixed(2), padLeft - 4, y + 3);
      }

      const avgY = padTop + ((data.avg_cost - minPrice) / priceRange) * chartH;
      ctx.strokeStyle = '#0A84FF';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(padLeft, avgY);
      ctx.lineTo(w - padRight, avgY);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = '#0A84FF';
      ctx.font = '8px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(`成本 ${data.avg_cost.toFixed(2)}`, w - padRight - 64, avgY - 4);

      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(padLeft, padTop);
      ctx.lineTo(padLeft, h - padBottom);
      ctx.stroke();
    }, [data]),
    [data],
  );

  useEffect(() => { redrawChart(); }, [data, redrawChart]);

  if (loading) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '200px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em' }}>LOADING...</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '200px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em' }}>筹码分布数据暂无</span>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
      <div style={{ display: 'flex', gap: 'var(--s4)', flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 100px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>获利比例</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 600, color: '#FF1744', fontVariantNumeric: 'tabular-nums' }}>
            {(data.profit_ratio * 100).toFixed(1)}%
          </span>
        </div>
        <div style={{ flex: '1 1 100px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>平均成本</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 600, color: 'rgba(255,255,255,0.95)', fontVariantNumeric: 'tabular-nums' }}>
            {data.avg_cost.toFixed(2)}
          </span>
        </div>
        <div style={{ flex: '1 1 100px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>集中度</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 600, color: '#0A84FF', fontVariantNumeric: 'tabular-nums' }}>
            {(data.concentration * 100).toFixed(1)}%
          </span>
        </div>
      </div>

      <canvas ref={chartRef} style={{ width: '100%', height: '300px', display: 'block' }} />

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s4)', justifyContent: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <div style={{ width: '8px', height: '8px', borderRadius: '1px', background: '#FF1744' }} />
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'rgba(255,255,255,0.35)' }}>盈利</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <div style={{ width: '8px', height: '8px', borderRadius: '1px', background: '#00C853' }} />
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'rgba(255,255,255,0.35)' }}>亏损</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <div style={{ width: '8px', height: '2px', background: '#0A84FF' }} />
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'rgba(255,255,255,0.35)' }}>平均成本</span>
        </div>
      </div>
    </div>
  );
});

const NewsTab = memo(function NewsTab({ symbol }: { symbol: string }) {
  const [news, setNews] = useState<NewsItem[]>([]);
  const [sentiment, setSentiment] = useState<SentimentData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    Promise.all([
      apiGet<NewsItem[]>(`/news/stock/${symbol}`, { limit: 10 }),
      apiGet<SentimentData>(`/news/sentiment`, { symbol }),
    ])
      .then(([n, s]) => {
        if (!cancelled) {
          setNews(Array.isArray(n) ? n : []);
          setSentiment(s);
        }
      })
      .catch(() => { if (!cancelled) setError(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [symbol]);

  if (loading) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '200px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em' }}>LOADING...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '200px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em' }}>资讯数据暂无</span>
      </div>
    );
  }

  const fgIndex = sentiment?.sentiment?.fear_greed_index ?? 50;
  const fgLabel = sentiment?.sentiment?.label ?? '—';
  const summary = sentiment?.summary;

  const gaugeColor = (val: number): string => {
    if (val <= 25) return '#FF1744';
    if (val <= 50) return '#FF9100';
    if (val <= 75) return '#FFD600';
    return '#00C853';
  };

  const sentimentBadgeColor = (label: string): string => {
    if (label === 'positive') return '#FF1744';
    if (label === 'negative') return '#00C853';
    return 'rgba(255,255,255,0.35)';
  };

  const sentimentBadgeText = (label: string): string => {
    if (label === 'positive') return '利好';
    if (label === 'negative') return '利空';
    return '中性';
  };

  const formatTime = (ts: string): string => {
    const d = new Date(Number(ts) * 1000);
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const hh = String(d.getHours()).padStart(2, '0');
    const mi = String(d.getMinutes()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s5)' }}>
      {sentiment && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--s3)' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>恐惧贪婪指数</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '24px', fontWeight: 700, color: gaugeColor(fgIndex), fontVariantNumeric: 'tabular-nums' }}>{fgIndex.toFixed(0)}</span>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '12px', color: gaugeColor(fgIndex) }}>{fgLabel}</span>
            </div>
            <div style={{ height: '8px', borderRadius: '4px', background: 'rgba(255,255,255,0.06)', position: 'relative', overflow: 'hidden' }}>
              <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${fgIndex}%`, background: `linear-gradient(to right, #FF1744, #FF9100, #FFD600, #00C853)`, borderRadius: '4px', opacity: 0.85 }} />
            </div>
          </div>

          {summary && (
            <div style={{ display: 'flex', gap: 'var(--s4)', flexWrap: 'wrap' }}>
              <div style={{ flex: '1 1 80px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>总计</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: 'rgba(255,255,255,0.90)', fontVariantNumeric: 'tabular-nums' }}>{summary.total}</span>
              </div>
              <div style={{ flex: '1 1 80px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>利好</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: '#FF1744', fontVariantNumeric: 'tabular-nums' }}>{summary.bullish}</span>
              </div>
              <div style={{ flex: '1 1 80px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>利空</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: '#00C853', fontVariantNumeric: 'tabular-nums' }}>{summary.bearish}</span>
              </div>
              <div style={{ flex: '1 1 80px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>中性</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: 'rgba(255,255,255,0.60)', fontVariantNumeric: 'tabular-nums' }}>{summary.neutral}</span>
              </div>
            </div>
          )}
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', maxHeight: '400px', overflowY: 'auto' }}>
        {news.map((item, idx) => (
          <div key={idx} style={{ padding: '10px 0', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s3)', marginBottom: '4px' }}>
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ fontFamily: 'var(--font-sans)', fontSize: '13px', color: 'rgba(255,255,255,0.90)', textDecoration: 'none', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
              >
                {item.title}
              </a>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '9px',
                padding: '2px 6px',
                borderRadius: 'var(--r-xs)',
                background: sentimentBadgeColor(item.sentiment_label) === 'rgba(255,255,255,0.35)' ? 'rgba(255,255,255,0.08)' : `${sentimentBadgeColor(item.sentiment_label)}20`,
                color: sentimentBadgeColor(item.sentiment_label),
                flexShrink: 0,
              }}>
                {sentimentBadgeText(item.sentiment_label)}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s3)', marginBottom: '4px' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'rgba(255,255,255,0.35)' }}>{formatTime(item.time)}</span>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'rgba(255,255,255,0.25)' }}>{item.source}</span>
            </div>
            <div style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: 'rgba(255,255,255,0.45)', lineHeight: 1.5 }}>
              {item.content.length > 100 ? `${item.content.slice(0, 100)}...` : item.content}
            </div>
          </div>
        ))}
        {news.length === 0 && (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'rgba(255,255,255,0.35)', padding: 'var(--s5)', textAlign: 'center' }}>暂无资讯</span>
        )}
      </div>
    </div>
  );
});

const VolatilityTab = memo(function VolatilityTab({ symbol }: { symbol: string }) {
  const [garch, setGarch] = useState<GarchData | null>(null);
  const [hmm, setHmm] = useState<HmmData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    Promise.all([
      apiGet<GarchData>(`/volatility/garch/${symbol}`),
      apiGet<HmmData>(`/regime/hmm/${symbol}`),
    ])
      .then(([g, h]) => {
        if (!cancelled) {
          setGarch(g);
          setHmm(h);
        }
      })
      .catch(() => { if (!cancelled) setError(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [symbol]);

  const { ref: chartRef, redraw: redrawChart } = useCanvas(
    useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
      if (!garch) return;
      ctx.clearRect(0, 0, w, h);

      const series = garch.forecast_series ?? [];
      if (series.length === 0) return;

      const padLeft = 48;
      const padRight = 12;
      const padTop = 20;
      const padBottom = 28;
      const chartW = w - padLeft - padRight;
      const chartH = h - padTop - padBottom;

      const vols = series.map(s => s.volatility_annualized);
      const minVol = Math.min(...vols, garch.current_volatility) * 0.9;
      const maxVol = Math.max(...vols, garch.current_volatility) * 1.1;
      const volRange = Math.max(0.001, maxVol - minVol);

      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = padTop + (i / 4) * chartH;
        ctx.beginPath();
        ctx.moveTo(padLeft, y);
        ctx.lineTo(w - padRight, y);
        ctx.stroke();

        const val = maxVol - (i / 4) * volRange;
        ctx.fillStyle = 'rgba(255,255,255,0.35)';
        ctx.font = '8px monospace';
        ctx.textAlign = 'right';
        ctx.fillText(`${(val * 100).toFixed(1)}%`, padLeft - 4, y + 3);
      }

      const currentY = padTop + ((maxVol - garch.current_volatility) / volRange) * chartH;
      ctx.strokeStyle = '#0A84FF';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(padLeft, currentY);
      ctx.lineTo(w - padRight, currentY);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = '#0A84FF';
      ctx.font = '8px monospace';
      ctx.textAlign = 'left';
      ctx.fillText(`当前 ${(garch.current_volatility * 100).toFixed(1)}%`, padLeft + 4, currentY - 4);

      ctx.strokeStyle = '#FF9100';
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let i = 0; i < series.length; i++) {
        const x = padLeft + (i / Math.max(1, series.length - 1)) * chartW;
        const y = padTop + ((maxVol - series[i]!.volatility_annualized) / volRange) * chartH;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      for (let i = 0; i < series.length; i++) {
        if (i % Math.max(1, Math.floor(series.length / 6)) === 0) {
          const x = padLeft + (i / Math.max(1, series.length - 1)) * chartW;
          ctx.fillStyle = 'rgba(255,255,255,0.35)';
          ctx.font = '8px monospace';
          ctx.textAlign = 'center';
          ctx.fillText(`D${series[i]!.day}`, x, h - 6);
        }
      }
    }, [garch]),
    [garch],
  );

  useEffect(() => { redrawChart(); }, [garch, redrawChart]);

  if (loading) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '200px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em' }}>LOADING...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '200px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em' }}>波动率数据暂无</span>
      </div>
    );
  }

  const stateBadgeColor = (label: string): { color: string; bg: string } => {
    if (label === 'BULL') return { color: '#FF1744', bg: 'rgba(255,23,68,0.12)' };
    if (label === 'BEAR') return { color: '#00C853', bg: 'rgba(0,200,83,0.12)' };
    return { color: 'rgba(255,255,255,0.60)', bg: 'rgba(255,255,255,0.08)' };
  };

  const stateLabelMap: Record<string, string> = { BULL: '牛市', BEAR: '熊市', NEUTRAL: '震荡' };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s5)' }}>
      {garch && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>GARCH 波动率</span>
          <div style={{ display: 'flex', gap: 'var(--s4)', flexWrap: 'wrap' }}>
            {[
              { label: '当前波动率', value: `${(garch.current_volatility * 100).toFixed(2)}%` },
              { label: '长期波动率', value: `${(garch.long_run_volatility * 100).toFixed(2)}%` },
              { label: '持续性', value: `${(garch.persistence * 100).toFixed(1)}%` },
              { label: '5日预测', value: `${(garch.forecast_5d * 100).toFixed(2)}%` },
              { label: '10日预测', value: `${(garch.forecast_10d * 100).toFixed(2)}%` },
              { label: '22日预测', value: `${(garch.forecast_22d * 100).toFixed(2)}%` },
            ].map(m => (
              <div key={m.label} style={{ flex: '1 1 80px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{m.label}</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: 'rgba(255,255,255,0.90)', fontVariantNumeric: 'tabular-nums' }}>{m.value}</span>
              </div>
            ))}
          </div>
          <canvas ref={chartRef} style={{ width: '100%', height: '220px', display: 'block' }} />
        </div>
      )}

      {hmm && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>HMM 市场状态</span>

          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s3)' }}>
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              fontWeight: 600,
              padding: '3px 10px',
              borderRadius: 'var(--r-xs)',
              color: stateBadgeColor(hmm.current_label).color,
              background: stateBadgeColor(hmm.current_label).bg,
            }}>
              {stateLabelMap[hmm.current_label] ?? hmm.current_label}
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {Object.entries(hmm.state_probabilities).map(([state, prob]) => {
              const badge = stateBadgeColor(state);
              return (
                <div key={state} style={{ display: 'flex', alignItems: 'center', gap: 'var(--s3)' }}>
                  <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: badge.color, width: '40px', flexShrink: 0 }}>{stateLabelMap[state] ?? state}</span>
                  <div style={{ flex: 1, height: '12px', background: 'rgba(255,255,255,0.06)', borderRadius: '2px', overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${prob * 100}%`, background: badge.color, borderRadius: '2px', opacity: 0.75 }} />
                  </div>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'rgba(255,255,255,0.60)', fontVariantNumeric: 'tabular-nums', width: '48px', textAlign: 'right', flexShrink: 0 }}>
                    {(prob * 100).toFixed(1)}%
                  </span>
                </div>
              );
            })}
          </div>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
              <thead>
                <tr>
                  {['状态', '日均收益', '年化波动率', '权重'].map(h => (
                    <th key={h} style={{ padding: '6px 8px', textAlign: 'left', color: 'rgba(255,255,255,0.35)', fontWeight: 400, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {hmm.states.map(st => {
                  const badge = stateBadgeColor(st.label);
                  return (
                    <tr key={st.label}>
                      <td style={{ padding: '6px 8px', color: badge.color, borderBottom: '1px solid rgba(255,255,255,0.04)' }}>{stateLabelMap[st.label] ?? st.label}</td>
                      <td style={{ padding: '6px 8px', color: st.mean_daily_return >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                        {st.mean_daily_return >= 0 ? '+' : ''}{(st.mean_daily_return * 100).toFixed(3)}%
                      </td>
                      <td style={{ padding: '6px 8px', color: 'rgba(255,255,255,0.90)', fontVariantNumeric: 'tabular-nums', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                        {(st.annualized_volatility * 100).toFixed(2)}%
                      </td>
                      <td style={{ padding: '6px 8px', color: 'rgba(255,255,255,0.60)', fontVariantNumeric: 'tabular-nums', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                        {(st.weight * 100).toFixed(1)}%
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
});

const RollingRiskTab = memo(function RollingRiskTab({ symbol }: { symbol: string }) {
  const [data, setData] = useState<RollingRiskData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    apiGet<RollingRiskData>(`/rolling-risk/${symbol}`)
      .then(d => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setError(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [symbol]);

  const { ref: chartRef, redraw: redrawChart } = useCanvas(
    useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
      if (!data) return;
      ctx.clearRect(0, 0, w, h);

      const history = data.history ?? [];
      if (history.length === 0) return;

      const padLeft = 48;
      const padRight = 12;
      const padTop = 20;
      const padBottom = 28;
      const chartW = w - padLeft - padRight;
      const chartH = h - padTop - padBottom;

      const sharpes = history.map(p => p.sharpe);
      const minSharpe = Math.min(...sharpes, 0) * 1.1;
      const maxSharpe = Math.max(...sharpes, 0) * 1.1;
      const sharpeRange = Math.max(0.01, maxSharpe - minSharpe);

      const zeroY = padTop + ((maxSharpe - 0) / sharpeRange) * chartH;
      ctx.strokeStyle = 'rgba(255,255,255,0.15)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(padLeft, zeroY);
      ctx.lineTo(w - padRight, zeroY);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = padTop + (i / 4) * chartH;
        ctx.beginPath();
        ctx.moveTo(padLeft, y);
        ctx.lineTo(w - padRight, y);
        ctx.stroke();

        const val = maxSharpe - (i / 4) * sharpeRange;
        ctx.fillStyle = 'rgba(255,255,255,0.35)';
        ctx.font = '8px monospace';
        ctx.textAlign = 'right';
        ctx.fillText(val.toFixed(2), padLeft - 4, y + 3);
      }

      for (let i = 0; i < history.length - 1; i++) {
        const x0 = padLeft + (i / Math.max(1, history.length - 1)) * chartW;
        const x1 = padLeft + ((i + 1) / Math.max(1, history.length - 1)) * chartW;
        const y0 = padTop + ((maxSharpe - history[i]!.sharpe) / sharpeRange) * chartH;
        const y1 = padTop + ((maxSharpe - history[i + 1]!.sharpe) / sharpeRange) * chartH;
        ctx.strokeStyle = history[i]!.sharpe >= 0 ? '#FF1744' : '#00C853';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x0, y0);
        ctx.lineTo(x1, y1);
        ctx.stroke();
      }

      for (let i = 0; i < history.length; i++) {
        if (i % Math.max(1, Math.floor(history.length / 6)) === 0) {
          const x = padLeft + (i / Math.max(1, history.length - 1)) * chartW;
          ctx.fillStyle = 'rgba(255,255,255,0.35)';
          ctx.font = '8px monospace';
          ctx.textAlign = 'center';
          ctx.fillText(history[i]!.date.slice(5, 10), x, h - 6);
        }
      }
    }, [data]),
    [data],
  );

  useEffect(() => { redrawChart(); }, [data, redrawChart]);

  if (loading) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '200px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em' }}>LOADING...</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '200px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em' }}>滚动风险数据暂无</span>
      </div>
    );
  }

  const latest = data.latest;
  const aColor = (v: number) => v >= 0 ? '#FF1744' : '#00C853';

  const metrics = [
    { label: '夏普率', value: latest.sharpe.toFixed(2), color: aColor(latest.sharpe) },
    { label: '索提诺', value: latest.sortino.toFixed(2), color: aColor(latest.sortino) },
    { label: '卡玛', value: latest.calmar.toFixed(2), color: aColor(latest.calmar) },
    { label: '波动率', value: `${(latest.volatility * 100).toFixed(2)}%`, color: aColor(-latest.volatility) },
    { label: '最大回撤', value: `${(latest.max_drawdown * 100).toFixed(2)}%`, color: aColor(-latest.max_drawdown) },
    { label: 'VaR(95%)', value: `${(latest.var_95 * 100).toFixed(2)}%`, color: aColor(-latest.var_95) },
    { label: 'CVaR(95%)', value: `${(latest.cvar_95 * 100).toFixed(2)}%`, color: aColor(-latest.cvar_95) },
    { label: '胜率', value: `${(latest.win_rate * 100).toFixed(2)}%`, color: aColor(latest.win_rate - 0.5) },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s5)' }}>
      <div style={{ display: 'flex', gap: 'var(--s4)', flexWrap: 'wrap' }}>
        {metrics.map(m => (
          <div key={m.label} style={{ flex: '1 1 80px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>{m.label}</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: m.color, fontVariantNumeric: 'tabular-nums' }}>{m.value}</span>
          </div>
        ))}
      </div>

      <canvas ref={chartRef} style={{ width: '100%', height: '260px', display: 'block' }} />
    </div>
  );
});

const MONTH_ORDER = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTH_LABELS: Record<string, string> = {
  Jan: '1月', Feb: '2月', Mar: '3月', Apr: '4月', May: '5月', Jun: '6月',
  Jul: '7月', Aug: '8月', Sep: '9月', Oct: '10月', Nov: '11月', Dec: '12月',
};
const DAY_ORDER = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'];
const DAY_LABELS: Record<string, string> = { Mon: '周一', Tue: '周二', Wed: '周三', Thu: '周四', Fri: '周五' };

const SeasonalityTab = memo(function SeasonalityTab({ symbol }: { symbol: string }) {
  const [data, setData] = useState<SeasonalityData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    apiGet<SeasonalityData>(`/seasonality/${symbol}`)
      .then(d => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setError(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [symbol]);

  const { ref: chartRef, redraw: redrawChart } = useCanvas(
    useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
      if (!data) return;
      ctx.clearRect(0, 0, w, h);

      const monthlyReturns = data.monthly_returns ?? {};
      const entries = MONTH_ORDER.map(m => ({ month: m, value: monthlyReturns[m] ?? 0 }));
      if (entries.length === 0) return;

      const padLeft = 44;
      const padRight = 12;
      const padTop = 20;
      const padBottom = 28;
      const chartW = w - padLeft - padRight;
      const chartH = h - padTop - padBottom;

      const maxAbs = Math.max(0.001, ...entries.map(e => Math.abs(e.value)));
      const zeroY = padTop + chartH / 2;

      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(padLeft, zeroY);
      ctx.lineTo(w - padRight, zeroY);
      ctx.stroke();

      const barGroupWidth = chartW / entries.length;
      const barWidth = Math.max(4, barGroupWidth * 0.55);

      for (let i = 0; i <= 4; i++) {
        const y = padTop + (i / 4) * chartH;
        ctx.strokeStyle = 'rgba(255,255,255,0.06)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(padLeft, y);
        ctx.lineTo(w - padRight, y);
        ctx.stroke();

        const val = maxAbs - (i / 4) * 2 * maxAbs;
        ctx.fillStyle = 'rgba(255,255,255,0.35)';
        ctx.font = '8px monospace';
        ctx.textAlign = 'right';
        ctx.fillText(`${(val * 100).toFixed(1)}%`, padLeft - 4, y + 3);
      }

      for (let i = 0; i < entries.length; i++) {
        const entry = entries[i]!;
        const x = padLeft + i * barGroupWidth + barGroupWidth / 2;
        const barH = (entry.value / maxAbs) * (chartH / 2);
        const isPositive = entry.value >= 0;
        const isBest = entry.month === data.best_month;
        const isWorst = entry.month === data.worst_month;

        ctx.fillStyle = isPositive ? '#FF1744' : '#00C853';
        if (isBest) ctx.fillStyle = '#FFD600';
        if (isWorst) ctx.fillStyle = '#AA00FF';

        if (isPositive) {
          ctx.fillRect(x - barWidth / 2, zeroY - barH, barWidth, barH);
        } else {
          ctx.fillRect(x - barWidth / 2, zeroY, barWidth, -barH);
        }

        if (isBest) {
          ctx.fillStyle = '#FFD600';
          ctx.font = '10px sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText('★', x, zeroY - barH - 4);
        }
        if (isWorst) {
          ctx.fillStyle = '#AA00FF';
          ctx.font = '10px sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText('▼', x, zeroY - barH + (isPositive ? 0 : -barH) - 4);
        }

        ctx.fillStyle = 'rgba(255,255,255,0.45)';
        ctx.font = '8px monospace';
        ctx.textAlign = 'center';
        ctx.fillText(MONTH_LABELS[entry.month] ?? entry.month, x, h - 6);
      }
    }, [data]),
    [data],
  );

  useEffect(() => { redrawChart(); }, [data, redrawChart]);

  if (loading) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '200px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em' }}>LOADING...</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '200px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em' }}>季节性数据暂无</span>
      </div>
    );
  }

  const dayReturns = data.day_of_week_returns ?? {};
  const dayEntries = DAY_ORDER.map(d => ({ day: d, value: dayReturns[d] ?? 0 }));
  const maxDayAbs = Math.max(0.001, ...dayEntries.map(e => Math.abs(e.value)));

  const tom = data.turn_of_month_effect;
  const strengthPct = Math.min(100, Math.max(0, data.seasonality_strength * 100));
  const strengthColor = strengthPct > 60 ? '#FFD600' : strengthPct > 30 ? '#FF9100' : 'rgba(255,255,255,0.45)';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s5)' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>月度收益</span>
        <canvas ref={chartRef} style={{ width: '100%', height: '260px', display: 'block' }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s4)', justifyContent: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <div style={{ width: '8px', height: '8px', borderRadius: '1px', background: '#FF1744' }} />
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'rgba(255,255,255,0.35)' }}>上涨</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <div style={{ width: '8px', height: '8px', borderRadius: '1px', background: '#00C853' }} />
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'rgba(255,255,255,0.35)' }}>下跌</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span style={{ fontFamily: 'sans-serif', fontSize: '10px', color: '#FFD600' }}>★</span>
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'rgba(255,255,255,0.35)' }}>最佳月</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span style={{ fontFamily: 'sans-serif', fontSize: '10px', color: '#AA00FF' }}>▼</span>
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', color: 'rgba(255,255,255,0.35)' }}>最差月</span>
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>星期效应</span>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {dayEntries.map(entry => {
            const pct = maxDayAbs > 0 ? (entry.value / maxDayAbs) * 50 : 0;
            const isPositive = entry.value >= 0;
            const isBest = entry.day === data.best_day;
            const isWorst = entry.day === data.worst_day;
            let barColor = isPositive ? '#FF1744' : '#00C853';
            if (isBest) barColor = '#FFD600';
            if (isWorst) barColor = '#AA00FF';
            return (
              <div key={entry.day} style={{ display: 'flex', alignItems: 'center', gap: 'var(--s3)' }}>
                <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: isBest ? '#FFD600' : isWorst ? '#AA00FF' : 'rgba(255,255,255,0.35)', width: '32px', flexShrink: 0 }}>
                  {DAY_LABELS[entry.day] ?? entry.day}
                  {isBest && '★'}
                  {isWorst && '▼'}
                </span>
                <div style={{ flex: 1, height: '16px', background: 'rgba(255,255,255,0.06)', borderRadius: '2px', overflow: 'hidden', position: 'relative' }}>
                  <div style={{
                    position: 'absolute',
                    height: '100%',
                    width: `${Math.abs(pct)}%`,
                    background: barColor,
                    borderRadius: '2px',
                    opacity: 0.85,
                    left: isPositive ? '50%' : `${50 - Math.abs(pct)}%`,
                  }} />
                  <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: '1px', background: 'rgba(255,255,255,0.12)' }} />
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: barColor, fontVariantNumeric: 'tabular-nums', width: '60px', textAlign: 'right', flexShrink: 0 }}>
                  {entry.value >= 0 ? '+' : ''}{(entry.value * 100).toFixed(2)}%
                </span>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s4)' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>换月效应</span>
        <div style={{ display: 'flex', gap: 'var(--s4)' }}>
          <div style={{ flex: 1, padding: 'var(--s4)', borderRadius: 'var(--r-md)', border: '1px solid rgba(255,23,68,0.2)', background: 'rgba(255,23,68,0.06)' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#FF1744', fontWeight: 600 }}>换月期</span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>平均收益</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: tom.tom_avg_return >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
                  {tom.tom_avg_return >= 0 ? '+' : ''}{(tom.tom_avg_return * 100).toFixed(3)}%
                </span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>胜率</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: tom.tom_win_rate >= 0.5 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
                  {(tom.tom_win_rate * 100).toFixed(1)}%
                </span>
              </div>
            </div>
          </div>
          <div style={{ flex: 1, padding: 'var(--s4)', borderRadius: 'var(--r-md)', border: '1px solid rgba(0,200,83,0.2)', background: 'rgba(0,200,83,0.06)' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: '#00C853', fontWeight: 600 }}>非换月期</span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>平均收益</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: tom.non_tom_avg_return >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
                  {tom.non_tom_avg_return >= 0 ? '+' : ''}{(tom.non_tom_avg_return * 100).toFixed(3)}%
                </span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>胜率</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: tom.non_tom_win_rate >= 0.5 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
                  {(tom.non_tom_win_rate * 100).toFixed(1)}%
                </span>
              </div>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--s3)' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>季节性强度</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 700, color: strengthColor, fontVariantNumeric: 'tabular-nums' }}>
              {strengthPct.toFixed(0)}
            </span>
          </div>
          <div style={{ height: '6px', borderRadius: '3px', background: 'rgba(255,255,255,0.06)', position: 'relative', overflow: 'hidden' }}>
            <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${strengthPct}%`, background: strengthColor, borderRadius: '3px', opacity: 0.75 }} />
          </div>
        </div>
      </div>
    </div>
  );
});

const KlineChart = memo(function KlineChart({ symbol }: { symbol: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    let cancelled = false;
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 480,
      layout: {
        background: { color: 'transparent' as const },
        textColor: 'rgba(255,255,255,0.35)',
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.06)' },
        horzLines: { color: 'rgba(255,255,255,0.06)' },
      },
      crosshair: { mode: 0 },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.06)' },
      timeScale: { borderColor: 'rgba(255,255,255,0.06)', timeVisible: false },
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#FF1744',
      downColor: '#00C853',
      borderUpColor: '#FF1744',
      borderDownColor: '#00C853',
      wickUpColor: '#FF1744',
      wickDownColor: '#00C853',
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });

    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });

    const loadKline = async () => {
      try {
        const data = await apiGet<KlineRaw[]>('/market/kline', { symbol, period: '1y', kline_type: 'daily', adjust: 'qfq' });
        if (cancelled) return;
        if (Array.isArray(data) && data.length > 0) {
          const candleData: CandlestickData<Time>[] = [];
          const volData: HistogramData<Time>[] = [];

          for (const d of data) {
            const t = msToTime(d.time);
            candleData.push({ time: t, open: d.open, high: d.high, low: d.low, close: d.close });
            const isUp = d.close >= d.open;
            volData.push({
              time: t,
              value: d.volume,
              color: isUp ? 'rgba(255,23,68,0.35)' : 'rgba(0,200,83,0.35)',
            });
          }

          candleSeries.setData(candleData);
          volumeSeries.setData(volData);
          chart.timeScale().fitContent();
        }
      } catch { /* kline not available */ }
    };
    loadKline();

    const onResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', onResize);
    return () => {
      cancelled = true;
      window.removeEventListener('resize', onResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [symbol]);

  return <div ref={containerRef} style={{ width: '100%', height: '480px' }} />;
});

function formatPePb(n: number | undefined | null): string {
  if (n === undefined || n === null || Number.isNaN(n) || !Number.isFinite(n)) return '—';
  return n.toFixed(2);
}

function resolveMarketTag(symbol: string): { label: string; color: string; bg: string } {
  if (/^(sh|sz)\d+$/i.test(symbol) || /^\d{6}$/.test(symbol)) {
    if (symbol.startsWith('688')) return { label: '科创板', color: '#FF9100', bg: 'rgba(255,145,0,0.12)' };
    if (symbol.startsWith('3')) return { label: '创业板', color: '#00C853', bg: 'rgba(0,200,83,0.12)' };
    if (symbol.startsWith('6')) return { label: '沪市', color: '#FF1744', bg: 'rgba(255,23,68,0.12)' };
    return { label: '深市', color: '#0A84FF', bg: 'rgba(10,132,255,0.12)' };
  }
  if (/^\d{5}$/.test(symbol)) return { label: '港股', color: '#0A84FF', bg: 'rgba(10,132,255,0.12)' };
  if (/^[A-Z]+$/.test(symbol)) return { label: '美股', color: '#FF9100', bg: 'rgba(255,145,0,0.12)' };
  return { label: 'A股', color: '#FF1744', bg: 'rgba(255,23,68,0.12)' };
}

type ChartTab = 'kline' | 'moneyflow' | 'chip' | 'news' | 'volatility' | 'rolling-risk' | 'seasonality';

const TAB_ITEMS: Array<{ key: ChartTab; label: string }> = [
  { key: 'kline', label: 'K线图' },
  { key: 'moneyflow', label: '资金流向' },
  { key: 'chip', label: '筹码分布' },
  { key: 'news', label: '资讯' },
  { key: 'volatility', label: '波动率' },
  { key: 'rolling-risk', label: '滚动风险' },
  { key: 'seasonality', label: '季节性' },
];

const GLASS: React.CSSProperties = {
  borderRadius: 'var(--r-md)',
  overflow: 'hidden',
  border: '1px solid var(--separator)',
  background: 'var(--bg-glass)',
  backdropFilter: 'blur(24px) saturate(120%)',
};

export function StockDetailPage() {
  const { symbol } = useParams<{ symbol: string }>();
  const navigate = useNavigate();
  const [quote, setQuote] = useState<StockQuote | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<ChartTab>('kline');

  useEffect(() => {
    if (!symbol) return;
    let cancelled = false;
    setLoading(true);

    apiGet<StockQuote>('/market/quote', { symbol })
      .then(data => {
        if (cancelled) return;
        if (data) {
          setQuote(data);
          return;
        }
        return apiGet<StockQuote[]>('/market/stocks').then(stocks => {
          if (cancelled) return;
          if (Array.isArray(stocks)) {
            const found = stocks.find(s => s.symbol === symbol);
            if (found) {
              setQuote({
                ...found,
                close: found.last_close ?? found.close,
                turnover: found.turnover_rate ?? found.turnover,
              });
              return;
            }
          }
          setQuote(null);
        });
      })
      .catch(() => {
        if (cancelled) return;
        return apiGet<StockQuote[]>('/market/stocks').then(stocks => {
          if (cancelled) return;
          if (Array.isArray(stocks)) {
            const found = stocks.find(s => s.symbol === symbol);
            if (found) {
              setQuote({
                ...found,
                close: found.last_close ?? found.close,
                turnover: found.turnover_rate ?? found.turnover,
              });
              return;
            }
          }
          setQuote(null);
        }).catch(() => { if (!cancelled) setQuote(null); });
      })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [symbol]);

  const handleBack = useCallback(() => {
    navigate(-1);
  }, [navigate]);

  const marketTag = symbol ? resolveMarketTag(symbol) : null;

  if (loading) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#000000' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'rgba(255,255,255,0.20)', letterSpacing: '0.06em' }}>
          LOADING...
        </span>
      </div>
    );
  }

  if (!quote) {
    return (
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 'var(--s4)', background: '#000000' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'rgba(255,255,255,0.20)', letterSpacing: '0.06em' }}>
          STOCK NOT FOUND
        </span>
        <button
          onClick={handleBack}
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: '12px',
            color: '#0A84FF',
            background: 'rgba(10,132,255,0.12)',
            border: '1px solid rgba(10,132,255,0.25)',
            borderRadius: 'var(--r-sm)',
            padding: '6px 16px',
            cursor: 'pointer',
          }}
        >
          返回
        </button>
      </div>
    );
  }

  const isRise = quote.change_pct >= 0;
  const priceClr = isRise ? '#FF1744' : '#00C853';
  const changeBg = isRise ? 'rgba(255,23,68,0.12)' : 'rgba(0,200,83,0.12)';

  const prevClose = quote.last_close ?? quote.close ?? quote.price - quote.change;
  const amplitude = prevClose > 0 ? ((quote.high ?? quote.price) - (quote.low ?? quote.price)) / prevClose * 100 : 0;

  const turnoverDisplay = quote.turnover_rate ?? quote.turnover;
  const metricsLeft = [
    { label: '今开', value: quote.open !== undefined ? formatPrice(quote.open) : '—' },
    { label: '最高', value: quote.high !== undefined ? formatPrice(quote.high) : '—', color: '#FF1744' },
    { label: '成交量', value: formatVolume(quote.volume) },
    { label: '市盈率', value: formatPePb(quote.pe) },
    { label: '换手率', value: turnoverDisplay !== undefined ? `${turnoverDisplay.toFixed(2)}%` : '—' },
  ];

  const metricsRight = [
    { label: '昨收', value: prevClose !== undefined ? formatPrice(prevClose) : '—' },
    { label: '最低', value: quote.low !== undefined ? formatPrice(quote.low) : '—', color: '#00C853' },
    { label: '成交额', value: formatAmount(quote.amount) },
    { label: '市净率', value: formatPePb(quote.pb) },
    { label: '振幅', value: `${amplitude.toFixed(2)}%` },
  ];

  return (
    <div style={{ height: '100%', overflow: 'auto', background: '#000000', padding: 'var(--s6)' }}>
      <div style={{ maxWidth: '1200px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 'var(--s5)' }}>

        <button
          onClick={handleBack}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 'var(--s2)',
            fontFamily: 'var(--font-sans)',
            fontSize: '12px',
            color: 'rgba(255,255,255,0.45)',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            padding: 0,
            width: 'fit-content',
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 18l-6-6 6-6" />
          </svg>
          返回
        </button>

        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 'var(--s6)' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', flex: '0 0 auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s3)' }}>
              <span style={{ fontFamily: 'var(--font-sans)', fontSize: '24px', fontWeight: 700, color: 'rgba(255,255,255,0.95)', lineHeight: 1.2 }}>
                {quote.name}
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: '#0A84FF', fontVariantNumeric: 'tabular-nums' }}>
                {quote.symbol}
              </span>
              {marketTag && (
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '9px',
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                    padding: '2px 8px',
                    borderRadius: 'var(--r-xs)',
                    background: marketTag.bg,
                    color: marketTag.color,
                  }}
                >
                  {marketTag.label}
                </span>
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--s4)' }}>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '42px',
                fontWeight: 700,
                color: priceClr,
                fontVariantNumeric: 'tabular-nums',
                lineHeight: 1,
              }}>
                {formatPrice(quote.price)}
              </span>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '15px',
                color: priceClr,
                fontVariantNumeric: 'tabular-nums',
                fontWeight: 500,
              }}>
                {quote.change >= 0 ? '+' : ''}{formatPrice(quote.change)}
              </span>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '14px',
                color: priceClr,
                fontVariantNumeric: 'tabular-nums',
                fontWeight: 600,
                padding: '3px 10px',
                borderRadius: 'var(--r-xs)',
                background: changeBg,
              }}>
                {isRise ? '+' : ''}{formatPercent(quote.change_pct)}
              </span>
            </div>
          </div>

          <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1px', background: 'rgba(255,255,255,0.06)', borderRadius: 'var(--r-md)', overflow: 'hidden', minWidth: 0 }}>
            {metricsLeft.map((row, i) => (
              <div key={`l${i}`} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', background: '#0a0a0a' }}>
                <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: 'rgba(255,255,255,0.35)' }}>{row.label}</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: row.color ?? 'rgba(255,255,255,0.90)', fontVariantNumeric: 'tabular-nums' }}>{row.value}</span>
              </div>
            ))}
            {metricsRight.map((row, i) => (
              <div key={`r${i}`} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', background: '#0a0a0a' }}>
                <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: 'rgba(255,255,255,0.35)' }}>{row.label}</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: row.color ?? 'rgba(255,255,255,0.90)', fontVariantNumeric: 'tabular-nums' }}>{row.value}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{ ...GLASS }}>
          <div style={{ display: 'flex', borderBottom: '1px solid var(--separator)' }}>
            {TAB_ITEMS.map(tab => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                style={{
                  fontFamily: 'var(--font-sans)',
                  fontSize: '12px',
                  padding: '10px 20px',
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  color: activeTab === tab.key ? 'rgba(255,255,255,0.95)' : 'rgba(255,255,255,0.35)',
                  borderBottom: activeTab === tab.key ? '2px solid #0A84FF' : '2px solid transparent',
                  transition: 'color 0.15s, border-color 0.15s',
                  fontWeight: activeTab === tab.key ? 600 : 400,
                }}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {activeTab === 'kline' && <KlineChart symbol={quote.symbol} />}
          {activeTab === 'moneyflow' && (
            <div style={{ padding: 'var(--s5)' }}>
              <MoneyFlowTab symbol={quote.symbol} />
            </div>
          )}
          {activeTab === 'chip' && (
            <div style={{ padding: 'var(--s5)' }}>
              <ChipDistributionTab symbol={quote.symbol} />
            </div>
          )}
          {activeTab === 'news' && (
            <div style={{ padding: 'var(--s5)' }}>
              <NewsTab symbol={quote.symbol} />
            </div>
          )}
          {activeTab === 'volatility' && (
            <div style={{ padding: 'var(--s5)' }}>
              <VolatilityTab symbol={quote.symbol} />
            </div>
          )}
          {activeTab === 'rolling-risk' && (
            <div style={{ padding: 'var(--s5)' }}>
              <RollingRiskTab symbol={quote.symbol} />
            </div>
          )}
          {activeTab === 'seasonality' && (
            <div style={{ padding: 'var(--s5)' }}>
              <SeasonalityTab symbol={quote.symbol} />
            </div>
          )}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--s5)' }}>
          <div style={{ ...GLASS, padding: 'var(--s5)' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.08em', marginBottom: 'var(--s3)', textTransform: 'uppercase' }}>
              价格区间
            </div>
            <PriceRangeBar high={quote.high ?? quote.price} low={quote.low ?? quote.price} current={quote.price} prevClose={prevClose} />
          </div>

          <div style={{ ...GLASS, padding: 'var(--s5)' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.08em', marginBottom: 'var(--s3)', textTransform: 'uppercase' }}>
              成交概览
            </div>
            <VolumeOverview volume={quote.volume} amount={quote.amount} turnover={quote.turnover} />
          </div>
        </div>

      </div>
    </div>
  );
}

function PriceRangeBar({ high, low, current, prevClose }: { high: number; low: number; current: number; prevClose: number }) {
  const range = high - low;
  const safeRange = range > 0 ? range : 1;
  const currentPct = ((current - low) / safeRange) * 100;
  const prevPct = prevClose > 0 ? ((prevClose - low) / safeRange) * 100 : 50;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#00C853', fontVariantNumeric: 'tabular-nums' }}>{formatPrice(low)}</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'rgba(255,255,255,0.35)', fontVariantNumeric: 'tabular-nums' }}>昨收 {formatPrice(prevClose)}</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: '#FF1744', fontVariantNumeric: 'tabular-nums' }}>{formatPrice(high)}</span>
      </div>
      <div style={{ position: 'relative', height: '8px', background: 'rgba(255,255,255,0.06)', borderRadius: '4px', overflow: 'hidden' }}>
        <div style={{
          position: 'absolute',
          left: `${Math.min(prevPct, currentPct)}%`,
          width: `${Math.abs(currentPct - prevPct)}%`,
          top: 0,
          bottom: 0,
          background: current >= prevClose ? '#FF1744' : '#00C853',
          borderRadius: '4px',
          opacity: 0.6,
        }} />
        <div style={{
          position: 'absolute',
          left: `${prevPct}%`,
          top: '-2px',
          bottom: '-2px',
          width: '2px',
          background: 'rgba(255,255,255,0.35)',
          borderRadius: '1px',
        }} />
        <div style={{
          position: 'absolute',
          left: `${currentPct}%`,
          top: '-3px',
          bottom: '-3px',
          width: '3px',
          background: current >= prevClose ? '#FF1744' : '#00C853',
          borderRadius: '2px',
          boxShadow: current >= prevClose ? '0 0 6px rgba(255,23,68,0.5)' : '0 0 6px rgba(0,200,83,0.5)',
        }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.20)' }}>LOW</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '9px', color: 'rgba(255,255,255,0.20)' }}>HIGH</span>
      </div>
    </div>
  );
}

function VolumeOverview({ volume, amount, turnover }: { volume: number; amount: number; turnover?: number }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: 'rgba(255,255,255,0.35)' }}>成交量</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: 'rgba(255,255,255,0.90)', fontVariantNumeric: 'tabular-nums' }}>
          {formatVolume(volume)}
        </span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: 'rgba(255,255,255,0.35)' }}>成交额</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: 'rgba(255,255,255,0.90)', fontVariantNumeric: 'tabular-nums' }}>
          {formatAmount(amount)}
        </span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: '11px', color: 'rgba(255,255,255,0.35)' }}>换手率</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600, color: turnover !== undefined && turnover > 5 ? '#FF9100' : 'rgba(255,255,255,0.90)', fontVariantNumeric: 'tabular-nums' }}>
          {turnover !== undefined ? `${turnover.toFixed(2)}%` : '—'}
        </span>
      </div>
    </div>
  );
}
