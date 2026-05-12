import { useState, useCallback, useMemo, useEffect, useRef, memo } from 'react';
import { useNavigate } from 'react-router-dom';
import { createChart, CandlestickSeries, type IChartApi, type ISeriesApi, type CandlestickData, type Time } from 'lightweight-charts';
import { useMarketStocks, useMarketSectors } from '@/hooks/queries/useMarketQueries';
import { useWatchlist, useAddToWatchlist, useRemoveFromWatchlist } from '@/hooks/queries/useWatchlistQueries';
import { VirtualList } from '@/components/ui/VirtualList';
import { EmptyState } from '@/components/ui/EmptyState';
import { apiGet } from '@/api/client';
import { formatPrice, formatPercent, formatVolume, formatAmount, priceColor } from '@/utils/format';
import type { StockQuote } from '@/types';

type SortKey = 'symbol' | 'name' | 'price' | 'change_pct' | 'volume' | 'amount' | 'pe' | 'pb';
type SortDir = 'asc' | 'desc';
type MarketTab = 'all' | 'sh' | 'sz' | 'cy' | 'kc';
type ContentTab = 'market' | 'moneyflow' | 'sector' | 'screener';

const RISE_HEX = '#FF1744';
const FALL_HEX = '#00C853';
const ACCENT_HEX = '#0A84FF';

interface MoneyFlowStock {
  symbol: string;
  name: string;
  main_net_inflow: number;
  main_inflow: number;
  main_outflow: number;
  change_pct: number;
}

type MoneyFlowSortKey = 'symbol' | 'name' | 'main_net_inflow' | 'main_inflow' | 'main_outflow' | 'change_pct';

interface SectorRotationItem {
  name: string;
  change_pct: number;
  momentum_score: number;
}

interface SectorStrengthItem {
  code: string;
  name: string;
  change_pct: number;
  amount: number;
  turnover_rate: number;
  main_net_inflow: number;
  up_count: number;
  down_count: number;
  leading_stock: string;
  leading_change: number;
  momentum_score: number;
  rank: number;
}

interface SectorMoneyFlow {
  name: string;
  change_pct: number;
  main_net_inflow: number;
  main_inflow: number;
  main_outflow: number;
  code: string;
}

interface ScreenerPreset {
  id: string;
  name: string;
  description: string;
  category: string;
  conditions: Array<{
    field: string;
    operator: string;
    value: number | string;
    label: string;
  }>;
}

interface ScreenerResult {
  total: number;
  stocks: Array<{
    symbol: string;
    name: string;
    price: number;
    change_pct: number;
    [key: string]: unknown;
  }>;
}

const TABS: Array<{ key: MarketTab; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'sh', label: '沪市' },
  { key: 'sz', label: '深市' },
  { key: 'cy', label: '创业板' },
  { key: 'kc', label: '科创板' },
];

const CONTENT_TABS: Array<{ key: ContentTab; label: string }> = [
  { key: 'market', label: '行情' },
  { key: 'moneyflow', label: '资金流向' },
  { key: 'sector', label: '板块轮动' },
  { key: 'screener', label: '条件选股' },
];

const MF_COLS: Array<{ label: string; key: MoneyFlowSortKey; width: string; align: 'left' | 'right' }> = [
  { label: '代码', key: 'symbol', width: '90px', align: 'left' },
  { label: '名称', key: 'name', width: '1fr', align: 'left' },
  { label: '主力净流入', key: 'main_net_inflow', width: '120px', align: 'right' },
  { label: '主力流入', key: 'main_inflow', width: '120px', align: 'right' },
  { label: '主力流出', key: 'main_outflow', width: '120px', align: 'right' },
  { label: '涨跌幅', key: 'change_pct', width: '90px', align: 'right' },
];

const SR_COLS: Array<{ label: string; key: string; width: string; align: 'left' | 'right' }> = [
  { label: '板块', key: 'name', width: '1fr', align: 'left' },
  { label: '涨跌幅', key: 'change_pct', width: '120px', align: 'right' },
  { label: '动量分数', key: 'momentum_score', width: '140px', align: 'right' },
];

const CHANGE_RANGES = [
  { label: '全部', min: -Infinity, max: Infinity },
  { label: '涨幅>5%', min: 5, max: Infinity },
  { label: '涨幅2-5%', min: 2, max: 5 },
  { label: '跌幅2-5%', min: -5, max: -2 },
  { label: '跌幅>5%', min: -Infinity, max: -5 },
];

const COL_DEFS: Array<{ label: string; key: SortKey; width: string; align: 'left' | 'right' | 'center' }> = [
  { label: 'CODE', key: 'symbol', width: '80px', align: 'left' },
  { label: 'NAME', key: 'name', width: '1fr', align: 'left' },
  { label: 'PRICE', key: 'price', width: '90px', align: 'right' },
  { label: 'CHANGE', key: 'change_pct', width: '90px', align: 'right' },
  { label: 'VOLUME', key: 'volume', width: '90px', align: 'right' },
  { label: 'AMOUNT', key: 'amount', width: '100px', align: 'right' },
  { label: 'PE', key: 'pe', width: '64px', align: 'right' },
  { label: 'PB', key: 'pb', width: '64px', align: 'right' },
];

function filterByMarket(stocks: StockQuote[], tab: MarketTab): StockQuote[] {
  if (tab === 'all') return stocks;
  if (tab === 'sh') return stocks.filter(s => s.symbol.startsWith('6'));
  if (tab === 'sz') return stocks.filter(s => s.symbol.startsWith('0') || s.symbol.startsWith('3'));
  if (tab === 'cy') return stocks.filter(s => s.symbol.startsWith('3'));
  if (tab === 'kc') return stocks.filter(s => s.symbol.startsWith('688'));
  return stocks;
}

function formatPePb(n: number | undefined): string {
  if (n === undefined || n === null || Number.isNaN(n) || !Number.isFinite(n)) return '—';
  return n.toFixed(1);
}

function changeColor(val: number): string {
  if (val > 0) return RISE_HEX;
  if (val < 0) return FALL_HEX;
  return 'rgba(255,255,255,0.45)';
}

const TickFlashCell = memo(function TickFlashCell({ value, changePct }: { value: number; changePct: number }) {
  const [flash, setFlash] = useState<'up' | 'down' | null>(null);
  const prev = useRef(value);
  useEffect(() => {
    if (value !== prev.current) {
      setFlash(value > prev.current ? 'up' : 'down');
      prev.current = value;
      const timer = setTimeout(() => setFlash(null), 500);
      return () => clearTimeout(timer);
    }
  }, [value]);
  return (
    <span style={{
      color: changePct >= 0 ? 'var(--num-positive)' : 'var(--num-negative)',
      background: flash === 'up' ? 'rgba(255,59,92,0.15)' :
                  flash === 'down' ? 'rgba(0,217,160,0.15)' : 'transparent',
      transition: 'background 500ms ease-out',
      fontVariantNumeric: 'tabular-nums',
      fontFamily: 'var(--font-mono)',
    }}>
      {formatPrice(value)}
    </span>
  );
});

