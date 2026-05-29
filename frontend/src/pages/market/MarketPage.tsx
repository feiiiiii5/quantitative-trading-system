import { useState, useDeferredValue, lazy, Suspense } from 'react';
import { useMarketStocks } from '@/hooks/queries/useMarketQueries';
import { useWatchlist } from '@/hooks/queries/useWatchlistQueries';
import { useMarketViewPersist } from '@/hooks/useMarketViewPersist';
import { LoadingState, ACCENT_HEX } from './shared';
import type { ContentTab } from './types';
import type { StockQuote } from '@/types';
import { StockListTab } from './StockListTab';

const MoneyFlowTab = lazy(() => import('./MoneyFlowTab').then(m => ({ default: m.MoneyFlowTab })));
const SectorRotationTab = lazy(() => import('./SectorRotationTab').then(m => ({ default: m.SectorRotationTab })));
const ScreenerTab = lazy(() => import('./ScreenerTab').then(m => ({ default: m.ScreenerTab })));

const CONTENT_TABS: Array<{ key: ContentTab; label: string }> = [
  { key: 'market', label: '行情' },
  { key: 'moneyflow', label: '资金流向' },
  { key: 'sector', label: '板块轮动' },
  { key: 'screener', label: '条件选股' },
];

const EMPTY_STOCKS: StockQuote[] = [];

export function MarketPage() {
  const { data: stocksData, isLoading: loading, error: stocksError, refetch: refetchStocks } = useMarketStocks('A');
  const stocks = stocksData ?? EMPTY_STOCKS;
  const deferredStocks = useDeferredValue(stocks);
  const { data: watchlistData } = useWatchlist();
  const watchlist = watchlistData?.symbols ?? [];

  const { view: persisted, update: updateView } = useMarketViewPersist();
  const [contentTab, setContentTab] = useState<ContentTab>(persisted.contentTab as ContentTab);

  return (
    <div tabIndex={0} style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg-base)', position: 'relative', outline: 'none' }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        height: '36px',
        padding: '0 var(--s6)',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
        background: 'var(--bg-base)',
        flexShrink: 0,
        gap: '2px',
      }}>
        {CONTENT_TABS.map(tab => (
          <button
            key={tab.key}
            onClick={() => { setContentTab(tab.key); updateView('contentTab', tab.key); }}
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

      {contentTab === 'market' && (
        <StockListTab
          stocks={deferredStocks}
          watchlist={watchlist}
          loading={loading}
          error={stocksError}
          refetch={refetchStocks}
          persistedSortKey={persisted.sortKey}
          persistedSortDir={persisted.sortDir}
          persistedActiveTab={persisted.activeTab}
          persistedChangeRangeIdx={persisted.changeRangeIdx}
          persistedSectorFilter={persisted.sectorFilter}
          updateView={updateView}
        />
      )}
      {contentTab === 'moneyflow' && (
        <Suspense fallback={<LoadingState />}><MoneyFlowTab /></Suspense>
      )}
      {contentTab === 'sector' && (
        <Suspense fallback={<LoadingState />}><SectorRotationTab /></Suspense>
      )}
      {contentTab === 'screener' && (
        <Suspense fallback={<LoadingState />}><ScreenerTab /></Suspense>
      )}
    </div>
  );
}
