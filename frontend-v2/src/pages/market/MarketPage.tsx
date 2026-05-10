import { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { createChart, CandlestickSeries, type IChartApi, type ISeriesApi, type CandlestickData, type Time } from 'lightweight-charts';
import { useMarketStore } from '@/stores/market';
import { useWatchlistStore } from '@/stores/watchlist';
import { VirtualList } from '@/components/ui/VirtualList';
import { apiGet } from '@/api/client';
import { formatPrice, formatPercent, formatVolume, formatAmount, priceColor } from '@/utils/format';
import type { StockQuote } from '@/types';

type SortKey = 'symbol' | 'name' | 'price' | 'change_pct' | 'volume' | 'amount' | 'pe' | 'pb';
type SortDir = 'asc' | 'desc';
type MarketTab = 'all' | 'sh' | 'sz' | 'cy' | 'kc';

const TABS: Array<{ key: MarketTab; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'sh', label: '沪市' },
  { key: 'sz', label: '深市' },
  { key: 'cy', label: '创业板' },
  { key: 'kc', label: '科创板' },
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

const MONO = "'JetBrains Mono', monospace";
const SERIF = "'Cormorant Garamond', serif";
const SANS = 'system-ui, -apple-system, sans-serif';

function KlineChart({ symbol }: { symbol: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 200,
      layout: { background: { color: '#0a0a0a' as const }, textColor: '#5E5854' },
      grid: { vertLines: { color: 'rgba(255,255,255,0.02)' }, horzLines: { color: 'rgba(255,255,255,0.02)' } },
      crosshair: { mode: 0 },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.04)' },
      timeScale: { borderColor: 'rgba(255,255,255,0.04)', timeVisible: true },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#D4584A',
      downColor: '#4E9E6E',
      borderUpColor: '#D4584A',
      borderDownColor: '#4E9E6E',
      wickUpColor: '#D4584A',
      wickDownColor: '#4E9E6E',
    });
    chartRef.current = chart;
    seriesRef.current = series;

    const loadKline = async () => {
      try {
        const data = await apiGet<Array<{
          time: string;
          open: number;
          high: number;
          low: number;
          close: number;
          volume?: number;
        }>>(`/market/kline`, { symbol, period: 'daily', count: 120 });
        if (Array.isArray(data) && data.length > 0) {
          const candleData: CandlestickData<Time>[] = data.map(d => ({
            time: d.time as Time,
            open: d.open,
            high: d.high,
            low: d.low,
            close: d.close,
          }));
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
      window.removeEventListener('resize', onResize);
      chart.remove();
    };
  }, [symbol]);

  return <div ref={containerRef} style={{ width: '100%', height: '200px' }} />;
}

