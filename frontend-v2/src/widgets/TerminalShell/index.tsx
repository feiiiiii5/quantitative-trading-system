import { useState, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useWSStatus } from '@/app/providers';
import { useTheme } from '@/app/providers';
import { cn } from '@/shared/lib/cn';
import { Panel } from '@/shared/ui';
import { useFPSCounter } from '@/shared/hooks';
import { ChartPanel } from '@/widgets/ChartPanel';
import { OrderBookPanel } from '@/widgets/OrderBookPanel';
import { StrategyConsole } from '@/widgets/StrategyConsole';
import { RiskMonitor } from '@/widgets/RiskMonitor';
import { TradePanel } from '@/widgets/TradePanel';
import { AIAnalysis } from '@/widgets/AIAnalysis';

interface NavItem {
  path: string;
  label: string;
  icon: string;
}

const NAV_ITEMS: NavItem[] = [
  { path: '/terminal', label: 'Dashboard', icon: '◈' },
  { path: '/backtester', label: 'Backtester', icon: '⟳' },
  { path: '/strategies', label: 'Strategies', icon: '⚡' },
  { path: '/risk', label: 'Risk', icon: '⊘' },
  { path: '/settings', label: 'Settings', icon: '⚙' },
];

export function TerminalShell() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const wsStatus = useWSStatus();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const fps = useFPSCounter();

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => !prev);
  }, []);

  return (
    <div className="flex h-screen bg-[var(--bg-base)] overflow-hidden">
      <aside
        className={cn(
          'flex flex-col border-r border-[var(--bg-border)] bg-[var(--bg-surface)] transition-all duration-[var(--duration-normal)]',
          sidebarCollapsed ? 'w-12' : 'w-44'
        )}
      >
        <div className="flex items-center h-10 px-[var(--space-3)] border-b border-[var(--bg-border)]">
          <span className="text-[var(--text-accent)] font-semibold text-[var(--font-size-sm)] tracking-wider">
            {sidebarCollapsed ? 'Q' : 'QUANTCORE'}
          </span>
        </div>

        <nav className="flex-1 py-[var(--space-2)]">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.path}
              onClick={() => navigate(item.path)}
              className={cn(
                'w-full flex items-center gap-[var(--space-2)] px-[var(--space-3)] py-[var(--space-2)] text-[var(--font-size-sm)] transition-colors',
                location.pathname === item.path
                  ? 'bg-[var(--bg-highlight)] text-[var(--text-primary)] border-l-2 border-l-[var(--color-bid)]'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-highlight)]'
              )}
            >
              <span className="text-base">{item.icon}</span>
              {!sidebarCollapsed && <span>{item.label}</span>}
            </button>
          ))}
        </nav>

        <button
          onClick={toggleSidebar}
          className="flex items-center justify-center h-8 border-t border-[var(--bg-border)] text-[var(--text-muted)] hover:text-[var(--text-primary)] text-[var(--font-size-xs)]"
        >
          {sidebarCollapsed ? '→' : '←'}
        </button>
      </aside>

      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="flex items-center justify-between h-10 px-[var(--space-4)] border-b border-[var(--bg-border)] bg-[var(--bg-surface)]">
          <div className="flex items-center gap-[var(--space-4)]">
            <span className="text-[var(--font-size-xs)] text-[var(--text-muted)]">
              {new Date().toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}
            </span>
          </div>
          <div className="flex items-center gap-[var(--space-4)]">
            {import.meta.env.DEV && (
              <span className={cn('text-[var(--font-size-xs)] font-mono', {
                'text-[var(--color-bid)]': fps >= 50,
                'text-[var(--color-warning)]': fps >= 30 && fps < 50,
                'text-[var(--color-critical)]': fps < 30,
              })}>
                {fps} FPS
              </span>
            )}
            <div className="flex items-center gap-1">
              <span
                className={cn('w-1.5 h-1.5 rounded-full', {
                  'bg-[var(--color-bid)] pulse-dot': wsStatus.status === 'connected',
                  'bg-[var(--color-warning)]': wsStatus.status === 'connecting',
                  'bg-[var(--color-critical)]': wsStatus.status === 'error' || wsStatus.status === 'fatal',
                  'bg-[var(--color-neutral)]': wsStatus.status === 'disconnected',
                })}
              />
              <span className="text-[var(--font-size-xs)] text-[var(--text-muted)]">
                {wsStatus.status.toUpperCase()}
              </span>
            </div>
            <button
              onClick={toggleTheme}
              className="text-[var(--text-muted)] hover:text-[var(--text-primary)] text-[var(--font-size-xs)]"
            >
              {theme === 'dark' ? '☀' : '☾'}
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-hidden p-[var(--space-2)]">
          <div
            className="h-full grid gap-[var(--space-2)]"
            style={{
              gridTemplateColumns: '1fr 280px 320px',
              gridTemplateRows: '1fr 200px',
              gridTemplateAreas: `
                "chart orderbook strategy"
                "trades depth risk"
              `,
            }}
          >
            <div style={{ gridArea: 'chart' }}>
              <ChartPanel />
            </div>
            <div style={{ gridArea: 'orderbook' }}>
              <OrderBookPanel />
            </div>
            <div style={{ gridArea: 'strategy' }} className="flex flex-col gap-[var(--space-2)]">
              <div className="flex-1 min-h-0">
                <StrategyConsole />
              </div>
              <div className="h-[200px]">
                <AIAnalysis />
              </div>
            </div>
            <div style={{ gridArea: 'trades' }}>
              <TradePanel />
            </div>
            <div style={{ gridArea: 'depth' }}>
              <Panel title="Trade Feed" accent="neutral">
                <div className="flex items-center justify-center h-full text-[var(--text-muted)] text-[var(--font-size-sm)]">
                  Real-time trades
                </div>
              </Panel>
            </div>
            <div style={{ gridArea: 'risk' }}>
              <RiskMonitor />
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
