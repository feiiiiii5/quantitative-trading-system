import { useState } from 'react';
import { useTheme } from '@/app/providers';
import { Button } from '@/shared/ui';
import { cn } from '@/shared/lib/cn';

type SettingsTab = 'account' | 'api-keys' | 'notifications' | 'risk-limits' | 'display' | 'integrations';

const TABS: Array<{ key: SettingsTab; label: string }> = [
  { key: 'account', label: 'Account' },
  { key: 'api-keys', label: 'API Keys' },
  { key: 'notifications', label: 'Notifications' },
  { key: 'risk-limits', label: 'Risk Limits' },
  { key: 'display', label: 'Display' },
  { key: 'integrations', label: 'Integrations' },
];

const TIMEZONES = ['Asia/Shanghai', 'America/New_York', 'America/Chicago', 'America/Los_Angeles', 'Europe/London', 'Europe/Frankfurt', 'Asia/Tokyo', 'Asia/Hong_Kong'];

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<SettingsTab>('account');
  const { theme, toggleTheme } = useTheme();
  const [timezone, setTimezone] = useState('Asia/Shanghai');
  const [decimalPrecision, setDecimalPrecision] = useState(2);

  return (
      <div className="flex h-screen bg-[var(--bg-base)]">
        {/* Tab sidebar */}
        <div className="w-48 bg-[var(--bg-surface)] border-r border-[var(--bg-border)] py-[var(--space-2)]">
          <div className="px-[var(--space-3)] py-[var(--space-2)] mb-[var(--space-2)]">
            <h1 className="text-[var(--font-size-lg)] font-semibold text-[var(--text-primary)]">Settings</h1>
          </div>
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                'w-full text-left px-[var(--space-3)] py-[var(--space-2)] text-[var(--font-size-sm)] transition-colors',
                activeTab === tab.key
                  ? 'bg-[var(--bg-highlight)] text-[var(--text-primary)] border-l-2 border-l-[var(--text-accent)]'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-highlight)]'
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-[var(--space-6)]">
          <div className="max-w-2xl">
            {activeTab === 'account' && (
              <div className="space-y-[var(--space-4)]">
                <h2 className="text-[var(--font-size-xl)] font-semibold text-[var(--text-primary)]">Account</h2>
                <div className="space-y-[var(--space-3)]">
                  <div>
                    <label className="text-[var(--font-size-xs)] text-[var(--text-muted)] uppercase tracking-wider block mb-1">Email</label>
                    <input type="email" className="w-full h-8 px-3 bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-md)] text-[var(--font-size-sm)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--text-accent)]" />
                  </div>
                  <div>
                    <label className="text-[var(--font-size-xs)] text-[var(--text-muted)] uppercase tracking-wider block mb-1">Password</label>
                    <Button variant="secondary" size="sm">Change Password</Button>
                  </div>
                  <div>
                    <label className="text-[var(--font-size-xs)] text-[var(--text-muted)] uppercase tracking-wider block mb-1">Two-Factor Authentication</label>
                    <Button variant="secondary" size="sm">Enable 2FA</Button>
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'api-keys' && (
              <div className="space-y-[var(--space-4)]">
                <div className="flex items-center justify-between">
                  <h2 className="text-[var(--font-size-xl)] font-semibold text-[var(--text-primary)]">API Keys</h2>
                  <Button size="sm">+ Add Key</Button>
                </div>
                <div className="bg-[var(--bg-elevated)] rounded-[var(--radius-md)] p-[var(--space-3)] text-[var(--text-muted)] text-[var(--font-size-sm)]">
                  No API keys configured. Add an exchange API key to enable trading.
                </div>
              </div>
            )}

            {activeTab === 'notifications' && (
              <div className="space-y-[var(--space-4)]">
                <h2 className="text-[var(--font-size-xl)] font-semibold text-[var(--text-primary)]">Notifications</h2>
                {['Order fills', 'Strategy alerts', 'Risk warnings', 'System alerts', 'Price alerts'].map((item) => (
                  <div key={item} className="flex items-center justify-between py-[var(--space-2)] border-b border-[var(--bg-border)]">
                    <span className="text-[var(--font-size-sm)] text-[var(--text-primary)]">{item}</span>
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input type="checkbox" defaultChecked className="sr-only peer" />
                      <div className="w-8 h-4 bg-[var(--bg-highlight)] rounded-full peer peer-checked:bg-[var(--text-accent)] after:content-[''] after:absolute after:top-0.5 after:left-[2px] after:bg-white after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:after:translate-x-full" />
                    </label>
                  </div>
                ))}
                <div>
                  <label className="text-[var(--font-size-xs)] text-[var(--text-muted)] uppercase tracking-wider block mb-1">Browser Push Notifications</label>
                  <Button variant="secondary" size="sm">Request Permission</Button>
                </div>
              </div>
            )}

            {activeTab === 'risk-limits' && (
              <div className="space-y-[var(--space-4)]">
                <h2 className="text-[var(--font-size-xl)] font-semibold text-[var(--text-primary)]">Risk Limits</h2>
                {[
                  { label: 'Max VaR (95%)', key: 'var95', defaultValue: '50000' },
                  { label: 'Max VaR (99%)', key: 'var99', defaultValue: '100000' },
                  { label: 'Max Drawdown (%)', key: 'maxDrawdown', defaultValue: '15' },
                  { label: 'Max Position Concentration (%)', key: 'maxConcentration', defaultValue: '30' },
                ].map((item) => (
                  <div key={item.key}>
                    <label className="text-[var(--font-size-xs)] text-[var(--text-muted)] uppercase tracking-wider block mb-1">{item.label}</label>
                    <input
                      type="number"
                      defaultValue={item.defaultValue}
                      className="w-48 h-7 px-2 bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-sm)] text-[var(--font-size-sm)] text-[var(--text-primary)] font-mono focus:outline-none focus:border-[var(--text-accent)]"
                    />
                  </div>
                ))}
                <Button className="mt-[var(--space-2)]">Save Limits</Button>
              </div>
            )}

            {activeTab === 'display' && (
              <div className="space-y-[var(--space-4)]">
                <h2 className="text-[var(--font-size-xl)] font-semibold text-[var(--text-primary)]">Display</h2>
                <div>
                  <label className="text-[var(--font-size-xs)] text-[var(--text-muted)] uppercase tracking-wider block mb-1">Theme</label>
                  <div className="flex gap-2">
                    <button onClick={() => { if (theme !== 'dark') toggleTheme(); }} className={cn('px-3 py-1.5 text-[var(--font-size-sm)] rounded-[var(--radius-sm)]', theme === 'dark' ? 'bg-[var(--text-accent)] text-[var(--bg-base)]' : 'bg-[var(--bg-elevated)] text-[var(--text-muted)]')}>Dark</button>
                    <button onClick={() => { if (theme !== 'light') toggleTheme(); }} className={cn('px-3 py-1.5 text-[var(--font-size-sm)] rounded-[var(--radius-sm)]', theme === 'light' ? 'bg-[var(--text-accent)] text-[var(--bg-base)]' : 'bg-[var(--bg-elevated)] text-[var(--text-muted)]')}>Light</button>
                  </div>
                </div>
                <div>
                  <label className="text-[var(--font-size-xs)] text-[var(--text-muted)] uppercase tracking-wider block mb-1">Timezone</label>
                  <select value={timezone} onChange={(e) => setTimezone(e.target.value)} className="w-64 h-7 px-2 bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-sm)] text-[var(--font-size-sm)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--text-accent)]">
                    {TIMEZONES.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-[var(--font-size-xs)] text-[var(--text-muted)] uppercase tracking-wider block mb-1">Decimal Precision</label>
                  <select value={decimalPrecision} onChange={(e) => setDecimalPrecision(Number(e.target.value))} className="w-32 h-7 px-2 bg-[var(--bg-elevated)] border border-[var(--bg-border)] rounded-[var(--radius-sm)] text-[var(--font-size-sm)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--text-accent)]">
                    {[2, 3, 4, 6, 8].map((p) => <option key={p} value={p}>{p} decimals</option>)}
                  </select>
                </div>
              </div>
            )}

            {activeTab === 'integrations' && (
              <div className="space-y-[var(--space-4)]">
                <h2 className="text-[var(--font-size-xl)] font-semibold text-[var(--text-primary)]">Integrations</h2>
                <div className="bg-[var(--bg-elevated)] rounded-[var(--radius-md)] p-[var(--space-3)] text-[var(--text-muted)] text-[var(--font-size-sm)]">
                  No data feed integrations configured. Connect a broker to enable live trading.
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
  );
}