export function MarketPage() {
  const { stocks, loading, sectors, fetchStocks, fetchSectors } = useMarketStore();
  const watchlist = useWatchlistStore(s => s.symbols);
  const toggleWatch = useWatchlistStore(s => s.toggle);

  const [sortKey, setSortKey] = useState<SortKey>('symbol');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [filter, setFilter] = useState('');
  const [activeTab, setActiveTab] = useState<MarketTab>('all');
  const [selectedStock, setSelectedStock] = useState<StockQuote | null>(null);
  const [changeRangeIdx, setChangeRangeIdx] = useState(0);
  const [sectorFilter, setSectorFilter] = useState('');
  const [showSectorDropdown, setShowSectorDropdown] = useState(false);

  useEffect(() => {
    fetchStocks();
    fetchSectors();
  }, [fetchStocks, fetchSectors]);

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

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      const av = a[sortKey] ?? (typeof a[sortKey] === 'string' ? '' : 0);
      const bv = b[sortKey] ?? (typeof b[sortKey] === 'string' ? '' : 0);
      if (typeof av === 'string' && typeof bv === 'string') {
        return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      return sortDir === 'asc' ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
  }, [filtered, sortKey, sortDir]);

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

  const handleDrawerBackdrop = useCallback((e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      setSelectedStock(null);
    }
  }, []);

  const renderItem = useCallback((stock: StockQuote, _index: number, style: React.CSSProperties) => {
    const isWatched = watchlistSet.has(stock.symbol);
    return (
      <div
        style={{
          ...style,
          display: 'flex',
          alignItems: 'center',
          height: '40px',
          cursor: 'pointer',
          borderBottom: '1px solid rgba(255,255,255,0.02)',
          transition: 'background 160ms cubic-bezier(0,0,0.2,1)',
          boxSizing: 'border-box',
        }}
        onClick={() => handleRowClick(stock)}
        onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.015)'; }}
        onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
      >
        <span style={{ width: '80px', flexShrink: 0, padding: '0 12px', fontFamily: MONO, fontSize: '11px', color: '#C9A96E', fontVariantNumeric: 'tabular-nums' }}>
          {stock.symbol}
        </span>
        <span style={{ flex: 1, minWidth: 0, padding: '0 12px', fontFamily: SANS, fontSize: '13px', fontWeight: 500, color: '#F0EBE3', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {stock.name}
        </span>
        <span style={{ width: '90px', flexShrink: 0, padding: '0 12px', fontFamily: MONO, fontSize: '12px', color: priceColor(stock.change_pct), fontVariantNumeric: 'tabular-nums', textAlign: 'right', boxSizing: 'border-box' }}>
          {formatPrice(stock.price)}
        </span>
        <span style={{ width: '90px', flexShrink: 0, padding: '0 12px', fontFamily: MONO, fontSize: '12px', color: priceColor(stock.change_pct), fontVariantNumeric: 'tabular-nums', textAlign: 'right', fontWeight: 500, boxSizing: 'border-box' }}>
          {formatPercent(stock.change_pct)}
        </span>
        <span style={{ width: '90px', flexShrink: 0, padding: '0 12px', fontFamily: MONO, fontSize: '11px', color: '#9B9490', fontVariantNumeric: 'tabular-nums', textAlign: 'right', boxSizing: 'border-box' }}>
          {formatVolume(stock.volume)}
        </span>
        <span style={{ width: '100px', flexShrink: 0, padding: '0 12px', fontFamily: MONO, fontSize: '11px', color: '#9B9490', fontVariantNumeric: 'tabular-nums', textAlign: 'right', boxSizing: 'border-box' }}>
          {formatAmount(stock.amount)}
        </span>
        <span style={{ width: '64px', flexShrink: 0, padding: '0 8px', fontFamily: MONO, fontSize: '11px', color: '#9B9490', fontVariantNumeric: 'tabular-nums', textAlign: 'right', boxSizing: 'border-box' }}>
          {formatPePb(stock.pe)}
        </span>
        <span style={{ width: '64px', flexShrink: 0, padding: '0 8px', fontFamily: MONO, fontSize: '11px', color: '#9B9490', fontVariantNumeric: 'tabular-nums', textAlign: 'right', boxSizing: 'border-box' }}>
          {formatPePb(stock.pb)}
        </span>
        <span style={{ width: '36px', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <button
            onClick={e => handleToggleWatch(stock.symbol, e)}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              color: isWatched ? '#C9A96E' : '#3A3633',
              fontSize: '14px', padding: '2px',
              transition: 'color 160ms cubic-bezier(0,0,0.2,1)', lineHeight: 1,
            }}
          >
            {isWatched ? '★' : '☆'}
          </button>
        </span>
      </div>
    );
  }, [watchlistSet, handleRowClick, handleToggleWatch]);

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: '#000000', position: 'relative' }}>
      <div style={{
        display: 'flex', alignItems: 'center', height: '48px',
        padding: '0 24px', borderBottom: '1px solid rgba(255,255,255,0.04)',
        background: '#050505', flexShrink: 0,
      }}>
        <span style={{ fontFamily: SERIF, fontSize: '20px', color: '#C9A96E', letterSpacing: '0.02em', whiteSpace: 'nowrap', marginRight: '32px' }}>
          股票市场
        </span>

        <div style={{ display: 'flex', alignItems: 'center', gap: '2px', flex: 1, justifyContent: 'center' }}>
          {TABS.map(tab => (
            <button key={tab.key} onClick={() => setActiveTab(tab.key)} style={{
              fontFamily: MONO, fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.08em',
              color: activeTab === tab.key ? '#C9A96E' : '#5E5854',
              background: activeTab === tab.key ? 'rgba(201,169,110,0.08)' : 'transparent',
              border: 'none', borderRadius: '3px', padding: '5px 12px', cursor: 'pointer',
              transition: 'all 160ms cubic-bezier(0,0,0.2,1)', whiteSpace: 'nowrap',
            }}>
              {tab.label}
            </button>
          ))}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginLeft: '32px' }}>
          <select
            value={changeRangeIdx}
            onChange={e => setChangeRangeIdx(Number(e.target.value))}
            style={{
              fontFamily: MONO, fontSize: '10px', color: '#9B9490',
              background: '#0a0a0a', border: '1px solid rgba(255,255,255,0.04)',
              borderRadius: '3px', padding: '4px 8px', outline: 'none', cursor: 'pointer',
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
                fontFamily: MONO, fontSize: '10px', color: sectorFilter ? '#C9A96E' : '#9B9490',
                background: '#0a0a0a', border: '1px solid rgba(255,255,255,0.04)',
                borderRadius: '3px', padding: '4px 8px', cursor: 'pointer', outline: 'none',
              }}
            >
              {sectorFilter || '行业板块'} ▾
            </button>
            {showSectorDropdown && (
              <div style={{
                position: 'absolute', top: '100%', right: 0, zIndex: 20,
                background: '#0f0f0f', border: '1px solid rgba(255,255,255,0.06)',
                borderRadius: '4px', maxHeight: '200px', overflow: 'auto', minWidth: '120px',
                boxShadow: '0 4px 16px rgba(0,0,0,0.5)',
              }}>
                <div
                  onClick={() => { setSectorFilter(''); setShowSectorDropdown(false); }}
                  style={{ padding: '6px 12px', fontFamily: MONO, fontSize: '10px', color: '#9B9490', cursor: 'pointer' }}
                  onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.03)'; }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                >
                  全部行业
                </div>
                {sectorNames.map(name => (
                  <div
                    key={name}
                    onClick={() => { setSectorFilter(name); setShowSectorDropdown(false); }}
                    style={{ padding: '6px 12px', fontFamily: MONO, fontSize: '10px', color: name === sectorFilter ? '#C9A96E' : '#9B9490', cursor: 'pointer' }}
                    onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.03)'; }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                  >
                    {name}
                  </div>
                ))}
              </div>
            )}
          </div>

          <span style={{ fontFamily: MONO, fontSize: '10px', color: '#3A3633', fontVariantNumeric: 'tabular-nums' }}>
            {sorted.length} ITEMS
          </span>
          <input
            value={filter}
            onChange={e => setFilter(e.target.value)}
            placeholder="FILTER..."
            style={{
              width: '200px', height: '28px', fontFamily: MONO, fontSize: '10px',
              textTransform: 'uppercase', letterSpacing: '0.05em', color: '#F0EBE3',
              background: '#0a0a0a', border: '1px solid rgba(255,255,255,0.04)',
              borderRadius: '3px', padding: '0 10px', outline: 'none',
              transition: 'border-color 160ms cubic-bezier(0,0,0.2,1)',
            }}
          />
        </div>
      </div>

      <div style={{
        display: 'flex', alignItems: 'center', height: '32px', flexShrink: 0,
        background: '#050505', borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}>
        {COL_DEFS.map(col => (
          <span key={col.key} onClick={() => handleSort(col.key)} style={{
            width: col.width, flexShrink: 0, padding: '0 12px',
            fontFamily: MONO, fontSize: '9px', textTransform: 'uppercase',
            letterSpacing: '0.1em', color: sortKey === col.key ? '#9B9490' : '#5E5854',
            textAlign: col.align, cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap',
            transition: 'color 160ms cubic-bezier(0,0,0.2,1)',
            display: 'inline-flex', alignItems: 'center',
            justifyContent: col.align === 'right' ? 'flex-end' : col.align === 'center' ? 'center' : 'flex-start',
            boxSizing: 'border-box',
          }}>
            {col.label}{sortKey === col.key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
          </span>
        ))}
        <span style={{ width: '36px', flexShrink: 0, fontFamily: MONO, fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.1em', color: '#5E5854', textAlign: 'center', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
          ★
        </span>
      </div>

      <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
        {loading ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: '12px' }}>
            <span style={{ fontFamily: SERIF, fontSize: '48px', fontWeight: 300, color: '#C9A96E', lineHeight: 1 }}>Q</span>
            <span style={{ fontFamily: MONO, fontSize: '10px', color: '#3A3633', letterSpacing: '0.12em' }}>LOADING</span>
          </div>
        ) : (
          <VirtualList items={sorted} itemHeight={40} renderItem={renderItem} overscan={10} />
        )}

        {selectedStock && (
          <div style={{ position: 'absolute', inset: 0, zIndex: 10 }} onClick={handleDrawerBackdrop}>
            <div
              style={{
                position: 'absolute', right: 0, top: 0, bottom: 0, width: '320px',
                background: '#0a0a0a', borderLeft: '1px solid rgba(255,255,255,0.06)',
                boxShadow: '-4px 0 16px rgba(0,0,0,0.4)',
                display: 'flex', flexDirection: 'column',
                animation: 'market-drawer-slide-in 280ms cubic-bezier(0.16,1,0.3,1)',
              }}
              onClick={e => e.stopPropagation()}
            >
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.04)', flexShrink: 0,
              }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                  <span style={{ fontFamily: SANS, fontSize: '16px', fontWeight: 600, color: '#F0EBE3', lineHeight: 1.2 }}>{selectedStock.name}</span>
                  <span style={{ fontFamily: MONO, fontSize: '11px', color: '#C9A96E', fontVariantNumeric: 'tabular-nums' }}>{selectedStock.symbol}</span>
                </div>
                <button onClick={handleCloseDrawer} style={{
                  background: 'none', border: '1px solid rgba(255,255,255,0.06)',
                  borderRadius: '4px', color: '#5E5854', fontSize: '14px', cursor: 'pointer',
                  width: '28px', height: '28px', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  transition: 'all 160ms cubic-bezier(0,0,0.2,1)',
                }}
                  onMouseEnter={e => { e.currentTarget.style.color = '#F0EBE3'; e.currentTarget.style.borderColor = 'rgba(255,255,255,0.12)'; }}
                  onMouseLeave={e => { e.currentTarget.style.color = '#5E5854'; e.currentTarget.style.borderColor = 'rgba(255,255,255,0.06)'; }}
                >
                  ✕
                </button>
              </div>

              <div style={{ flex: 1, overflow: 'auto', padding: '20px' }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: '12px', marginBottom: '16px' }}>
                  <span style={{ fontFamily: MONO, fontSize: '28px', fontWeight: 600, color: priceColor(selectedStock.change_pct), fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>
                    {formatPrice(selectedStock.price)}
                  </span>
                  <span style={{ fontFamily: MONO, fontSize: '14px', color: priceColor(selectedStock.change_pct), fontVariantNumeric: 'tabular-nums', fontWeight: 500 }}>
                    {formatPercent(selectedStock.change_pct)}
                  </span>
                </div>

                <div style={{ marginBottom: '16px', borderRadius: '4px', overflow: 'hidden', border: '1px solid rgba(255,255,255,0.04)' }}>
                  <KlineChart symbol={selectedStock.symbol} />
                </div>

                <div style={{ fontFamily: MONO, fontSize: '9px', color: '#5E5854', letterSpacing: '0.08em', marginBottom: '8px', textTransform: 'uppercase' }}>基本面</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
                  {([
                    { label: '成交量', value: formatVolume(selectedStock.volume) },
                    { label: '成交额', value: formatAmount(selectedStock.amount) },
                    { label: '市盈率', value: formatPePb(selectedStock.pe) },
                    { label: '市净率', value: formatPePb(selectedStock.pb) },
                    { label: '今开', value: selectedStock.open !== undefined ? formatPrice(selectedStock.open) : '—' },
                    { label: '最高', value: selectedStock.high !== undefined ? formatPrice(selectedStock.high) : '—' },
                    { label: '最低', value: selectedStock.low !== undefined ? formatPrice(selectedStock.low) : '—' },
                    { label: '昨收', value: selectedStock.close !== undefined ? formatPrice(selectedStock.close) : '—' },
                  ]).map(row => (
                    <div key={row.label} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 0', borderBottom: '1px solid rgba(255,255,255,0.02)' }}>
                      <span style={{ fontFamily: MONO, fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.06em', color: '#5E5854' }}>{row.label}</span>
                      <span style={{ fontFamily: MONO, fontSize: '12px', color: '#F0EBE3', fontVariantNumeric: 'tabular-nums' }}>{row.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      <style>{`
        @keyframes market-drawer-slide-in {
          from { transform: translateX(100%); opacity: 0; }
          to { transform: translateX(0); opacity: 1; }
        }
      `}</style>
    </div>
  );
}
