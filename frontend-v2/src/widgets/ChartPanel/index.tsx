import { Panel, WidgetErrorBoundary } from '@/shared/ui';
import { TradingChart } from './TradingChart';

export function ChartPanel() {
  return (
    <WidgetErrorBoundary>
      <Panel title="Chart" accent="accent">
        <TradingChart />
      </Panel>
    </WidgetErrorBoundary>
  );
}
