import { useState, useCallback, useMemo, useEffect, useRef, memo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMarketSectors } from '@/hooks/queries/useMarketQueries';
import { useAddToWatchlist, useRemoveFromWatchlist } from '@/hooks/queries/useWatchlistQueries';
import { useContextMenu } from '@/hooks/useContextMenu';
import { ContextMenu } from '@/components/ui/ContextMenu';
import { VirtualList } from '@/components/ui/VirtualList';
import { EmptyState } from '@/components/ui/EmptyState';
import { ExportButton } from '@/components/ExportButton';
import { MarketStatsBar } from '@/components/MarketStatsBar';
import { formatPrice, formatPercent, formatVolume, formatAmount, priceColor } from '@/utils/format';
import type { StockQuote } from '@/types';
import { TickFlashCell, LimitBadge, KlineChart, formatPePb, changeColor, StockDrawer, DrawerBackdrop } from './shared';
import type { SortKey, SortDir, MarketTab } from './types';

const TABS: Array<{ key: MarketTab; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'sh', label: '沪市' },
  { key: 'sz', label: '深市' },
  { key: 'cy', label: '创业板' },
  { key: 'kc', label: '科创板' },
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

const CHANGE_RANGES = [
  { label: '全部', min: -Infinity, max: Infinity },
  { label: '涨幅>5%', min: 5, max: Infinity },
  { label: '涨幅2-5%', min: 2, max: 5 },
  { label: '跌幅2-5%', min: -5, max: -2 },
  { label: '跌幅>5%', min: -Infinity, max: -5 },
];

function filterByMarket(stocks: StockQuote[], tab: MarketTab): StockQuote[] {
  if (tab === 'all') return stocks;
  if (tab === 'sh') return stocks.filter(s => s.symbol.startsWith('6'));
  if (tab === 'sz') return stocks.filter(s => s.symbol.startsWith('0') || s.symbol.startsWith('3'));
  if (tab === 'cy') return stocks.filter(s => s.symbol.startsWith('3'));
  if (tab === 'kc') return stocks.filter(s => s.symbol.startsWith('688'));
  return stocks;
}

interface StockListTabProps {
  stocks: StockQuote[];
  watchlist: string[];
  loading: boolean;
  error: unknown;
  refetch: () => void;
  persistedSortKey: string;
  persistedSortDir: string;
  persistedActiveTab: string;
  persistedChangeRangeIdx: number;
  persistedSectorFilter: string;
  updateView: <K extends string>(key: K, value: unknown) => void;
}

