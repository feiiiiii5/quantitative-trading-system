import { useState, memo } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Button } from '@/shared/ui';
import { useStrategyStore } from '@/features/strategy-control';
import { formatAmount, formatPct } from '@/shared/lib/format';
import { cn } from '@/shared/lib/cn';

type DrawerTab = 'performance' | 'parameters' | 'trades' | 'logs';

interface StrategyDetailDrawerProps {
  strategyId: string | null;
  onClose: () => void;
}

export const StrategyDetailDrawer = memo(function StrategyDetailDrawer({
  strategyId,
  onClose,
}: StrategyDetailDrawerProps) {
  const [activeTab, setActiveTab] = useState<DrawerTab>('performance');
  const strategies = useStrategyStore((s) => s.strategies);

  const strategy = strategyId ? strategies.get(strategyId) : null;

  if (!strategy) return null;

  const TABS: Array<{ key: DrawerTab; label: string }> = [
    { key: 'performance', label: 'Performance' },
    { key: 'parameters', label: 'Parameters' },
    { key: 'trades', label: 'Trades' },
    { key: 'logs', label: 'Logs' },
  ];

  return (
    <AnimatePresence>
      <motion.div
        initial={{ x: 480 }}
        animate={{ x: 0 }}
        exit={{ x: 480 }}
        transition={{ type: 'spring', damping: 25, stiffness: 300 }}
        className="fixed top-0 right-0 w-[480px] h-screen bg-[var(--bg-surface)] border-l border-[var(--bg-border)] z-50 flex flex-col"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-[var(--space-4)] py-[var(--space-3)] border-b border-[var(--bg-border)]">
          <div>
            <h2 className="text-[var(--font-size-lg)] font-semibold text-[var(--text-primary)]">
              {strategy.name}
            </h2>
            <div className="text-[var(--font-size-xs)] text-[var(--text-muted)]">
              {strategy.symbols.join(', ')}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-[var(--text-muted)] hover:text-[var(--text-primary)] text-lg"
          >
            ✕
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-[var(--bg-border)]">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                'flex-1 py-[var(--space-2)] text-[var(--font-size-xs)] uppercase tracking-wider transition-colors',
                activeTab === tab.key
                  ? 'text-[var(--text-accent)] border-b-2 border-b-[var(--text-accent)]'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-[var(--space-3)]">
          {activeTab === 'performance' && (
            <div className="space-y-[var(--space-3)]">
              <div className="grid grid-cols-2 gap-[var(--space-2)]">
                <div className="bg-[var(--bg-elevated)] rounded-[var(--radius-md)] p-[var(--space-3)]">
                  <div className="text-[var(--font-size-xs)] text-[var(--text-muted)]">Unrealized PnL</div>
                  <div className={cn('font-mono text-[var(--font-size-lg)]', {
                    'text-[var(--color-bid)]': strategy.unrealizedPnl > 0,
                    'text-[var(--color-ask)]': strategy.unrealizedPnl < 0,
                  })}>
                    {formatAmount(strategy.unrealizedPnl)}
                  </div>
                </div>
                <div className="bg-[var(--bg-elevated)] rounded-[var(--radius-md)] p-[var(--space-3)]">
                  <div className="text-[var(--font-size-xs)] text-[var(--text-muted)]">Realized PnL</div>
                  <div className={cn('font-mono text-[var(--font-size-lg)]', {
                    'text-[var(--color-bid)]': strategy.realizedPnl > 0,
                    'text-[var(--color-ask)]': strategy.realizedPnl < 0,
                  })}>
                    {formatAmount(strategy.realizedPnl)}
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-[var(--space-2)]">
                <div className="bg-[var(--bg-elevated)] rounded-[var(--radius-md)] p-[var(--space-2)]">
                  <div className="text-[var(--font-size-xs)] text-[var(--text-muted)]">Sharpe(30d)</div>
                  <div className="font-mono text-[var(--font-size-sm)] text-[var(--text-primary)]">
                    {strategy.metrics.sharpe30d.toFixed(2)}
                  </div>
                </div>
                <div className="bg-[var(--bg-elevated)] rounded-[var(--radius-md)] p-[var(--space-2)]">
                  <div className="text-[var(--font-size-xs)] text-[var(--text-muted)]">Max DD</div>
                  <div className="font-mono text-[var(--font-size-sm)] text-[var(--color-ask)]">
                    {formatPct(strategy.metrics.maxDrawdown)}
                  </div>
                </div>
                <div className="bg-[var(--bg-elevated)] rounded-[var(--radius-md)] p-[var(--space-2)]">
                  <div className="text-[var(--font-size-xs)] text-[var(--text-muted)]">Win Rate</div>
                  <div className="font-mono text-[var(--font-size-sm)] text-[var(--text-primary)]">
                    {(strategy.metrics.winRate * 100).toFixed(1)}%
                  </div>
                </div>
              </div>
              <div className="bg-[var(--bg-elevated)] rounded-[var(--radius-md)] p-[var(--space-3)]">
                <div className="text-[var(--font-size-xs)] text-[var(--text-muted)] mb-1">Equity Curve</div>
                <div className="h-[120px] flex items-center justify-center text-[var(--text-muted)] text-[var(--font-size-xs)]">
                  {strategy.equityCurve ? `${strategy.equityCurve.length} data points` : 'No equity data'}
                </div>
              </div>
            </div>
          )}

          {activeTab === 'parameters' && (
            <div className="space-y-[var(--space-2)]">
              {Object.entries(strategy.parameters).map(([key, value]) => (
                <div key={key} className="flex items-center gap-[var(--space-2)]">
                  <label className="w-32 text-[var(--font-size-xs)] text-[var(--text-muted)] font-mono">{key}</label>
                  <input
                    type="text"
                    defaultValue={String(value)}
                    className="flex-1 h-7 px-2 bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-sm)] text-[var(--font-size-sm)] text-[var(--text-primary)] font-mono focus:outline-none focus:border-[var(--text-accent)]"
                  />
                </div>
              ))}
              <Button className="w-full mt-[var(--space-3)]">Apply Parameters</Button>
            </div>
          )}

          {activeTab === 'trades' && (
            <div className="text-[var(--text-muted)] text-[var(--font-size-sm)] text-center py-[var(--space-4)]">
              Trade history will be loaded from API
            </div>
          )}

          {activeTab === 'logs' && (
            <div className="text-[var(--text-muted)] text-[var(--font-size-sm)] text-center py-[var(--space-4)]">
              Strategy logs will stream via WebSocket
            </div>
          )}
        </div>
      </motion.div>
    </AnimatePresence>
  );
});
