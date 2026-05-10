import { useState, useEffect, useCallback, memo } from 'react';
import { useMarketStore } from '@/stores/market';
import { formatPrice, formatPercent, priceColor } from '@/utils/format';
import type { IndexQuote } from '@/types';

interface TopbarProps {
  onSearchOpen: () => void;
}

const FALLBACK_INDICES: readonly IndexQuote[] = [
  { name: '上证', code: 'SH', price: 0, change: 0, change_pct: 0 },
  { name: '深证', code: 'SZ', price: 0, change: 0, change_pct: 0 },
  { name: '创业板', code: 'CY', price: 0, change: 0, change_pct: 0 },
] as const;

function isMarketOpen(): boolean {
  const now = new Date();
  const t = now.getHours() * 60 + now.getMinutes();
  return (t >= 570 && t <= 690) || (t >= 780 && t <= 900);
}

export const Topbar = memo(function Topbar({ onSearchOpen }: TopbarProps) {
  const indices = useMarketStore((s) => s.indices);
  const fetchIndices = useMarketStore((s) => s.fetchIndices);
  const [marketOpen, setMarketOpen] = useState(isMarketOpen);

  useEffect(() => {
    fetchIndices();
    const id = setInterval(() => setMarketOpen(isMarketOpen()), 30000);
    return () => clearInterval(id);
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
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontFamily: 'var(--font-mono)',
          fontSize: '11px',
          textTransform: 'uppercase' as const,
          letterSpacing: '0.06em',
          color: 'var(--label-secondary)',
        }}
      >
        <span
          style={{
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            background: marketOpen ? 'var(--green)' : 'var(--label-tertiary)',
            animation: marketOpen ? 'market-pulse 2s ease-in-out infinite' : 'none',
            flexShrink: 0,
          }}
        />
        <span>A股</span>
      </div>

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
      </div>
    </header>
  );
});
