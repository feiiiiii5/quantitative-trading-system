import { useState, useEffect, useRef } from 'react';
import { apiGet } from '@/api/client';
import { formatPrice, formatPercent, priceColor } from '@/utils/format';

interface SearchResult {
  symbol: string;
  name: string;
  code?: string;
  market?: string;
  sector?: string;
  price?: number;
  change_pct?: number;
}

interface Props {
  open: boolean;
  onClose: () => void;
}

const ACCENT = '#C9A96E';
const ACCENT_MUTED = 'rgba(201,169,110,0.08)';
const SIGNAL_RISE = '#D4584A';
const SIGNAL_INFO = '#6B8FB5';
const SIGNAL_PURPLE = '#9B7DB8';
const TEXT_PRIMARY = '#F0EBE3';
const TEXT_TERTIARY = '#5E5854';
const TEXT_MUTED = '#3A3633';
const FONT_MONO = "'JetBrains Mono', monospace";
const FONT_SANS = 'system-ui, sans-serif';
const DUR_FAST = '160ms';
const DUR_NORMAL = '280ms';
const EASE_OUT = 'cubic-bezier(0.16,1,0.3,1)';

const MARKET_STYLES: Record<string, { color: string; bg: string; label: string }> = {
  a: { color: SIGNAL_RISE, bg: 'rgba(212,88,74,0.12)', label: 'A' },
  hk: { color: SIGNAL_INFO, bg: 'rgba(107,143,181,0.12)', label: 'HK' },
  us: { color: SIGNAL_PURPLE, bg: 'rgba(155,125,184,0.12)', label: 'US' },
};

function resolveMarket(market?: string) {
  if (!market) return null;
  const lower = market.toLowerCase();
  if (market.includes('港') || lower.includes('hk')) return MARKET_STYLES.hk;
  if (market.includes('美') || lower.includes('us')) return MARKET_STYLES.us;
  return MARKET_STYLES.a;
}

function MarketTag({ market }: { market?: string }) {
  const style = resolveMarket(market);
  if (!style) return null;
  return (
    <span style={{
      fontFamily: FONT_MONO, fontSize: '9px', textTransform: 'uppercase',
      letterSpacing: '0.05em', padding: '1px 6px', borderRadius: '2px',
      background: style.bg, color: style.color,
    }}>
      {style.label}
    </span>
  );
}

