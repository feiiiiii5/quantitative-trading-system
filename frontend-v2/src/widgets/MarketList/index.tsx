import { memo, useMemo, useCallback, useState, useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Panel, WidgetErrorBoundary } from '@/shared/ui';
import { useMarketStore } from '@/features/market-data';
import { formatPrice, formatPct, formatVolume } from '@/shared/lib/format';
import type { TickData } from '@/entities/tick';
import { cn } from '@/shared/lib/cn';

interface MarketListRowProps {
  quote: TickData;
  isSelected: boolean;
  onSelect: (symbol: string) => void;
}

const MarketListRow = memo(function MarketListRow({ quote, isSelected, onSelect }: MarketListRowProps) {
  return (
    <button
      onClick={() => onSelect(quote.symbol)}
      className={cn(
        'w-full flex items-center px-[var(--space-2)] py-[var(--space-1)] text-[var(--font-size-xs)] font-mono transition-colors',
        isSelected
          ? 'bg-[var(--bg-highlight)] border-l-2 border-l-[var(--color-bid)]'
          : 'hover:bg-[var(--bg-highlight)]'
      )}
    >
      <span className="w-24 text-left text-[var(--text-primary)] truncate">{quote.symbol}</span>
      <span className={cn('w-20 text-right', {
        'text-[var(--color-bid)]': quote.changePct > 0,
        'text-[var(--color-ask)]': quote.changePct < 0,
        'text-[var(--color-neutral)]': quote.changePct === 0,
      })}>
        {formatPrice(quote.price)}
      </span>
      <span className={cn('w-16 text-right', {
        'text-[var(--color-bid)]': quote.changePct > 0,
        'text-[var(--color-ask)]': quote.changePct < 0,
        'text-[var(--color-neutral)]': quote.changePct === 0,
      })}>
        {formatPct(quote.changePct)}
      </span>
      <span className="w-16 text-right text-[var(--text-muted)]">
        {formatVolume(quote.volume)}
      </span>
    </button>
  );
}, (prev, next) => prev.quote.price === next.quote.price && prev.quote.changePct === next.quote.changePct && prev.isSelected === next.isSelected);

export function MarketList() {
  const quotes = useMarketStore((s) => s.quotes);
  const [search, setSearch] = useState('');
  const [selectedSymbol, setSelectedSymbol] = useState('');

  const quoteList = useMemo(() => {
    const all = Array.from(quotes.values());
    if (!search) return all;
    const lower = search.toLowerCase();
    return all.filter((q) => q.symbol.toLowerCase().includes(lower));
  }, [quotes, search]);

  const parentRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: quoteList.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 28,
    overscan: 20,
  });

  const handleSelect = useCallback((symbol: string) => {
    setSelectedSymbol(symbol);
  }, []);

  return (
    <WidgetErrorBoundary>
      <Panel title="Markets" accent="neutral">
        <div className="flex flex-col h-full">
          <div className="px-[var(--space-2)] py-[var(--space-1)] border-b border-[var(--bg-border)]">
            <input
              type="text"
              placeholder="Search symbol..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full h-6 px-2 bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-sm)] text-[var(--font-size-xs)] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--text-accent)]"
            />
          </div>

          <div className="flex items-center px-[var(--space-2)] py-px text-[var(--font-size-xs)] text-[var(--text-muted)] border-b border-[var(--bg-border)]">
            <span className="w-24">Symbol</span>
            <span className="w-20 text-right">Price</span>
            <span className="w-16 text-right">Chg%</span>
            <span className="w-16 text-right">Vol</span>
          </div>

          <div ref={parentRef} className="flex-1 overflow-y-auto">
            <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
              {virtualizer.getVirtualItems().map((virtualRow) => {
                const quote = quoteList[virtualRow.index];
                return (
                  <div
                    key={virtualRow.key}
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: '100%',
                      transform: `translateY(${virtualRow.start}px)`,
                    }}
                  >
                    <MarketListRow
                      quote={quote}
                      isSelected={selectedSymbol === quote.symbol}
                      onSelect={handleSelect}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </Panel>
    </WidgetErrorBoundary>
  );
}
