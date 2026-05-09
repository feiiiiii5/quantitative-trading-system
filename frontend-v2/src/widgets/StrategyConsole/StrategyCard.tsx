import { memo } from 'react';
import { Badge, Button } from '@/shared/ui';
import { formatAmount, formatPct } from '@/shared/lib/format';
import type { Strategy, StrategyStatus } from '@/entities/strategy';
import { cn } from '@/shared/lib/cn';

const STATUS_CONFIG: Record<StrategyStatus, { variant: 'success' | 'warning' | 'danger' | 'neutral'; label: string; pulse: boolean }> = {
  running: { variant: 'success', label: 'RUNNING', pulse: true },
  paused: { variant: 'warning', label: 'PAUSED', pulse: false },
  stopped: { variant: 'neutral', label: 'STOPPED', pulse: false },
  error: { variant: 'danger', label: 'ERROR', pulse: true },
};

interface StrategyCardProps {
  strategy: Strategy;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onStop: (id: string) => void;
  onParams: (id: string) => void;
}

export const StrategyCard = memo(function StrategyCard({ strategy, onPause, onResume, onStop, onParams }: StrategyCardProps) {
  const config = STATUS_CONFIG[strategy.status];

  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-md)] p-[var(--space-3)]">
      <div className="flex items-center justify-between mb-[var(--space-2)]">
        <span className="text-[var(--font-size-sm)] font-semibold text-[var(--text-primary)] tracking-wide">
          {strategy.name}
        </span>
        <Badge variant={config.variant} pulse={config.pulse}>
          {config.label}
        </Badge>
      </div>

      <div className="flex items-center gap-[var(--space-3)] text-[var(--font-size-xs)] text-[var(--text-muted)] mb-[var(--space-2)]">
        <span>{strategy.symbols.join(', ')}</span>
        <span>•</span>
        <span>{formatAmount(strategy.capital)}</span>
      </div>

      <div className="grid grid-cols-4 gap-[var(--space-2)] mb-[var(--space-2)]">
        <div>
          <div className="text-[var(--font-size-xs)] text-[var(--text-muted)]">PnL Today</div>
          <div className={cn('font-mono text-[var(--font-size-sm)]', {
            'text-[var(--color-bid)]': strategy.totalPnl > 0,
            'text-[var(--color-ask)]': strategy.totalPnl < 0,
            'text-[var(--color-neutral)]': strategy.totalPnl === 0,
          })}>
            {formatAmount(strategy.totalPnl)}
          </div>
        </div>
        <div>
          <div className="text-[var(--font-size-xs)] text-[var(--text-muted)]">Sharpe(30d)</div>
          <div className="font-mono text-[var(--font-size-sm)] text-[var(--text-primary)]">
            {strategy.metrics.sharpe30d.toFixed(2)}
          </div>
        </div>
        <div>
          <div className="text-[var(--font-size-xs)] text-[var(--text-muted)]">Max DD</div>
          <div className="font-mono text-[var(--font-size-sm)] text-[var(--color-ask)]">
            {formatPct(strategy.metrics.maxDrawdown)}
          </div>
        </div>
        <div>
          <div className="text-[var(--font-size-xs)] text-[var(--text-muted)]">Win Rate</div>
          <div className="font-mono text-[var(--font-size-sm)] text-[var(--text-primary)]">
            {(strategy.metrics.winRate * 100).toFixed(1)}%
          </div>
        </div>
      </div>

      {strategy.position && (
        <div className="text-[var(--font-size-xs)] text-[var(--text-secondary)] mb-[var(--space-2)]">
          Position: {strategy.position.side.toUpperCase()} {strategy.position.qty} @ {formatAmount(strategy.position.avgEntryPrice)}
          <span className={cn('ml-2', {
            'text-[var(--color-bid)]': strategy.position.side === 'long',
            'text-[var(--color-ask)]': strategy.position.side === 'short',
          })}>
            Unreal. PnL: {formatAmount(strategy.unrealizedPnl)}
          </span>
        </div>
      )}

      <div className="flex items-center gap-[var(--space-1)]">
        {strategy.status === 'running' && (
          <Button size="sm" variant="secondary" onClick={() => onPause(strategy.id)}>⏸ Pause</Button>
        )}
        {strategy.status === 'paused' && (
          <Button size="sm" variant="primary" onClick={() => onResume(strategy.id)}>▶ Resume</Button>
        )}
        {strategy.status !== 'stopped' && (
          <Button size="sm" variant="danger" onClick={() => onStop(strategy.id)}>⏹ Stop</Button>
        )}
        <Button size="sm" variant="ghost" onClick={() => onParams(strategy.id)}>⚙ Params</Button>
      </div>
    </div>
  );
});