export function SearchModal({ open, onClose }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      setQuery('');
      setResults([]);
      setSelectedIdx(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  useEffect(() => {
    if (!query) {
      setResults([]);
      return;
    }
    setLoading(true);
    const timer = setTimeout(async () => {
      try {
        const data = await apiGet<SearchResult[]>('/search', { q: query });
        setResults(Array.isArray(data) ? data : []);
        setSelectedIdx(0);
      } catch {
        setResults([]);
      }
      setLoading(false);
    }, 200);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (!open) return;
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIdx((i) => Math.min(i + 1, results.length - 1));
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIdx((i) => Math.max(i - 1, 0));
      }
      if (e.key === 'Enter' && results[selectedIdx]) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [open, onClose, results.length, selectedIdx]);

  useEffect(() => {
    if (!listRef.current) return;
    const selected = listRef.current.children[selectedIdx] as HTMLElement | undefined;
    if (selected) {
      selected.scrollIntoView({ block: 'nearest' });
    }
  }, [selectedIdx]);

  useEffect(() => {
    const styleId = 'search-modal-keyframes';
    if (document.getElementById(styleId)) return;
    const sheet = document.createElement('style');
    sheet.id = styleId;
    sheet.textContent = `
      @keyframes search-modal-scale-in {
        from { transform: scale(0.96); opacity: 0; }
        to { transform: scale(1); opacity: 1; }
      }
      @keyframes search-modal-pulse-dot {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.3; }
      }
    `;
    document.head.appendChild(sheet);
    return () => {
      const el = document.getElementById(styleId);
      if (el) el.remove();
    };
  }, []);

  if (!open) return null;

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'rgba(0,0,0,0.75)',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        display: 'flex', justifyContent: 'center',
        alignItems: 'flex-start', paddingTop: '18vh',
      }}
      onClick={onClose}
    >
      <div
        ref={containerRef}
        style={{
          width: '560px', maxHeight: '480px',
          background: '#0a0a0a',
          border: '1px solid rgba(255,255,255,0.06)',
          borderRadius: '12px',
          boxShadow: '0 16px 48px rgba(0,0,0,0.6)',
          overflow: 'hidden',
          animation: `search-modal-scale-in ${DUR_NORMAL} ${EASE_OUT}`,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{
          height: '56px', display: 'flex', alignItems: 'center',
          padding: '0 20px', gap: '12px',
          borderBottom: '1px solid rgba(255,255,255,0.04)',
        }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
            stroke={TEXT_TERTIARY} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" />
            <path d="M21 21l-4.35-4.35" />
          </svg>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索股票代码或名称..."
            style={{
              flex: 1, background: 'transparent', border: 'none', outline: 'none',
              fontFamily: FONT_MONO, fontSize: '16px', color: TEXT_PRIMARY,
              padding: 0,
            }}
          />
          {loading && (
            <span style={{
              fontFamily: FONT_MONO, fontSize: '9px', color: ACCENT,
              letterSpacing: '0.08em',
              animation: 'search-modal-pulse-dot 1.2s ease-in-out infinite',
            }}>
              SEARCHING
            </span>
          )}
          <span style={{
            fontFamily: FONT_MONO, fontSize: '10px', color: TEXT_MUTED,
            border: '1px solid rgba(255,255,255,0.06)',
            padding: '0 8px', borderRadius: '3px', lineHeight: '20px',
          }}>
            ESC
          </span>
        </div>

        <div
          ref={listRef}
          style={{ maxHeight: '424px', overflow: 'auto' }}
        >
          {results.length === 0 ? (
            <div style={{
              textAlign: 'center', padding: '64px 0',
              fontFamily: FONT_MONO, fontSize: '13px',
              color: TEXT_MUTED, letterSpacing: '0.06em',
            }}>
              {query ? 'NO RESULTS' : 'TYPE TO SEARCH'}
            </div>
          ) : (
            results.map((stock, i) => {
              const hasPrice = stock.price !== undefined && stock.price > 0;
              const isSelected = i === selectedIdx;
              return (
                <div
                  key={stock.symbol}
                  style={{
                    display: 'flex', alignItems: 'center',
                    height: '48px', padding: '0 20px', gap: '12px',
                    background: isSelected
                      ? ACCENT_MUTED
                      : 'transparent',
                    borderLeft: isSelected
                      ? '2px solid #C9A96E'
                      : '2px solid transparent',
                    cursor: 'pointer',
                    transition: `background ${DUR_FAST} ${EASE_OUT}, border-color ${DUR_FAST} ${EASE_OUT}`,
                  }}
                  onMouseEnter={() => setSelectedIdx(i)}
                  onClick={() => onClose()}
                >
                  <span style={{
                    fontFamily: FONT_MONO, fontSize: '13px',
                    color: ACCENT, width: '80px',
                    fontVariantNumeric: 'tabular-nums',
                  }}>
                    {stock.symbol}
                  </span>
                  <span style={{
                    fontFamily: FONT_SANS, fontSize: '13px',
                    color: TEXT_PRIMARY, flex: 1,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {stock.name}
                  </span>
                  <MarketTag market={stock.market} />
                  {hasPrice && (
                    <>
                      <span style={{
                        fontFamily: FONT_MONO, fontSize: '13px',
                        color: priceColor(stock.change_pct ?? 0),
                        fontVariantNumeric: 'tabular-nums',
                      }}>
                        {formatPrice(stock.price!)}
                      </span>
                      <span style={{
                        fontFamily: FONT_MONO, fontSize: '11px',
                        color: priceColor(stock.change_pct ?? 0),
                        fontVariantNumeric: 'tabular-nums',
                        width: '70px', textAlign: 'right',
                      }}>
                        {stock.change_pct !== undefined ? formatPercent(stock.change_pct) : ''}
                      </span>
                    </>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