const LimitBadge = memo(function LimitBadge({ changePct }: { changePct: number }) {
  if (changePct >= 9.9) {
    return (
      <span style={{
        fontFamily: 'var(--font-mono)',
        fontSize: '9px',
        fontWeight: 600,
        padding: '1px 4px',
        borderRadius: '2px',
        background: 'rgba(255,23,68,0.2)',
        color: '#FF1744',
        marginLeft: 4,
        flexShrink: 0,
      }}>
        ↑停
      </span>
    );
  }
  if (changePct <= -9.9) {
    return (
      <span style={{
        fontFamily: 'var(--font-mono)',
        fontSize: '9px',
        fontWeight: 600,
        padding: '1px 4px',
        borderRadius: '2px',
        background: 'rgba(0,200,83,0.2)',
        color: '#00C853',
        marginLeft: 4,
        flexShrink: 0,
      }}>
        ↓停
      </span>
    );
  }
  return null;
});

const KlineChart = memo(function KlineChart({ symbol }: { symbol: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    let cancelled = false;
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 200,
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
      timeScale: { borderColor: 'rgba(255,255,255,0.06)', timeVisible: true },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#FF1744',
      downColor: '#00C853',
      borderUpColor: '#FF1744',
      borderDownColor: '#00C853',
      wickUpColor: '#FF1744',
      wickDownColor: '#00C853',
    });
    chartRef.current = chart;
    seriesRef.current = series;

    const loadKline = async () => {
      try {
        const data = await apiGet<Array<{
          time: number;
          open: number;
          high: number;
          low: number;
          close: number;
          volume?: number;
        }>>(`/market/kline`, { symbol, period: 'daily', count: 120 });
        if (cancelled) return;
        if (Array.isArray(data) && data.length > 0) {
          const candleData: CandlestickData<Time>[] = data.map(d => {
            const dt = new Date(d.time);
            const yyyy = dt.getFullYear();
            const mm = String(dt.getMonth() + 1).padStart(2, '0');
            const dd = String(dt.getDate()).padStart(2, '0');
            return {
              time: `${yyyy}-${mm}-${dd}` as Time,
              open: d.open,
              high: d.high,
              low: d.low,
              close: d.close,
            };
          });
          series.setData(candleData);
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
      seriesRef.current = null;
    };
  }, [symbol]);

  return <div ref={containerRef} style={{ width: '100%', height: '200px' }} />;
});

const SkeletonRow = memo(function SkeletonRow({ style }: { style: React.CSSProperties }) {
  return (
    <div style={{ ...style, display: 'flex', alignItems: 'center', gap: 'var(--s3)', padding: '0 var(--s4)' }}>
      {Array.from({ length: 8 }, (_, i) => (
        <div key={i} style={{
          width: i === 1 ? '60px' : '48px',
          height: '10px',
          borderRadius: 'var(--r-xs)',
          background: 'var(--separator)',
          animation: 'market-pulse 1.2s ease-in-out infinite',
          animationDelay: `${i * 80}ms`,
        }} />
      ))}
    </div>
  );
});

const LoadingState = memo(function LoadingState() {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      height: '100%',
      gap: 'var(--s4)',
    }}>
      <span style={{
        fontFamily: 'var(--font-sans)',
        fontSize: '48px',
        fontWeight: 300,
        color: 'var(--accent)',
        lineHeight: 1,
      }}>
        Q
      </span>
      <div style={{ width: '200px' }}>
        {Array.from({ length: 5 }, (_, i) => (
          <SkeletonRow key={i} style={{ height: '40px', position: 'relative' }} />
        ))}
      </div>
    </div>
  );
});



