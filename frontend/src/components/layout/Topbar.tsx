import { useEffect, useCallback, useState, memo } from 'react';
import { useMarketStore } from '@/stores/market';
import { formatPrice, formatPercent, priceColor } from '@/utils/format';
import { MarketStatusBadge } from '@/components/MarketStatusBadge';
import { AlertNotificationPanel } from '@/components/AlertNotificationPanel';
import { ThemeToggle } from '@/components/ThemeToggle';
import { useWsConnectionState } from '@/hooks/useWebSocket';
import { useDataFreshness } from '@/hooks/useDataFreshness';
import type { IndexQuote } from '@/types';

interface TopbarProps {
  onSearchOpen: () => void;
}

const FALLBACK_INDICES: readonly IndexQuote[] = [
  { name: '上证', code: 'SH', price: 0, change: 0, change_pct: 0 },
  { name: '深证', code: 'SZ', price: 0, change: 0, change_pct: 0 },
  { name: '创业板', code: 'CY', price: 0, change: 0, change_pct: 0 },
] as const;

export const Topbar = memo(function Topbar({ onSearchOpen }: TopbarProps) {
  const indices = useMarketStore((s) => s.indices);
  const fetchIndices = useMarketStore((s) => s.fetchIndices);
  const lastDataUpdate = useMarketStore((s) => s.lastDataUpdate);
  const breadth = useMarketStore((s) => s.breadth);
  const wsConnected = useWsConnectionState();
  const freshness = useDataFreshness(lastDataUpdate);
  const [alertOpen, setAlertOpen] = useState(false);

  useEffect(() => {
    fetchIndices();
  }, [fetchIndices]);

  const handleSearchClick = useCallback(() => onSearchOpen(), [onSearchOpen]);

  const displayIndices = indices.length > 0 ? indices : [...FALLBACK_INDICES];

  return (
    <header
      style={{
        height: 'var(--topbar-h)',
        display: 'flex',
        alignItems: 'center',
        background: 'var(--bg-glass)',
        backdropFilter: 'blur(20px) saturate(180%)',
        WebkitBackdropFilter: 'blur(20px) saturate(180%)',
        borderBottom: '1px solid var(--separator)',
        padding: '0 var(--s5)',
        flexShrink: 0,
        position: 'relative',
        zIndex: 10,
      }}
    >
      <MarketStatusBadge />

      <span style={{
        display: 'flex', alignItems: 'center', gap: 4,
        fontSize: 9, fontFamily: 'var(--font-mono)', letterSpacing: '0.08em',
        color: wsConnected ? (freshness === 'fresh' ? 'var(--green)' : freshness === 'stale' ? 'var(--orange)' : 'var(--label-quaternary)') : 'var(--label-quaternary)',
      }}>
        <span style={{
          width: 5, height: 5, borderRadius: '50%',
          background: wsConnected ? (freshness === 'fresh' ? 'var(--green)' : freshness === 'stale' ? 'var(--orange)' : 'var(--label-quaternary)') : 'var(--label-quaternary)',
          boxShadow: wsConnected && freshness === 'fresh' ? '0 0 4px var(--green)' : 'none',
        }} />
        {wsConnected ? (freshness === 'fresh' ? 'LIVE' : freshness === 'stale' ? 'STALE' : 'WAIT') : 'OFFLINE'}
      </span>

      {breadth?.regime && (
        <span style={{
          fontSize: 9, fontFamily: 'var(--font-mono)', letterSpacing: '0.06em',
          padding: '2px 6px', borderRadius: 'var(--r-xs)',
          background: breadth.regime === 'BULL' ? 'rgba(52,199,89,0.15)' : breadth.regime === 'BEAR' ? 'rgba(255,69,58,0.15)' : 'rgba(255,159,10,0.12)',
          color: breadth.regime === 'BULL' ? 'var(--green)' : breadth.regime === 'BEAR' ? 'var(--red)' : 'var(--orange)',
          border: `1px solid ${breadth.regime === 'BULL' ? 'rgba(52,199,89,0.3)' : breadth.regime === 'BEAR' ? 'rgba(255,69,58,0.3)' : 'rgba(255,159,10,0.25)'}`,
        }}>
          {breadth.regime}
        </span>
      )}

      <div
        role="button"
        tabIndex={0}
        onClick={handleSearchClick}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') handleSearchClick();
        }}
        style={{
          width: '280px',
          height: '32px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '0 14px',
          marginLeft: 'var(--s5)',
          background: 'var(--bg-glass)',
          backdropFilter: 'blur(12px) saturate(150%)',
          WebkitBackdropFilter: 'blur(12px) saturate(150%)',
          border: '1px solid var(--separator)',
          borderRadius: 'var(--r-pill)',
          cursor: 'pointer',
          fontFamily: 'var(--font-mono)',
          fontSize: '12px',
          color: 'var(--label-tertiary)',
          transition: 'border-color var(--dur-fast) var(--ease-apple), background var(--dur-fast) var(--ease-apple)',
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLElement).style.borderColor = 'var(--separator-hi)';
          (e.currentTarget as HTMLElement).style.background = 'var(--bg-overlay)';
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLElement).style.borderColor = 'var(--separator)';
          (e.currentTarget as HTMLElement).style.background = 'var(--bg-glass)';
        }}
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ flexShrink: 0, opacity: 0.5 }}
        >
          <circle cx="11" cy="11" r="8" />
          <path d="M21 21l-4.35-4.35" />
        </svg>
        <span style={{ flex: 1 }}>搜索股票...</span>
        <span
          style={{
            fontSize: '10px',
            color: 'var(--label-quaternary)',
            border: '1px solid var(--separator)',
            padding: '1px 6px',
            borderRadius: 'var(--r-xs)',
            lineHeight: '1.4',
            fontFamily: 'var(--font-mono)',
          }}
        >
          ⌘K
        </span>
      </div>

      <div
        style={{
          flex: 1,
          overflow: 'hidden',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          gap: 'var(--s5)',
          fontFamily: 'var(--font-mono)',
          fontSize: '11px',
        }}
      >
        <button
          onClick={() => setAlertOpen(v => !v)}
          style={{
            background: 'none', border: '1px solid var(--separator)',
            borderRadius: 'var(--r-sm)', padding: '4px 8px',
            color: 'var(--label-tertiary)', cursor: 'pointer',
            fontSize: 13, lineHeight: 1, display: 'flex', alignItems: 'center',
          }}
        >
          🔔
        </button>
        {displayIndices.map((idx) => (
          <span
            key={idx.code || idx.name}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              whiteSpace: 'nowrap',
            }}
          >
            <span style={{ color: 'var(--label-tertiary)' }}>{idx.name}</span>
            <span
              style={{
                color: priceColor(idx.change_pct),
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {idx.price ? formatPrice(idx.price) : '—'}
            </span>
            <span
              style={{
                color: priceColor(idx.change_pct),
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {idx.change_pct !== 0 ? formatPercent(idx.change_pct) : ''}
            </span>
          </span>
        ))}
        <ThemeToggle />
      </div>
      <AlertNotificationPanel open={alertOpen} onClose={() => setAlertOpen(false)} />
    </header>
  );
});
