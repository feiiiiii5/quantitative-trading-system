import { Panel, WidgetErrorBoundary, Button } from '@/shared/ui';
import { useOrderEntryStore } from '@/features/order-entry';
import { cn } from '@/shared/lib/cn';

export function TradePanel() {
  const symbol = useOrderEntryStore((s) => s.symbol);
  const side = useOrderEntryStore((s) => s.side);
  const type = useOrderEntryStore((s) => s.type);
  const qty = useOrderEntryStore((s) => s.qty);
  const price = useOrderEntryStore((s) => s.price);
  const setSymbol = useOrderEntryStore((s) => s.setSymbol);
  const setSide = useOrderEntryStore((s) => s.setSide);
  const setType = useOrderEntryStore((s) => s.setType);
  const setQty = useOrderEntryStore((s) => s.setQty);
  const setPrice = useOrderEntryStore((s) => s.setPrice);

  return (
    <WidgetErrorBoundary>
      <Panel title="Order Entry" accent="accent">
        <div className="p-[var(--space-3)] flex flex-col gap-[var(--space-2)]">
          <div className="flex gap-1">
            <button
              onClick={() => setSide('buy')}
              className={cn('flex-1 py-1 text-[var(--font-size-sm)] font-medium rounded-[var(--radius-sm)] transition-colors', {
                'bg-[var(--color-bid)] text-[var(--bg-base)]': side === 'buy',
                'bg-[var(--bg-elevated)] text-[var(--text-muted)]': side !== 'buy',
              })}
            >
              BUY
            </button>
            <button
              onClick={() => setSide('sell')}
              className={cn('flex-1 py-1 text-[var(--font-size-sm)] font-medium rounded-[var(--radius-sm)] transition-colors', {
                'bg-[var(--color-ask)] text-white': side === 'sell',
                'bg-[var(--bg-elevated)] text-[var(--text-muted)]': side !== 'sell',
              })}
            >
              SELL
            </button>
          </div>

          <input
            type="text"
            placeholder="Symbol"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="w-full h-7 px-2 bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-sm)] text-[var(--font-size-sm)] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--text-accent)] font-mono"
          />

          <select
            value={type}
            onChange={(e) => setType(e.target.value as 'market' | 'limit' | 'stop' | 'stop_limit')}
            className="w-full h-7 px-2 bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-sm)] text-[var(--font-size-sm)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--text-accent)]"
          >
            <option value="market">Market</option>
            <option value="limit">Limit</option>
            <option value="stop">Stop</option>
            <option value="stop_limit">Stop Limit</option>
          </select>

          <input
            type="number"
            placeholder="Quantity"
            value={qty || ''}
            onChange={(e) => setQty(Number(e.target.value))}
            className="w-full h-7 px-2 bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-sm)] text-[var(--font-size-sm)] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--text-accent)] font-mono"
          />

          {type !== 'market' && (
            <input
              type="number"
              placeholder="Price"
              value={price || ''}
              onChange={(e) => setPrice(Number(e.target.value))}
              className="w-full h-7 px-2 bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-sm)] text-[var(--font-size-sm)] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--text-accent)] font-mono"
            />
          )}

          <Button
            variant={side === 'buy' ? 'primary' : 'danger'}
            className="w-full mt-1"
          >
            {side === 'buy' ? 'BUY' : 'SELL'} {symbol || '...'}
          </Button>
        </div>
      </Panel>
    </WidgetErrorBoundary>
  );
}
