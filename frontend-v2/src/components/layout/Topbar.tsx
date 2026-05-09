import { useState, useEffect } from 'react';
import { useMarketStore } from '@/stores/market';
import { formatPrice, formatPercent, priceColor } from '@/utils/format';
import type { IndexQuote } from '@/types';

interface TopbarProps {
  onSearchOpen: () => void;
}

export function Topbar({ onSearchOpen }: TopbarProps) {
  const { indices, fetchIndices } = useMarketStore();
  const [marketOpen, setMarketOpen] = useState(false);

  useEffect(() => {
    fetchIndices();
    const checkMarket = () => {
      const now = new Date();
      const t = now.getHours() * 60 + now.getMinutes();
      setMarketOpen((t >= 570 && t <= 690) || (t >= 780 && t <= 900));
    };
    checkMarket();
    const id = setInterval(checkMarket, 30000);
    return () => clearInterval(id);
  }, [fetchIndices]);

  const fallbackIndices: IndexQuote[] = [
    { name: '上证', code: 'SH', price: 0, change: 0, change_pct: 0 },
    { name: '深证', code: 'SZ', price: 0, change: 0, change_pct: 0 },
    { name: '创业板', code: 'CY', price: 0, change: 0, change_pct: 0 },
  ];

  const displayIndices = indices.length > 0 ? indices : fallbackIndices;

  return (
    <header
      className="glass-bar"
      style={{
        height: 'var(--topbar-h, 52px)',
        display: 'flex',
        alignItems: 'center',
        borderBottom: '1px solid rgba(255,255,255,0.04)',
        padding: '0 20px',
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
          fontSize: '10px',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          color: 'var(--text-secondary)',
        }}
      >
        <span
          style={{
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            background: marketOpen ? 'var(--accent)' : 'var(--text-muted)',
            animation: marketOpen ? 'pulse-dot 2s ease-in-out infinite' : 'none',
            flexShrink: 0,
          }}
        />
        <span>A股</span>
      </div>

      <div
        onClick={onSearchOpen}
        style={{
          width: '280px',
          height: '32px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '0 12px',
          marginLeft: '20px',
          background: 'rgba(255,255,255,0.03)',
          border: '1px solid rgba(255,255,255,0.06)',
          borderRadius: '8px',
          cursor: 'pointer',
          fontFamily: 'var(--font-mono)',
          fontSize: '12px',
          color: 'var(--text-muted)',
          transition: 'border-color var(--dur-fast, 160ms) var(--ease-out, ease)',
        }}
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          style={{ flexShrink: 0, opacity: 0.5 }}
        >
          <circle cx="11" cy="11" r="8" />
          <path d="M21 21l-4.35-4.35" />
        </svg>
        <span style={{ flex: 1 }}>搜索股票...</span>
        <span
          style={{
            fontSize: '10px',
            color: 'var(--text-muted)',
            border: '1px solid rgba(255,255,255,0.08)',
            padding: '1px 5px',
            borderRadius: '4px',
            lineHeight: '1.4',
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
          gap: '24px',
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
            <span style={{ color: 'var(--text-tertiary)' }}>{idx.name}</span>
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
}
