import { Panel, Button, MetricCard } from '@/shared/ui';
import { useBacktestStore, useRunBacktest } from '@/features/backtest';
import { formatPct } from '@/shared/lib/format';

function BacktestConfigPanel() {
  const config = useBacktestStore((s) => s.config);
  const setConfig = useBacktestStore((s) => s.setConfig);
  const runBacktest = useRunBacktest();

  return (
    <Panel title="Configuration" accent="accent">
      <div className="p-[var(--space-3)] flex flex-col gap-[var(--space-2)] overflow-y-auto h-full">
        <div>
          <label className="text-[var(--font-size-xs)] text-[var(--text-muted)] uppercase tracking-wider block mb-1">Strategy</label>
          <input
            type="text"
            value={config.strategy ?? ''}
            onChange={(e) => setConfig({ strategy: e.target.value })}
            placeholder="Strategy name"
            className="w-full h-7 px-2 bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-sm)] text-[var(--font-size-sm)] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--text-accent)]"
          />
        </div>

        <div>
          <label className="text-[var(--font-size-xs)] text-[var(--text-muted)] uppercase tracking-wider block mb-1">Symbols</label>
          <input
            type="text"
            value={(config.symbols ?? []).join(', ')}
            onChange={(e) => setConfig({ symbols: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })}
            placeholder="000001.SZ, 000002.SZ"
            className="w-full h-7 px-2 bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-sm)] text-[var(--font-size-sm)] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--text-accent)] font-mono"
          />
        </div>

        <div className="grid grid-cols-2 gap-[var(--space-2)]">
          <div>
            <label className="text-[var(--font-size-xs)] text-[var(--text-muted)] uppercase tracking-wider block mb-1">Start Date</label>
            <input
              type="date"
              value={config.startDate ?? ''}
              onChange={(e) => setConfig({ startDate: e.target.value })}
              className="w-full h-7 px-2 bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-sm)] text-[var(--font-size-sm)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--text-accent)]"
            />
          </div>
          <div>
            <label className="text-[var(--font-size-xs)] text-[var(--text-muted)] uppercase tracking-wider block mb-1">End Date</label>
            <input
              type="date"
              value={config.endDate ?? ''}
              onChange={(e) => setConfig({ endDate: e.target.value })}
              className="w-full h-7 px-2 bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-sm)] text-[var(--font-size-sm)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--text-accent)]"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-[var(--space-2)]">
          <div>
            <label className="text-[var(--font-size-xs)] text-[var(--text-muted)] uppercase tracking-wider block mb-1">Capital</label>
            <input
              type="number"
              value={config.capital ?? 100000}
              onChange={(e) => setConfig({ capital: Number(e.target.value) })}
              className="w-full h-7 px-2 bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-sm)] text-[var(--font-size-sm)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--text-accent)] font-mono"
            />
          </div>
          <div>
            <label className="text-[var(--font-size-xs)] text-[var(--text-muted)] uppercase tracking-wider block mb-1">Commission</label>
            <input
              type="number"
              step="0.001"
              value={config.commission ?? 0.001}
              onChange={(e) => setConfig({ commission: Number(e.target.value) })}
              className="w-full h-7 px-2 bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-sm)] text-[var(--font-size-sm)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--text-accent)] font-mono"
            />
          </div>
        </div>

        <div>
          <label className="text-[var(--font-size-xs)] text-[var(--text-muted)] uppercase tracking-wider block mb-1">Slippage Model</label>
          <select
            value={config.slippage ?? 'realistic'}
            onChange={(e) => setConfig({ slippage: e.target.value as 'market' | 'realistic' | 'zero' })}
            className="w-full h-7 px-2 bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-sm)] text-[var(--font-size-sm)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--text-accent)]"
          >
            <option value="zero">Zero</option>
            <option value="realistic">Realistic</option>
            <option value="market">Market Impact</option>
          </select>
        </div>

        <div className="mt-auto">
          <Button
            className="w-full"
            onClick={() => {
              if (config.strategy && config.symbols?.length) {
                runBacktest.mutate(config as any);
              }
            }}
            disabled={runBacktest.isPending || !config.strategy}
          >
            {runBacktest.isPending ? 'Running...' : '▶ Run Backtest'}
          </Button>
        </div>
      </div>
    </Panel>
  );
}

function BacktestProgressOverlay() {
  const currentJob = useBacktestStore((s) => s.currentJob);
  if (!currentJob || currentJob.status !== 'running') return null;

  return (
    <div className="absolute inset-0 bg-[var(--bg-base)]/80 flex items-center justify-center z-50">
      <div className="bg-[var(--bg-surface)] border border-[var(--bg-border)] rounded-[var(--radius-lg)] p-[var(--space-6)] w-[400px]">
        <div className="text-[var(--text-primary)] text-[var(--font-size-lg)] font-medium mb-[var(--space-3)]">
          Backtesting...
        </div>
        <div className="h-2 bg-[var(--bg-highlight)] rounded-full overflow-hidden mb-[var(--space-2)]">
          <div
            className="h-full bg-[var(--text-accent)] rounded-full transition-all duration-300"
            style={{ width: `${currentJob.progress}%` }}
          />
        </div>
        <div className="flex justify-between text-[var(--font-size-xs)] text-[var(--text-muted)]">
          <span>Simulating: {currentJob.currentDate ?? '...'}</span>
          <span>{currentJob.progress.toFixed(0)}%</span>
        </div>
      </div>
    </div>
  );
}

function BacktestResults() {
  const results = useBacktestStore((s) => s.results);
  const currentJob = useBacktestStore((s) => s.currentJob);
  if (!currentJob) return null;

  const result = results.get(currentJob.jobId);
  if (!result) return null;

  const m = result.metrics;

  return (
    <div className="grid grid-cols-2 gap-[var(--space-3)] p-[var(--space-3)] overflow-y-auto h-full">
      <Panel title="Equity Curve" accent="bid">
        <div className="p-[var(--space-2)] text-[var(--text-muted)] text-[var(--font-size-sm)]">
          Equity curve chart — {result.equityCurve.length} data points
        </div>
      </Panel>

      <div className="flex flex-col gap-[var(--space-2)]">
        <Panel title="Key Metrics" accent="accent">
          <div className="grid grid-cols-2 gap-x-[var(--space-4)] gap-y-[var(--space-1)] p-[var(--space-2)]">
            <MetricCard label="Total Return" value={formatPct(m.totalReturn)} />
            <MetricCard label="CAGR" value={formatPct(m.cagr)} />
            <MetricCard label="Sharpe Ratio" value={m.sharpeRatio.toFixed(2)} />
            <MetricCard label="Sortino Ratio" value={m.sortinoRatio.toFixed(2)} />
            <MetricCard label="Max Drawdown" value={formatPct(m.maxDrawdown)} />
            <MetricCard label="Win Rate" value={`${(m.winRate * 100).toFixed(1)}%`} />
            <MetricCard label="Profit Factor" value={m.profitFactor.toFixed(2)} />
            <MetricCard label="Total Trades" value={String(m.totalTrades)} />
          </div>
        </Panel>
      </div>
    </div>
  );
}

export default function BacktesterPage() {
  return (
    <div className="flex h-screen bg-[var(--bg-base)] relative">
        <div className="w-[340px] border-r border-[var(--bg-border)]">
          <BacktestConfigPanel />
        </div>
        <div className="flex-1 overflow-hidden">
          <BacktestProgressOverlay />
          <BacktestResults />
        </div>
      </div>
  );
}
