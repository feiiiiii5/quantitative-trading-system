import { Panel, WidgetErrorBoundary, Badge, MetricCard } from '@/shared/ui';
import { useRiskStore } from '@/features/risk-management';
import { formatAmount } from '@/shared/lib/format';
import { cn } from '@/shared/lib/cn';

function CircuitBreakerBanner({ state }: { state: 'active' | 'warning' | 'tripped' }) {
  return (
    <div
      className={cn('px-[var(--space-3)] py-[var(--space-2)] rounded-[var(--radius-md)] text-center text-[var(--font-size-sm)] font-semibold uppercase tracking-wider', {
        'bg-[var(--color-bid)]/10 text-[var(--color-bid)] border border-[var(--color-bid)]/30': state === 'active',
        'bg-[var(--color-warning)]/10 text-[var(--color-warning)] border border-[var(--color-warning)]/30 pulse-dot': state === 'warning',
        'bg-[var(--color-critical)]/10 text-[var(--color-critical)] border border-[var(--color-critical)]/30': state === 'tripped',
      })}
    >
      Circuit Breaker: {state.toUpperCase()}
    </div>
  );
}

function ExposureBar({ label, current, max }: { label: string; current: number; max: number }) {
  const pct = max > 0 ? (current / max) * 100 : 0;
  const color = pct >= 100 ? 'var(--color-critical)' : pct >= 80 ? 'var(--color-warning)' : 'var(--color-bid)';

  return (
    <div className="mb-[var(--space-2)]">
      <div className="flex justify-between text-[var(--font-size-xs)] mb-0.5">
        <span className="text-[var(--text-secondary)]">{label}</span>
        <span className="font-mono text-[var(--text-primary)]">{formatAmount(current)} / {formatAmount(max)}</span>
      </div>
      <div className="h-1.5 bg-[var(--bg-highlight)] rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-[var(--duration-normal)]"
          style={{ width: `${Math.min(pct, 100)}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}

function DrawdownGauge({ current, max }: { current: number; max: number }) {
  const pct = max > 0 ? Math.min((current / max) * 100, 100) : 0;
  const circumference = Math.PI * 40;
  const offset = circumference - (pct / 100) * circumference;
  const color = pct >= 100 ? 'var(--color-critical)' : pct >= 80 ? 'var(--color-warning)' : 'var(--color-bid)';

  return (
    <div className="flex flex-col items-center">
      <svg width="100" height="55" viewBox="0 0 100 55">
        <path
          d="M 10 50 A 40 40 0 0 1 90 50"
          fill="none"
          stroke="var(--bg-highlight)"
          strokeWidth="6"
          strokeLinecap="round"
        />
        <path
          d="M 10 50 A 40 40 0 0 1 90 50"
          fill="none"
          stroke={color}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className="transition-all duration-[var(--duration-normal)]"
        />
      </svg>
      <div className="font-mono text-[var(--font-size-sm)]" style={{ color }}>
        {current.toFixed(1)}% / {max.toFixed(1)}%
      </div>
      <div className="text-[var(--font-size-xs)] text-[var(--text-muted)]">Drawdown</div>
    </div>
  );
}

export function RiskMonitor() {
  const exposure = useRiskStore((s) => s.exposure);
  const alerts = useRiskStore((s) => s.alerts);
  const unreadCount = useRiskStore((s) => s.unreadAlertCount);

  if (!exposure) {
    return (
      <WidgetErrorBoundary>
        <Panel title="Risk Monitor" accent="ask">
          <div className="flex items-center justify-center h-full text-[var(--text-muted)] text-[var(--font-size-sm)]">
            No risk data
          </div>
        </Panel>
      </WidgetErrorBoundary>
    );
  }

  return (
    <WidgetErrorBoundary>
      <Panel
        title="Risk Monitor"
        accent="ask"
        headerRight={
          unreadCount > 0 ? (
            <Badge variant="danger">{unreadCount}</Badge>
          ) : undefined
        }
      >
        <div className="flex flex-col gap-[var(--space-3)] p-[var(--space-2)] overflow-y-auto h-full">
          <CircuitBreakerBanner state={exposure.circuitBreaker} />

          <div className="grid grid-cols-2 gap-[var(--space-2)]">
            <MetricCard label="95% VaR" value={formatAmount(exposure.var95)} />
            <MetricCard label="99% VaR" value={formatAmount(exposure.var99)} />
          </div>

          <DrawdownGauge current={exposure.currentDrawdown} max={exposure.maxDrawdown} />

          <ExposureBar
            label="Total Exposure"
            current={exposure.totalExposure}
            max={exposure.maxExposure}
          />

          <div className="mt-auto">
            <div className="text-[var(--font-size-xs)] text-[var(--text-muted)] uppercase tracking-wider mb-[var(--space-1)]">
              Recent Alerts
            </div>
            <div className="max-h-[120px] overflow-y-auto">
              {alerts.slice(0, 10).map((alert) => (
                <div key={alert.id} className="flex items-start gap-[var(--space-1)] py-px text-[var(--font-size-xs)]">
                  <Badge
                    variant={alert.severity === 'critical' ? 'danger' : alert.severity === 'error' ? 'danger' : alert.severity === 'warning' ? 'warning' : 'info'}
                    pulse={alert.severity === 'critical'}
                  >
                    {alert.severity}
                  </Badge>
                  <span className="text-[var(--text-secondary)]">{alert.message}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </Panel>
    </WidgetErrorBoundary>
  );
}
