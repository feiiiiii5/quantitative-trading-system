import { cn } from '@/shared/lib/cn';

interface MetricCardProps {
  label: string;
  value: string;
  change?: number;
  className?: string;
}

export function MetricCard({ label, value, change, className }: MetricCardProps) {
  return (
    <div className={cn('px-[var(--space-3)] py-[var(--space-2)]', className)}>
      <div className="text-[var(--font-size-xs)] text-[var(--text-muted)] uppercase tracking-wider mb-0.5">
        {label}
      </div>
      <div className="font-mono text-[var(--font-size-lg)] text-[var(--text-primary)]">
        {value}
      </div>
      {change !== undefined && (
        <div
          className={cn('font-mono text-[var(--font-size-xs)]', {
            'text-[var(--color-bid)]': change > 0,
            'text-[var(--color-ask)]': change < 0,
            'text-[var(--color-neutral)]': change === 0,
          })}
        >
          {change > 0 ? '+' : ''}{change.toFixed(2)}%
        </div>
      )}
    </div>
  );
}