export const StockListTab = memo(function StockListTab({
  stocks,
  watchlist,
  loading,
  error,
  refetch,
  persistedSortKey,
  persistedSortDir,
  persistedActiveTab,
  persistedChangeRangeIdx,
  persistedSectorFilter,
  updateView,
}: StockListTabProps) {
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const workerRef = useRef<Worker | null>(null);

  const [sortKey, setSortKey] = useState<SortKey>(persistedSortKey as SortKey);
  const [sortDir, setSortDir] = useState<SortDir>(persistedSortDir as SortDir);
  const [filter, setFilter] = useState('');
  const [activeTab, setActiveTab] = useState<MarketTab>(persistedActiveTab as MarketTab);
  const [selectedStock, setSelectedStock] = useState<StockQuote | null>(null);
  const [focusedIdx, setFocusedIdx] = useState(-1);
  const [changeRangeIdx, setChangeRangeIdx] = useState(persistedChangeRangeIdx);
  const [sectorFilter, setSectorFilter] = useState(persistedSectorFilter);
  const [showSectorDropdown, setShowSectorDropdown] = useState(false);
  const [sorted, setSorted] = useState<StockQuote[]>([]);

  const { data: sectorsData } = useMarketSectors();
  const sectorNames = useMemo(() => {
    if (!sectorsData?.sectors) return [];
    return Object.keys(sectorsData.sectors);
  }, [sectorsData]);

  const addWatch = useAddToWatchlist();
  const removeWatch = useRemoveFromWatchlist();
  const toggleWatch = useCallback((symbol: string) => {
    if (watchlist.includes(symbol)) {
      removeWatch.mutate(symbol);
    } else {
      addWatch.mutate(symbol);
    }
  }, [watchlist, addWatch, removeWatch]);

  const { state: ctxState, onContextMenu, close: closeCtx } = useContextMenu();
  const menuItems = useMemo(() => selectedStock ? [
    { label: `查看 ${selectedStock.symbol} 详情`, onClick: () => { navigate(`/stock/${selectedStock.symbol}`); closeCtx(); } },
    { label: watchlist.includes(selectedStock.symbol) ? '取消关注' : '加入关注', onClick: () => { toggleWatch(selectedStock.symbol); closeCtx(); } },
  ] : [], [selectedStock, watchlist, toggleWatch, navigate, closeCtx]);

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

  useEffect(() => {
    workerRef.current = new Worker(
      new URL('@/workers/sortWorker.ts', import.meta.url),
      { type: 'module' },
    );
    return () => {
      workerRef.current?.terminate();
      workerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const worker = workerRef.current;
    if (!worker) return;
    worker.postMessage({ items: filtered, sortKey, sortDir });
    const handler = (e: MessageEvent) => { setSorted(e.data); };
    worker.addEventListener('message', handler);
    return () => { worker.removeEventListener('message', handler); };
  }, [filtered, sortKey, sortDir]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const handler = (e: KeyboardEvent) => {
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
  }, [sorted, focusedIdx, navigate, toggleWatch]);

  const watchlistSet = useMemo(() => new Set(watchlist), [watchlist]);

  const handleSort = useCallback((key: SortKey) => {
    setSortKey(prev => {
      if (prev === key) {
        setSortDir(d => {
          const next = d === 'asc' ? 'desc' : 'asc';
          updateView('sortDir', next);
          return next;
        });
      } else {
        setSortDir('asc');
        updateView('sortDir', 'asc');
      }
      updateView('sortKey', key);
      return key;
    });
  }, [updateView]);

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
        onContextMenu={(e) => onContextMenu(e, stock)}
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
  }, [watchlistSet, handleRowClick, handleToggleWatch, focusedIdx, navigate, onContextMenu]);

  return (
    <div ref={containerRef} tabIndex={0} style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, outline: 'none' }}>
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
              onClick={() => { setActiveTab(tab.key); updateView('activeTab', tab.key); }}
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
            onChange={e => { const v = Number(e.target.value); setChangeRangeIdx(v); updateView('changeRangeIdx', v); }}
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
                  onClick={() => { setSectorFilter(''); setShowSectorDropdown(false); updateView('sectorFilter', ''); }}
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
                    onClick={() => { setSectorFilter(name); setShowSectorDropdown(false); updateView('sectorFilter', name); }}
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
          <ExportButton
            headers={['代码', '名称', '现价', '涨跌幅', '成交量', '成交额', 'PE', 'PB']}
            rows={sorted.map(s => [s.symbol, s.name, s.price, s.change_pct, s.volume, s.amount, s.pe ?? '', s.pb ?? ''])}
            filename={`A股行情_${new Date().toISOString().slice(0, 10)}`}
            label="导出"
          />
        </div>
      </div>

      <MarketStatsBar stocks={stocks} />
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
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--label-quaternary)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>加载中...</div>
        ) : error ? (
          <EmptyState title="加载失败" description="无法获取行情数据，请检查网络连接" size="md" action={{ label: '重试', onClick: () => refetch() }} />
        ) : sorted.length === 0 ? (
          <EmptyState title="暂无数据" description="当前筛选条件下没有匹配的股票" size="md" />
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
      {ctxState && <ContextMenu x={ctxState.x} y={ctxState.y} items={menuItems} onClose={closeCtx} />}
    </div>
  );
});
