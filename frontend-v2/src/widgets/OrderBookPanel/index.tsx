import { useEffect, useRef, memo } from 'react';
import { Panel, WidgetErrorBoundary } from '@/shared/ui';
import { useOrderBookStore, groupLevels } from '@/features/order-book';
import { OrderBookRow } from './OrderBookRow';
import { OrderBookRenderer } from './OrderBookRenderer';
import { formatPrice } from '@/shared/lib/format';
import type { GroupSize } from '@/features/order-book';

const GROUP_SIZES: GroupSize[] = [0.01, 0.1, 1, 10, 100];

export const OrderBookPanel = memo(function OrderBookPanel() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<OrderBookRenderer | null>(null);

  const bids = useOrderBookStore((s) => s.bids);
  const asks = useOrderBookStore((s) => s.asks);
  const spread = useOrderBookStore((s) => s.spread);
  const midPrice = useOrderBookStore((s) => s.midPrice);
  const groupSize = useOrderBookStore((s) => s.groupSize);
  const setGroupSize = useOrderBookStore((s) => s.setGroupSize);

  const groupedBids = groupLevels(bids.slice(0, 20), groupSize);
  const groupedAsks = groupLevels(asks.slice(0, 20), groupSize);
  const maxTotal = Math.max(
    ...groupedBids.map((l) => l.total),
    ...groupedAsks.map((l) => l.total),
    1
  );

  useEffect(() => {
    if (!canvasRef.current || rendererRef.current) return;
    rendererRef.current = new OrderBookRenderer(canvasRef.current);
    return () => {
      rendererRef.current?.destroy();
      rendererRef.current = null;
    };
  }, []);

  useEffect(() => {
    rendererRef.current?.render(groupedBids, groupedAsks, maxTotal);
  }, [groupedBids, groupedAsks, maxTotal]);

  return (
    <WidgetErrorBoundary>
      <Panel
        title="Order Book"
        accent="bid"
        headerRight={
          <div className="flex items-center gap-1">
            {GROUP_SIZES.map((size) => (
              <button
                key={size}
                onClick={() => setGroupSize(size)}
                className={`px-1.5 py-0.5 text-[var(--font-size-xs)] rounded-[var(--radius-sm)] transition-colors ${
                  groupSize === size
                    ? 'bg-[var(--text-accent)] text-[var(--bg-base)]'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                }`}
              >
                {size}
              </button>
            ))}
          </div>
        }
      >
        <div className="flex h-full">
          <div className="flex-1 flex flex-col overflow-hidden">
            <div className="flex-1 overflow-hidden flex flex-col justify-end">
              {[...groupedAsks].reverse().map((level, i) => (
                <OrderBookRow key={`ask-${i}`} level={level} side="ask" maxTotal={maxTotal} />
              ))}
            </div>

            <div className="flex items-center justify-between px-[var(--space-2)] py-[var(--space-1)] border-y border-[var(--bg-border)] bg-[var(--bg-elevated)]">
              <span className="font-mono text-[var(--font-size-sm)] text-[var(--text-primary)]">
                {formatPrice(midPrice)}
              </span>
              <span className="font-mono text-[var(--font-size-xs)] text-[var(--text-muted)]">
                Spread: {formatPrice(spread)}
              </span>
            </div>

            <div className="flex-1 overflow-hidden">
              {groupedBids.map((level, i) => (
                <OrderBookRow key={`bid-${i}`} level={level} side="bid" maxTotal={maxTotal} />
              ))}
            </div>
          </div>

          <div className="w-[200px] border-l border-[var(--bg-border)]">
            <canvas ref={canvasRef} className="w-full h-full" />
          </div>
        </div>
      </Panel>
    </WidgetErrorBoundary>
  );
});