const MoneyFlowTab = memo(function MoneyFlowTab() {
  const [stocks, setStocks] = useState<MoneyFlowStock[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [sortKey, setSortKey] = useState<MoneyFlowSortKey>('main_net_inflow');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    apiGet<MoneyFlowStock[]>('/moneyflow/ranking')
      .then(data => {
        if (cancelled) return;
        setStocks(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setError(true);
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  const handleSort = useCallback((key: MoneyFlowSortKey) => {
    setSortKey(prev => {
      if (prev === key) {
        setSortDir(d => d === 'asc' ? 'desc' : 'asc');
      } else {
        setSortDir('desc');
      }
      return key;
    });
  }, []);

  const sorted = useMemo(() => {
    return [...stocks].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === 'string' && typeof bv === 'string') {
        return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      return sortDir === 'asc' ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
  }, [stocks, sortKey, sortDir]);

  if (loading) return <LoadingState />;
  if (error || sorted.length === 0) return <EmptyState title="暂无资金流向数据" description="请检查网络连接或稍后重试" size="md" />;

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        height: '32px',
        flexShrink: 0,
        background: '#111111',
        borderBottom: '1px solid rgba(255,255,255,0.08)',
      }}>
        {MF_COLS.map(col => (
          <span
            key={col.key}
            onClick={() => handleSort(col.key)}
            style={{
              width: col.width,
              flexShrink: 0,
              padding: '0 12px',
              fontFamily: 'var(--font-mono)',
              fontSize: '9px',
              textTransform: 'uppercase',
              letterSpacing: '0.1em',
              color: sortKey === col.key ? 'rgba(255,255,255,0.7)' : 'rgba(255,255,255,0.25)',
              textAlign: col.align,
              cursor: 'pointer',
              userSelect: 'none',
              whiteSpace: 'nowrap',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: col.align === 'right' ? 'flex-end' : 'flex-start',
              boxSizing: 'border-box',
            }}
          >
            {col.label}{sortKey === col.key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
          </span>
        ))}
      </div>
      <div style={{ flex: 1, overflow: 'auto' }}>
        {sorted.map(stock => (
          <div
            key={stock.symbol}
            style={{
              display: 'flex',
              alignItems: 'center',
              height: '40px',
              borderBottom: '1px solid rgba(255,255,255,0.04)',
              transition: 'background 0.15s ease',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = 'rgba(10,132,255,0.06)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
          >
            <span style={{ width: '90px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: ACCENT_HEX, fontVariantNumeric: 'tabular-nums' }}>
              {stock.symbol}
            </span>
            <span style={{ flex: 1, minWidth: 0, padding: '0 12px', fontFamily: 'var(--font-sans)', fontSize: '13px', fontWeight: 500, color: 'rgba(255,255,255,0.85)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {stock.name}
            </span>
            <span style={{ width: '120px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '12px', color: changeColor(stock.main_net_inflow), fontVariantNumeric: 'tabular-nums', textAlign: 'right', fontWeight: 500, boxSizing: 'border-box' }}>
              {formatAmount(stock.main_net_inflow)}
            </span>
            <span style={{ width: '120px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'rgba(255,255,255,0.55)', fontVariantNumeric: 'tabular-nums', textAlign: 'right', boxSizing: 'border-box' }}>
              {formatAmount(stock.main_inflow)}
            </span>
            <span style={{ width: '120px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'rgba(255,255,255,0.55)', fontVariantNumeric: 'tabular-nums', textAlign: 'right', boxSizing: 'border-box' }}>
              {formatAmount(stock.main_outflow)}
            </span>
            <span style={{ width: '90px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '12px', color: changeColor(stock.change_pct), fontVariantNumeric: 'tabular-nums', textAlign: 'right', fontWeight: 500, boxSizing: 'border-box' }}>
              {formatPercent(stock.change_pct)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
});

const SectorRotationTab = memo(function SectorRotationTab() {
  const [rotation, setRotation] = useState<SectorRotationItem[]>([]);
  const [strength, setStrength] = useState<SectorStrengthItem[]>([]);
  const [moneyFlow, setMoneyFlow] = useState<SectorMoneyFlow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);

    Promise.all([
      apiGet<{
        snapshot: {
          top_sectors: Array<{ name: string; change_pct: number; momentum_score: number }>;
          bottom_sectors: Array<{ name: string; change_pct: number; momentum_score: number }>;
        };
        trend: unknown[];
        signals: unknown[];
      }>('/sector/rotation'),
      apiGet<SectorStrengthItem[]>('/sector/strength'),
      apiGet<SectorMoneyFlow[]>('/moneyflow/sector'),
    ])
      .then(([rotData, strData, mfData]) => {
        if (cancelled) return;
        const top = rotData.snapshot?.top_sectors ?? [];
        const bottom = rotData.snapshot?.bottom_sectors ?? [];
        setRotation([...top, ...bottom]);
        setStrength(Array.isArray(strData) ? strData : []);
        setMoneyFlow(Array.isArray(mfData) ? mfData : []);
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setError(true);
        setLoading(false);
      });

    return () => { cancelled = true; };
  }, []);

  if (loading) return <LoadingState />;
  if (error || (rotation.length === 0 && strength.length === 0 && moneyFlow.length === 0)) return <EmptyState title="暂无行情数据" description="请检查网络连接或稍后重试" size="lg" />;

  const sortedMoneyFlow = useMemo(() => {
    return [...moneyFlow].sort((a, b) => b.main_net_inflow - a.main_net_inflow);
  }, [moneyFlow]);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'auto' }}>
      {strength.length > 0 && (
        <div style={{ padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '9px',
            color: 'rgba(255,255,255,0.35)',
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            marginBottom: '12px',
          }}>
            板块强度排行
          </div>
          <div style={{ display: 'flex', gap: '10px', overflowX: 'auto', paddingBottom: '4px' }}>
            {strength
              .sort((a, b) => b.momentum_score - a.momentum_score)
              .map(item => {
                const trend: 'up' | 'down' = item.change_pct >= 0 ? 'up' : 'down';
                return (
                <div
                  key={item.name}
                  style={{
                    flexShrink: 0,
                    width: '140px',
                    padding: '12px',
                    background: '#111111',
                    borderRadius: '8px',
                    border: '1px solid rgba(255,255,255,0.06)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '8px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ fontFamily: 'var(--font-sans)', fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.85)' }}>
                      {item.name}
                    </span>
                    <span style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '11px',
                      color: trend === 'up' ? RISE_HEX : FALL_HEX,
                    }}>
                      {trend === 'up' ? '↑' : '↓'}
                    </span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <div style={{
                      flex: 1,
                      height: '4px',
                      background: 'rgba(255,255,255,0.06)',
                      borderRadius: '2px',
                      overflow: 'hidden',
                    }}>
                      <div style={{
                        width: `${Math.min(Math.max(item.momentum_score, 0), 100)}%`,
                        height: '100%',
                        background: item.momentum_score >= 70 ? RISE_HEX : item.momentum_score >= 40 ? ACCENT_HEX : FALL_HEX,
                        borderRadius: '2px',
                      }} />
                    </div>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'rgba(255,255,255,0.6)', fontVariantNumeric: 'tabular-nums', minWidth: '24px', textAlign: 'right' }}>
                      {item.momentum_score}
                    </span>
                  </div>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: ACCENT_HEX, fontVariantNumeric: 'tabular-nums' }}>
                    {item.leading_stock}
                  </span>
                </div>
              );})
              }
          </div>
        </div>
      )}

      {moneyFlow.length > 0 && (
        <div style={{ padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '9px',
            color: 'rgba(255,255,255,0.35)',
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            marginBottom: '12px',
          }}>
            板块资金流
          </div>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            height: '32px',
            flexShrink: 0,
            background: '#111111',
            borderBottom: '1px solid rgba(255,255,255,0.08)',
          }}>
            <span style={{ width: '100px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'rgba(255,255,255,0.25)', whiteSpace: 'nowrap' }}>板块名称</span>
            <span style={{ width: '100px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'rgba(255,255,255,0.25)', textAlign: 'right', whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'center', justifyContent: 'flex-end', boxSizing: 'border-box' }}>涨跌幅</span>
            <span style={{ width: '130px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'rgba(255,255,255,0.25)', textAlign: 'right', whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'center', justifyContent: 'flex-end', boxSizing: 'border-box' }}>主力净流入</span>
            <span style={{ width: '130px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'rgba(255,255,255,0.25)', textAlign: 'right', whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'center', justifyContent: 'flex-end', boxSizing: 'border-box' }}>主力流入</span>
            <span style={{ flex: 1, minWidth: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'rgba(255,255,255,0.25)', textAlign: 'right', whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'center', justifyContent: 'flex-end', boxSizing: 'border-box' }}>主力流出</span>
          </div>
          {sortedMoneyFlow.map(sector => (
            <div
              key={sector.code}
              style={{
                display: 'flex',
                alignItems: 'center',
                height: '40px',
                borderBottom: '1px solid rgba(255,255,255,0.04)',
                transition: 'background 0.15s ease',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = 'rgba(10,132,255,0.06)'; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
            >
              <span style={{ width: '100px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-sans)', fontSize: '13px', fontWeight: 500, color: 'rgba(255,255,255,0.85)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {sector.name}
              </span>
              <span style={{ width: '100px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '12px', color: changeColor(sector.change_pct), fontVariantNumeric: 'tabular-nums', textAlign: 'right', fontWeight: 500, boxSizing: 'border-box' }}>
                {formatPercent(sector.change_pct)}
              </span>
              <span style={{ width: '130px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '12px', color: sector.main_net_inflow >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums', textAlign: 'right', fontWeight: 500, boxSizing: 'border-box' }}>
                {formatAmount(sector.main_net_inflow)}
              </span>
              <span style={{ width: '130px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'rgba(255,255,255,0.55)', fontVariantNumeric: 'tabular-nums', textAlign: 'right', boxSizing: 'border-box' }}>
                {formatAmount(sector.main_inflow)}
              </span>
              <span style={{ flex: 1, minWidth: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'rgba(255,255,255,0.55)', fontVariantNumeric: 'tabular-nums', textAlign: 'right', boxSizing: 'border-box' }}>
                {formatAmount(sector.main_outflow)}
              </span>
            </div>
          ))}
        </div>
      )}

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          height: '32px',
          flexShrink: 0,
          background: '#111111',
          borderBottom: '1px solid rgba(255,255,255,0.08)',
        }}>
          {SR_COLS.map(col => (
            <span
              key={col.key}
              style={{
                width: col.width,
                flexShrink: 0,
                padding: '0 12px',
                fontFamily: 'var(--font-mono)',
                fontSize: '9px',
                textTransform: 'uppercase',
                letterSpacing: '0.1em',
                color: 'rgba(255,255,255,0.25)',
                textAlign: col.align,
                whiteSpace: 'nowrap',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: col.align === 'right' ? 'flex-end' : 'flex-start',
                boxSizing: 'border-box',
              }}
            >
              {col.label}
            </span>
          ))}
        </div>
        <div style={{ flex: 1, overflow: 'auto' }}>
          {rotation.map(sector => (
            <div
                key={sector.name}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  height: '40px',
                  borderBottom: '1px solid rgba(255,255,255,0.04)',
                  transition: 'background 0.15s ease',
                }}
                onMouseEnter={e => { e.currentTarget.style.background = 'rgba(10,132,255,0.06)'; }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
              >
                <span style={{ flex: 1, minWidth: 0, padding: '0 12px', fontFamily: 'var(--font-sans)', fontSize: '13px', fontWeight: 500, color: 'rgba(255,255,255,0.85)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {sector.name}
                </span>
                <span style={{ width: '120px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '12px', color: changeColor(sector.change_pct), fontVariantNumeric: 'tabular-nums', textAlign: 'right', fontWeight: 500, boxSizing: 'border-box' }}>
                  {formatPercent(sector.change_pct)}
                </span>
                <span style={{ width: '140px', flexShrink: 0, padding: '0 12px', display: 'flex', alignItems: 'center', gap: '8px', boxSizing: 'border-box' }}>
                  <div style={{
                    flex: 1,
                    height: '4px',
                    background: 'rgba(255,255,255,0.06)',
                    borderRadius: '2px',
                    overflow: 'hidden',
                  }}>
                    <div style={{
                      width: `${Math.min(Math.max(sector.momentum_score, 0), 100)}%`,
                      height: '100%',
                      background: sector.momentum_score >= 70 ? RISE_HEX : sector.momentum_score >= 40 ? ACCENT_HEX : FALL_HEX,
                      borderRadius: '2px',
                    }} />
                  </div>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'rgba(255,255,255,0.5)', fontVariantNumeric: 'tabular-nums', minWidth: '28px', textAlign: 'right' }}>
                    {sector.momentum_score.toFixed(0)}
                  </span>
                </span>
              </div>
            ))}
          </div>
      </div>
    </div>
  );
});

const CATEGORY_LABELS: Record<string, string> = {
  technical: '技术面',
  fundamental: '基本面',
  quant: '量化',
};

const SCREENER_COLS: Array<{ label: string; key: string; width: string; align: 'left' | 'right' }> = [
  { label: '代码', key: 'symbol', width: '90px', align: 'left' },
  { label: '名称', key: 'name', width: '1fr', align: 'left' },
  { label: '价格', key: 'price', width: '100px', align: 'right' },
  { label: '涨跌幅', key: 'change_pct', width: '100px', align: 'right' },
];

const ScreenerTab = memo(function ScreenerTab() {
  const navigate = useNavigate();
  const [presets, setPresets] = useState<ScreenerPreset[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [result, setResult] = useState<ScreenerResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    apiGet<ScreenerPreset[]>('/screener/presets')
      .then(data => {
        if (cancelled) return;
        setPresets(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setError(true);
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setResult(null);
      return;
    }
    let cancelled = false;
    setRunning(true);
    setResult(null);
    apiGet<ScreenerResult>('/screener/run', { preset: selectedId })
      .then(data => {
        if (cancelled) return;
        setResult(data);
        setRunning(false);
      })
      .catch(() => {
        if (cancelled) return;
        setResult(null);
        setRunning(false);
      });
    return () => { cancelled = true; };
  }, [selectedId]);

  const grouped = useMemo(() => {
    const groups: Record<string, ScreenerPreset[]> = {};
    for (const preset of presets) {
      const cat = preset.category || 'other';
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(preset);
    }
    return groups;
  }, [presets]);

  if (loading) return <LoadingState />;
  if (error || presets.length === 0) return <EmptyState title="暂无选股条件" description="请检查网络连接或稍后重试" size="md" />;

  return (
    <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
      <div style={{
        width: '280px',
        flexShrink: 0,
        borderRight: '1px solid rgba(255,255,255,0.08)',
        overflow: 'auto',
        padding: '12px',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
      }}>
        {Object.entries(grouped).map(([category, items]) => (
          <div key={category}>
            <div style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '9px',
              color: 'rgba(255,255,255,0.35)',
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              marginBottom: '8px',
              paddingLeft: '4px',
            }}>
              {CATEGORY_LABELS[category] ?? category}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {items.map(preset => (
                <div
                  key={preset.id}
                  onClick={() => setSelectedId(prev => prev === preset.id ? null : preset.id)}
                  style={{
                    padding: '10px 12px',
                    background: selectedId === preset.id ? 'rgba(10,132,255,0.12)' : '#111111',
                    borderRadius: '8px',
                    border: `1px solid ${selectedId === preset.id ? 'rgba(10,132,255,0.3)' : 'rgba(255,255,255,0.06)'}`,
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                  onMouseEnter={e => {
                    if (selectedId !== preset.id) {
                      e.currentTarget.style.background = 'rgba(255,255,255,0.04)';
                    }
                  }}
                  onMouseLeave={e => {
                    if (selectedId !== preset.id) {
                      e.currentTarget.style.background = '#111111';
                    }
                  }}
                >
                  <div style={{
                    fontFamily: 'var(--font-sans)',
                    fontSize: '13px',
                    fontWeight: 600,
                    color: selectedId === preset.id ? ACCENT_HEX : 'rgba(255,255,255,0.85)',
                    marginBottom: '4px',
                  }}>
                    {preset.name}
                  </div>
                  <div style={{
                    fontFamily: 'var(--font-sans)',
                    fontSize: '11px',
                    color: 'rgba(255,255,255,0.4)',
                    marginBottom: '8px',
                    lineHeight: 1.4,
                  }}>
                    {preset.description}
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                    {preset.conditions.map((cond, idx) => (
                      <span
                        key={idx}
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: '9px',
                          color: 'rgba(255,255,255,0.55)',
                          background: 'rgba(255,255,255,0.06)',
                          borderRadius: '4px',
                          padding: '2px 6px',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {cond.label}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        {running && <LoadingState />}
        {!running && result && (
          <>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              height: '32px',
              padding: '0 16px',
              flexShrink: 0,
              borderBottom: '1px solid rgba(255,255,255,0.08)',
            }}>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '10px',
                color: 'rgba(255,255,255,0.35)',
                letterSpacing: '0.06em',
              }}>
                {result.total} 只股票
              </span>
            </div>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              height: '32px',
              flexShrink: 0,
              background: '#111111',
              borderBottom: '1px solid rgba(255,255,255,0.08)',
            }}>
              {SCREENER_COLS.map(col => (
                <span
                  key={col.key}
                  style={{
                    width: col.width,
                    flexShrink: 0,
                    padding: '0 12px',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '9px',
                    textTransform: 'uppercase',
                    letterSpacing: '0.1em',
                    color: 'rgba(255,255,255,0.25)',
                    textAlign: col.align,
                    whiteSpace: 'nowrap',
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: col.align === 'right' ? 'flex-end' : 'flex-start',
                    boxSizing: 'border-box',
                  }}
                >
                  {col.label}
                </span>
              ))}
            </div>
            <div style={{ flex: 1, overflow: 'auto' }}>
              {result.stocks.map(stock => (
                <div
                  key={stock.symbol}
                  onClick={() => navigate(`/stock/${stock.symbol}`)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    height: '40px',
                    borderBottom: '1px solid rgba(255,255,255,0.04)',
                    cursor: 'pointer',
                    transition: 'background 0.15s ease',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = 'rgba(10,132,255,0.06)'; }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                >
                  <span style={{ width: '90px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: ACCENT_HEX, fontVariantNumeric: 'tabular-nums' }}>
                    {stock.symbol}
                  </span>
                  <span style={{ flex: 1, minWidth: 0, padding: '0 12px', fontFamily: 'var(--font-sans)', fontSize: '13px', fontWeight: 500, color: 'rgba(255,255,255,0.85)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {stock.name}
                  </span>
                  <span style={{ width: '100px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '12px', color: changeColor(stock.change_pct), fontVariantNumeric: 'tabular-nums', textAlign: 'right', fontWeight: 500, boxSizing: 'border-box' }}>
                    {formatPrice(stock.price)}
                  </span>
                  <span style={{ width: '100px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '12px', color: changeColor(stock.change_pct), fontVariantNumeric: 'tabular-nums', textAlign: 'right', fontWeight: 500, boxSizing: 'border-box' }}>
                    {formatPercent(stock.change_pct)}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
        {!running && !result && selectedId === null && (
          <EmptyState title="请选择选股条件" description="从左侧列表中选择一个条件开始筛选" size="md" />
        )}
        {!running && !result && selectedId !== null && (
          <EmptyState title="暂无选股结果" description="该条件下未筛选到符合条件的股票" size="md" />
        )}
      </div>
    </div>
  );
});

const DrawerBackdrop = memo(function DrawerBackdrop({
  children,
  onClose,
}: {
  children: React.ReactNode;
  onClose: () => void;
}) {
  const handleBackdrop = useCallback((e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onClose();
  }, [onClose]);

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        zIndex: 10,
        background: 'rgba(0,0,0,0.4)',
        backdropFilter: 'blur(4px)',
        animation: 'fade-in var(--dur-fast) var(--ease-apple)',
      }}
      onClick={handleBackdrop}
    >
      {children}
    </div>
  );
});

const StockDrawer = memo(function StockDrawer({
  stock,
  onClose,
  isWatched,
  onToggleWatch,
}: {
  stock: StockQuote;
  onClose: () => void;
  isWatched: boolean;
  onToggleWatch: (e: React.MouseEvent) => void;
}) {
  const navigate = useNavigate();
  return (
    <div
      style={{
        position: 'absolute',
        right: 0,
        top: 0,
        bottom: 0,
        width: '320px',
        background: 'var(--bg-glass)',
        backdropFilter: 'blur(24px) saturate(120%)',
        borderLeft: '1px solid var(--separator)',
        boxShadow: 'var(--shadow-lg)',
        display: 'flex',
        flexDirection: 'column',
        animation: 'slide-in-right var(--dur-base) var(--ease-spring)',
      }}
      onClick={e => e.stopPropagation()}
    >
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: 'var(--s4) var(--s5)',
        borderBottom: '1px solid var(--separator)',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: '16px', fontWeight: 600, color: 'var(--label-primary)', lineHeight: 1.2 }}>{stock.name}</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--accent)', fontVariantNumeric: 'tabular-nums' }}>{stock.symbol}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s2)' }}>
          <button
            onClick={() => navigate(`/stock/${stock.symbol}`)}
            style={{
              background: 'none',
              border: '1px solid var(--separator)',
              borderRadius: 'var(--r-sm)',
              color: 'var(--accent)',
              fontSize: '11px',
              fontFamily: 'var(--font-mono)',
              cursor: 'pointer',
              height: '28px',
              padding: '0 10px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: `all var(--dur-fast) var(--ease-apple)`,
            }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent)'; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--separator)'; }}
          >
            详情
          </button>
          <button
            onClick={onToggleWatch}
            style={{
              background: 'none',
              border: '1px solid var(--separator)',
              borderRadius: 'var(--r-sm)',
              color: isWatched ? 'var(--signal-warn)' : 'var(--label-tertiary)',
              fontSize: '14px',
              cursor: 'pointer',
              width: '28px',
              height: '28px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: `all var(--dur-fast) var(--ease-apple)`,
            }}
          >
            {isWatched ? '★' : '☆'}
          </button>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: '1px solid var(--separator)',
              borderRadius: 'var(--r-sm)',
              color: 'var(--label-tertiary)',
              fontSize: '14px',
              cursor: 'pointer',
              width: '28px',
              height: '28px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: `all var(--dur-fast) var(--ease-apple)`,
            }}
            onMouseEnter={e => { e.currentTarget.style.color = 'var(--label-primary)'; e.currentTarget.style.borderColor = 'var(--separator-hi)'; }}
            onMouseLeave={e => { e.currentTarget.style.color = 'var(--label-tertiary)'; e.currentTarget.style.borderColor = 'var(--separator)'; }}
          >
            ✕
          </button>
        </div>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: 'var(--s5)' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--s3)', marginBottom: 'var(--s4)' }}>
          <span style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '28px',
            fontWeight: 600,
            color: priceColor(stock.change_pct),
            fontVariantNumeric: 'tabular-nums',
            lineHeight: 1,
          }}>
            {formatPrice(stock.price)}
          </span>
          <span style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '14px',
            color: priceColor(stock.change_pct),
            fontVariantNumeric: 'tabular-nums',
            fontWeight: 500,
            padding: '2px 8px',
            borderRadius: 'var(--r-xs)',
            background: stock.change_pct >= 0 ? 'var(--rise-bg)' : 'var(--fall-bg)',
          }}>
            {formatPercent(stock.change_pct)}
          </span>
        </div>

        <div style={{
          marginBottom: 'var(--s4)',
          borderRadius: 'var(--r-md)',
          overflow: 'hidden',
          border: '1px solid var(--separator)',
          background: 'var(--bg-elevated)',
        }}>
          <KlineChart symbol={stock.symbol} />
        </div>

        <div style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '9px',
          color: 'var(--label-tertiary)',
          letterSpacing: '0.08em',
          marginBottom: 'var(--s2)',
          textTransform: 'uppercase',
        }}>
          基本面
        </div>
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '1px',
          background: 'var(--separator)',
          borderRadius: 'var(--r-md)',
          overflow: 'hidden',
        }}>
          {([
            { label: '成交量', value: formatVolume(stock.volume) },
            { label: '成交额', value: formatAmount(stock.amount) },
            { label: '市盈率', value: formatPePb(stock.pe) },
            { label: '市净率', value: formatPePb(stock.pb) },
            { label: '今开', value: stock.open !== undefined ? formatPrice(stock.open) : '—' },
            { label: '最高', value: stock.high !== undefined ? formatPrice(stock.high) : '—' },
            { label: '最低', value: stock.low !== undefined ? formatPrice(stock.low) : '—' },
            { label: '昨收', value: stock.close !== undefined ? formatPrice(stock.close) : '—' },
          ]).map(row => (
            <div key={row.label} style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '10px var(--s3)',
              background: 'var(--bg-elevated)',
            }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--label-tertiary)', letterSpacing: '0.04em' }}>{row.label}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--label-primary)', fontVariantNumeric: 'tabular-nums' }}>{row.value}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
});

export function MarketPage() {
  const { data: stocks = [], isLoading: loading } = useMarketStocks('A');
  const { data: sectorsData = {} } = useMarketSectors();
  const { data: watchlistData } = useWatchlist();
  const addMutation = useAddToWatchlist();
  const removeMutation = useRemoveFromWatchlist();
  const navigate = useNavigate();

  const watchlist = watchlistData?.symbols ?? [];
  const toggleWatch = (symbol: string) => {
    if (watchlist.includes(symbol)) {
      removeMutation.mutate(symbol);
    } else {
      addMutation.mutate(symbol);
    }
  };

  const sectors = useMemo(() => {
    return Object.entries(sectorsData).map(([key, val]) => ({
      name: (val as { name?: string })?.name ?? key,
      change_pct: (val as { change_pct?: number })?.change_pct ?? 0,
      stocks: (val as { stocks?: string[] })?.stocks ?? [],
    }));
  }, [sectorsData]);

  const [sortKey, setSortKey] = useState<SortKey>('symbol');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [filter, setFilter] = useState('');
  const [activeTab, setActiveTab] = useState<MarketTab>('all');
  const [selectedStock, setSelectedStock] = useState<StockQuote | null>(null);
  const [changeRangeIdx, setChangeRangeIdx] = useState(0);
  const [sectorFilter, setSectorFilter] = useState('');
  const [showSectorDropdown, setShowSectorDropdown] = useState(false);
  const [contentTab, setContentTab] = useState<ContentTab>('market');
  const [focusedIdx, setFocusedIdx] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const sectorNames = useMemo(() => {
    const names = new Set(sectors.map(s => s.name));
    return Array.from(names).sort();
  }, [sectors]);

  const handleSort = useCallback((key: SortKey) => {
    setSortKey(prev => {
      if (prev === key) {
        setSortDir(d => d === 'asc' ? 'desc' : 'asc');
      } else {
        setSortDir('asc');
      }
      return key;
    });
  }, []);

  const filtered = useMemo(() => {
    let result = filterByMarket(stocks, activeTab);
    if (filter) {
      const q = filter.toLowerCase();
      result = result.filter(s => s.symbol.includes(q) || s.name?.toLowerCase().includes(q));
    }
    const range = CHANGE_RANGES[changeRangeIdx];
    if (range && (range.min !== -Infinity || range.max !== Infinity)) {
      result = result.filter(s => s.change_pct >= range.min && s.change_pct <= range.max);
    }
    if (sectorFilter) {
      result = result.filter(s => s.sector === sectorFilter);
    }
    return result;
  }, [stocks, activeTab, filter, changeRangeIdx, sectorFilter]);

  const [sorted, setSorted] = useState<StockQuote[]>([]);
  const [sorting, setSorting] = useState(false);
  const workerRef = useRef<Worker | null>(null);

  useEffect(() => {
    workerRef.current = new Worker(
      new URL('@/workers/sortWorker.ts', import.meta.url),
      { type: 'module' },
    );
    workerRef.current.onmessage = (e: MessageEvent<StockQuote[]>) => {
      setSorted(e.data);
      setSorting(false);
    };
    return () => {
      workerRef.current?.terminate();
    };
  }, []);

  useEffect(() => {
    if (filtered.length === 0) {
      setSorted([]);
      return;
    }
    setSorting(true);
    workerRef.current?.postMessage({
      items: filtered,
      key: sortKey,
      dir: sortDir,
    });
  }, [filtered, sortKey, sortDir]);

  useEffect(() => {
    setFocusedIdx(-1);
  }, [filter, activeTab, changeRangeIdx, sectorFilter]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const handler = (e: KeyboardEvent) => {
      if (contentTab !== 'market') return;
      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          setFocusedIdx(prev => Math.min(prev + 1, sorted.length - 1));
          break;
        case 'ArrowUp':
          e.preventDefault();
          setFocusedIdx(prev => Math.max(prev - 1, 0));
          break;
        case 'Enter':
          if (focusedIdx >= 0 && sorted[focusedIdx]) {
            navigate(`/stock/${sorted[focusedIdx].symbol}`);
          }
          break;
        case 'Escape':
          setFocusedIdx(-1);
          break;
        case ' ':
          if (focusedIdx >= 0 && sorted[focusedIdx]) {
            e.preventDefault();
            toggleWatch(sorted[focusedIdx].symbol);
          }
          break;
        case 'f':
          if (!e.metaKey && !e.ctrlKey && !e.altKey) {
            e.preventDefault();
            searchInputRef.current?.focus();
          }
          break;
      }
    };
    el.addEventListener('keydown', handler);
    return () => el.removeEventListener('keydown', handler);
  }, [contentTab, sorted, focusedIdx, navigate, toggleWatch]);

  const watchlistSet = useMemo(() => new Set(watchlist), [watchlist]);

  const handleRowClick = useCallback((stock: StockQuote) => {
    setSelectedStock(prev => prev?.symbol === stock.symbol ? null : stock);
  }, []);

  const handleCloseDrawer = useCallback(() => {
    setSelectedStock(null);
  }, []);

  const handleToggleWatch = useCallback((symbol: string, e: React.MouseEvent) => {
    e.stopPropagation();
    toggleWatch(symbol);
  }, [toggleWatch]);

  const handleDrawerToggleWatch = useCallback((_e: React.MouseEvent) => {
    if (selectedStock) {
      toggleWatch(selectedStock.symbol);
    }
  }, [selectedStock, toggleWatch]);

  const renderItem = useCallback((stock: StockQuote, index: number, style: React.CSSProperties) => {
    const isWatched = watchlistSet.has(stock.symbol);
    const isFocused = focusedIdx === index;
    return (
      <div
        style={{
          ...style,
          display: 'flex',
          alignItems: 'center',
          height: '40px',
          cursor: 'pointer',
          borderBottom: '1px solid var(--separator)',
          borderLeft: isFocused ? '2px solid var(--accent)' : '2px solid transparent',
          background: isFocused ? 'rgba(10,132,255,0.08)' : undefined,
          transition: `background var(--dur-fast) var(--ease-apple)`,
          boxSizing: 'border-box',
        }}
        onClick={() => handleRowClick(stock)}
        onDoubleClick={() => navigate(`/stock/${stock.symbol}`)}
        onMouseEnter={e => { if (!isFocused) e.currentTarget.style.background = 'var(--accent-soft)'; }}
        onMouseLeave={e => { if (!isFocused) e.currentTarget.style.background = 'transparent'; }}
      >
        <span style={{ width: '80px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--accent)', fontVariantNumeric: 'tabular-nums' }}>
          {stock.symbol}
        </span>
        <span style={{ flex: 1, minWidth: 0, padding: '0 12px', fontFamily: 'var(--font-sans)', fontSize: '13px', fontWeight: 500, color: 'var(--label-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {stock.name}
        </span>
        <span style={{ width: '90px', flexShrink: 0, padding: '0 12px', fontSize: '12px', fontVariantNumeric: 'tabular-nums', textAlign: 'right', boxSizing: 'border-box' }}>
          <TickFlashCell value={stock.price} changePct={stock.change_pct} />
        </span>
        <span style={{ width: '90px', flexShrink: 0, padding: '0 12px', display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 2, boxSizing: 'border-box' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: priceColor(stock.change_pct), fontVariantNumeric: 'tabular-nums', fontWeight: 500 }}>
            {formatPercent(stock.change_pct)}
          </span>
          <LimitBadge changePct={stock.change_pct} />
        </span>
        <span style={{ width: '90px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: (stock.volume_ratio ?? 0) > 3 ? '#FF9100' : 'var(--label-secondary)', fontVariantNumeric: 'tabular-nums', textAlign: 'right', boxSizing: 'border-box', background: (stock.volume_ratio ?? 0) > 3 ? 'rgba(255,145,0,0.08)' : 'transparent' }}>
          {formatVolume(stock.volume)}
        </span>
        <span style={{ width: '100px', flexShrink: 0, padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--label-secondary)', fontVariantNumeric: 'tabular-nums', textAlign: 'right', boxSizing: 'border-box' }}>
          {formatAmount(stock.amount)}
        </span>
        <span style={{ width: '64px', flexShrink: 0, padding: '0 8px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--label-secondary)', fontVariantNumeric: 'tabular-nums', textAlign: 'right', boxSizing: 'border-box' }}>
          {formatPePb(stock.pe)}
        </span>
        <span style={{ width: '64px', flexShrink: 0, padding: '0 8px', fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--label-secondary)', fontVariantNumeric: 'tabular-nums', textAlign: 'right', boxSizing: 'border-box' }}>
          {formatPePb(stock.pb)}
        </span>
        <span style={{ width: '36px', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <button
            onClick={e => handleToggleWatch(stock.symbol, e)}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: isWatched ? 'var(--signal-warn)' : 'var(--label-quaternary)',
              fontSize: '14px',
              padding: '2px',
              transition: `color var(--dur-fast) var(--ease-apple)`,
              lineHeight: 1,
            }}
          >
            {isWatched ? '★' : '☆'}
          </button>
        </span>
      </div>
    );
  }, [watchlistSet, handleRowClick, handleToggleWatch, focusedIdx]);

  return (
    <div ref={containerRef} tabIndex={0} style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg-base)', position: 'relative', outline: 'none' }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        height: '48px',
        padding: '0 var(--s6)',
        borderBottom: '1px solid var(--separator)',
        background: 'var(--bg-glass)',
        backdropFilter: 'blur(24px) saturate(120%)',
        flexShrink: 0,
      }}>
        <span style={{
          fontFamily: 'var(--font-sans)',
          fontSize: '16px',
          fontWeight: 600,
          color: 'var(--label-primary)',
          whiteSpace: 'nowrap',
          marginRight: 'var(--s8)',
        }}>
          股票市场
        </span>

        <div style={{ display: 'flex', alignItems: 'center', gap: '2px', flex: 1, justifyContent: 'center' }}>
          {TABS.map(tab => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              style={{
                fontFamily: 'var(--font-sans)',
                fontSize: '12px',
                color: activeTab === tab.key ? 'var(--accent)' : 'var(--label-tertiary)',
                background: activeTab === tab.key ? 'var(--accent-soft)' : 'transparent',
                border: 'none',
                borderRadius: 'var(--r-sm)',
                padding: '5px 14px',
                cursor: 'pointer',
                transition: `all var(--dur-fast) var(--ease-apple)`,
                whiteSpace: 'nowrap',
                fontWeight: activeTab === tab.key ? 600 : 400,
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s3)', marginLeft: 'var(--s8)' }}>
          <select
            value={changeRangeIdx}
            onChange={e => setChangeRangeIdx(Number(e.target.value))}
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              color: 'var(--label-secondary)',
              background: 'var(--bg-overlay)',
              border: '1px solid var(--separator)',
              borderRadius: 'var(--r-sm)',
              padding: '4px 8px',
              outline: 'none',
              cursor: 'pointer',
            }}
          >
            {CHANGE_RANGES.map((r, i) => (
              <option key={r.label} value={i}>{r.label}</option>
            ))}
          </select>

          <div style={{ position: 'relative' }}>
            <button
              onClick={() => setShowSectorDropdown(v => !v)}
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '11px',
                color: sectorFilter ? 'var(--accent)' : 'var(--label-secondary)',
                background: 'var(--bg-overlay)',
                border: '1px solid var(--separator)',
                borderRadius: 'var(--r-sm)',
                padding: '4px 8px',
                cursor: 'pointer',
                outline: 'none',
              }}
            >
              {sectorFilter || '行业板块'} ▾
            </button>
            {showSectorDropdown && (
              <div style={{
                position: 'absolute',
                top: '100%',
                right: 0,
                zIndex: 20,
                background: 'var(--bg-glass)',
                backdropFilter: 'blur(24px) saturate(120%)',
                border: '1px solid var(--separator)',
                borderRadius: 'var(--r-md)',
                maxHeight: '200px',
                overflow: 'auto',
                minWidth: '120px',
                boxShadow: 'var(--shadow-lg)',
              }}>
                <div
                  onClick={() => { setSectorFilter(''); setShowSectorDropdown(false); }}
                  style={{
                    padding: '6px 12px',
                    fontFamily: 'var(--font-sans)',
                    fontSize: '12px',
                    color: 'var(--label-secondary)',
                    cursor: 'pointer',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent-soft)'; }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                >
                  全部行业
                </div>
                {sectorNames.map(name => (
                  <div
                    key={name}
                    onClick={() => { setSectorFilter(name); setShowSectorDropdown(false); }}
                    style={{
                      padding: '6px 12px',
                      fontFamily: 'var(--font-sans)',
                      fontSize: '12px',
                      color: name === sectorFilter ? 'var(--accent)' : 'var(--label-secondary)',
                      cursor: 'pointer',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent-soft)'; }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                  >
                    {name}
                  </div>
                ))}
              </div>
            )}
          </div>

          <span style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
            color: 'var(--label-quaternary)',
            fontVariantNumeric: 'tabular-nums',
          }}>
            {sorted.length}
          </span>
          <input
            ref={searchInputRef}
            value={filter}
            onChange={e => setFilter(e.target.value)}
            placeholder="搜索代码/名称..."
            style={{
              width: '180px',
              height: '28px',
              fontFamily: 'var(--font-sans)',
              fontSize: '12px',
              color: 'var(--label-primary)',
              background: 'var(--bg-overlay)',
              border: '1px solid var(--separator)',
              borderRadius: 'var(--r-sm)',
              padding: '0 10px',
              outline: 'none',
              transition: `border-color var(--dur-fast) var(--ease-apple)`,
            }}
          />
        </div>
      </div>

      <div style={{
        display: 'flex',
        alignItems: 'center',
        height: '36px',
        padding: '0 var(--s6)',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
        background: '#000000',
        flexShrink: 0,
        gap: '2px',
      }}>
        {CONTENT_TABS.map(tab => (
          <button
            key={tab.key}
            onClick={() => setContentTab(tab.key)}
            style={{
              fontFamily: 'var(--font-sans)',
              fontSize: '12px',
              color: contentTab === tab.key ? ACCENT_HEX : 'rgba(255,255,255,0.4)',
              background: contentTab === tab.key ? 'rgba(10,132,255,0.1)' : 'transparent',
              border: 'none',
              borderRadius: '6px',
              padding: '5px 16px',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
              whiteSpace: 'nowrap',
              fontWeight: contentTab === tab.key ? 600 : 400,
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {contentTab === 'market' && (<>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        height: '32px',
        flexShrink: 0,
        background: 'var(--bg-elevated)',
        borderBottom: '1px solid var(--separator-hi)',
        position: 'sticky',
        top: 0,
        zIndex: 5,
      }}>
        {COL_DEFS.map(col => (
          <span
            key={col.key}
            onClick={() => handleSort(col.key)}
            style={{
              width: col.width,
              flexShrink: 0,
              padding: '0 12px',
              fontFamily: 'var(--font-mono)',
              fontSize: '9px',
              textTransform: 'uppercase',
              letterSpacing: '0.1em',
              color: sortKey === col.key ? 'var(--label-secondary)' : 'var(--label-quaternary)',
              textAlign: col.align,
              cursor: 'pointer',
              userSelect: 'none',
              whiteSpace: 'nowrap',
              transition: `color var(--dur-fast) var(--ease-apple)`,
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: col.align === 'right' ? 'flex-end' : col.align === 'center' ? 'center' : 'flex-start',
              boxSizing: 'border-box',
            }}
          >
            {col.label}{sortKey === col.key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
          </span>
        ))}
        <span style={{
          width: '36px',
          flexShrink: 0,
          fontFamily: 'var(--font-mono)',
          fontSize: '9px',
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
          color: 'var(--label-quaternary)',
          textAlign: 'center',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}>
          ★
        </span>
      </div>

      <div style={{ flex: 1, position: 'relative', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        {loading ? (
          <LoadingState />
        ) : (
          <VirtualList items={sorted} itemHeight={40} renderItem={renderItem} overscan={10} />
        )}

        {selectedStock && (
          <DrawerBackdrop onClose={handleCloseDrawer}>
            <StockDrawer
              stock={selectedStock}
              onClose={handleCloseDrawer}
              isWatched={watchlistSet.has(selectedStock.symbol)}
              onToggleWatch={handleDrawerToggleWatch}
            />
          </DrawerBackdrop>
        )}
      </div>
      </>)}

      {contentTab === 'moneyflow' && <MoneyFlowTab />}
      {contentTab === 'sector' && <SectorRotationTab />}
      {contentTab === 'screener' && <ScreenerTab />}
    </div>
  );
}
