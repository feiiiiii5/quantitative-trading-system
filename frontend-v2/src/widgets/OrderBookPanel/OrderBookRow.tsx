import { memo, useEffect, useRef, useState } from 'react';
import { cn } from '@/shared/lib/cn';
import { formatPrice, formatVolume } from '@/shared/lib/format';
import type { OrderBookLevel } from '@/features/order-book';

interface OrderBookRowProps {
  level: OrderBookLevel;
  side: 'bid' | 'ask';
  maxTotal: number;
}

export const OrderBookRow = memo(function OrderBookRow({ level, side, maxTotal }: OrderBookRowProps) {
  const [flash, setFlash] = useState<'up' | 'down' | null>(null);
  const prevPriceRef = useRef(level.price);

  useEffect(() => {
    if (prevPriceRef.current !== level.price) {
      setFlash(level.price > prevPriceRef.current ? 'up' : 'down');
      prevPriceRef.current = level.price;
      const timer = setTimeout(() => setFlash(null), 300);
      return () => clearTimeout(timer);
    }
  }, [level.price]);

  const depthPct = maxTotal > 0 ? (level.total / maxTotal) * 100 : 0;

  return (
    <div
      className={cn(
        'flex items-center px-[var(--space-2)] py-px text-[var(--font-size-xs)] font-mono relative',
        flash === 'up' && 'price-up',
        flash === 'down' && 'price-down'
      )}
    >
      <div
        className="absolute inset-y-0 opacity-20"
        style={{
          width: `${depthPct}%`,
          right: side === 'bid' ? 0 : undefined,
          left: side === 'ask' ? 0 : undefined,
          backgroundColor: side === 'bid' ? 'var(--color-bid)' : 'var(--color-ask)',
        }}
      />
      <span
        className={cn('w-1/3 relative z-10', {
          'text-[var(--color-bid)]': side === 'bid',
          'text-[var(--color-ask)]': side === 'ask',
        })}
      >
        {formatPrice(level.price)}
      </span>
      <span className="w-1/3 text-right text-[var(--text-secondary)] relative z-10">
        {formatVolume(level.size)}
      </span>
      <span className="w-1/3 text-right text-[var(--text-muted)] relative z-10">
        {formatVolume(level.total)}
      </span>
    </div>
  );
}, (prev, next) => prev.level.price === next.level.price && prev.level.size === next.level.size);
