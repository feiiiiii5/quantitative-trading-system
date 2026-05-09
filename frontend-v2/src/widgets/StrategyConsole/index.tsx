import { useCallback } from 'react';
import { Panel, WidgetErrorBoundary } from '@/shared/ui';
import { useStrategyStore } from '@/features/strategy-control';
import { StrategyCard } from './StrategyCard';

export function StrategyConsole() {
  const strategies = useStrategyStore((s) => s.strategies);
  const updateStatus = useStrategyStore((s) => s.updateStatus);

  const handlePause = useCallback((id: string) => updateStatus(id, 'paused'), [updateStatus]);
  const handleResume = useCallback((id: string) => updateStatus(id, 'running'), [updateStatus]);
  const handleStop = useCallback((id: string) => updateStatus(id, 'stopped'), [updateStatus]);
  const handleParams = useCallback((_id: string) => {
    // TODO: open param drawer
  }, []);

  const strategyList = Array.from(strategies.values());

  return (
    <WidgetErrorBoundary>
      <Panel title="Strategies" accent="accent">
        <div className="flex flex-col gap-[var(--space-2)] p-[var(--space-2)] overflow-y-auto h-full">
          {strategyList.length === 0 ? (
            <div className="flex items-center justify-center h-full text-[var(--text-muted)] text-[var(--font-size-sm)]">
              No strategies running
            </div>
          ) : (
            strategyList.map((strategy) => (
              <StrategyCard
                key={strategy.id}
                strategy={strategy}
                onPause={handlePause}
                onResume={handleResume}
                onStop={handleStop}
                onParams={handleParams}
              />
            ))
          )}
        </div>
      </Panel>
    </WidgetErrorBoundary>
  );
}
