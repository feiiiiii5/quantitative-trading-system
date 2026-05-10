import { useState, useEffect, useRef, useCallback } from 'react';
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

const RECENT_KEY = 'qc_recent_searches';
const MAX_RECENT = 5;

function loadRecent(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveRecent(symbols: string[]) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(symbols.slice(0, MAX_RECENT)));
  } catch { /* silent */ }
}

const ACCENT = '#C9A96E';
const ACCENT_MUTED = 'rgba(201,169,110,0.08)';
const SIGNAL_RISE = '#D4584A';
const SIGNAL_INFO = '#6B8FB5';
const SIGNAL_PURPLE = '#9B7DB8';
const SIGNAL_TEAL = '#5BA8A0';
const TEXT_PRIMARY = '#F0EBE3';
const TEXT_SECONDARY = '#9B9490';
const TEXT_TERTIARY = '#5E5854';
const TEXT_MUTED = '#3A3633';
const FONT_MONO = "'JetBrains Mono', monospace";
const FONT_SANS = 'system-ui, sans-serif';
const DUR_FAST = '160ms';
const DUR_NORMAL = '280ms';
const EASE_OUT = 'cubic-bezier(0.16,1,0.3,1)';

const MARKET_KEYS = ['a', 'hk', 'us', 'idx'] as const;
type MarketKey = typeof MARKET_KEYS[number];

const MARKET_STYLES: Record<MarketKey, { color: string; bg: string; label: string }> = {
  a: { color: SIGNAL_RISE, bg: 'rgba(212,88,74,0.12)', label: 'A股' },
  hk: { color: SIGNAL_INFO, bg: 'rgba(107,143,181,0.12)', label: '港股' },
  us: { color: SIGNAL_PURPLE, bg: 'rgba(155,125,184,0.12)', label: '美股' },
  idx: { color: SIGNAL_TEAL, bg: 'rgba(91,168,160,0.12)', label: '指数' },
};

function resolveMarket(market?: string, symbol?: string): { color: string; bg: string; label: string } {
  if (!market && symbol) {
    if (/^(sh|sz)\d+$/i.test(symbol) || /^\d{6}$/.test(symbol)) return MARKET_STYLES.a;
    if (/^\d{5}$/.test(symbol)) return MARKET_STYLES.hk;
    if (/^[A-Z]+$/.test(symbol)) return MARKET_STYLES.us;
    return MARKET_STYLES.a;
  }
  if (!market) return MARKET_STYLES.a;
  const lower = market.toLowerCase();
  if (market.includes('港') || lower.includes('hk')) return MARKET_STYLES.hk;
  if (market.includes('美') || lower.includes('us')) return MARKET_STYLES.us;
  if (market.includes('指') || lower.includes('index') || lower.includes('idx')) return MARKET_STYLES.idx;
  return MARKET_STYLES.a;
}

function MarketTag({ market, symbol }: { market?: string; symbol?: string }) {
  const style = resolveMarket(market, symbol);
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

function groupByMarket(results: SearchResult[]): Array<{ group: string; items: SearchResult[] }> {
  const groups = new Map<string, SearchResult[]>();
  for (const r of results) {
    const style = resolveMarket(r.market, r.symbol);
    const key = style.label;
    const existing = groups.get(key);
    if (existing) {
      existing.push(r);
    } else {
      groups.set(key, [r]);
    }
  }
  return Array.from(groups.entries()).map(([group, items]) => ({ group, items }));
}

export function SearchModal({ open, onClose }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [loading, setLoading] = useState(false);
  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      setQuery('');
      setResults([]);
      setSelectedIdx(0);
      setRecentSearches(loadRecent());
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

  const addToRecent = useCallback((symbol: string) => {
    const current = loadRecent().filter(s => s !== symbol);
    const updated = [symbol, ...current].slice(0, MAX_RECENT);
    saveRecent(updated);
  }, []);

  const handleSelect = useCallback((symbol: string) => {
    addToRecent(symbol);
    onClose();
  }, [addToRecent, onClose]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (!open) return;
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      const flatCount = results.length > 0 ? results.length + groupByMarket(results).length : recentSearches.length;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIdx(i => Math.min(i + 1, flatCount - 1));
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIdx(i => Math.max(i - 1, 0));
      }
      if (e.key === 'Enter') {
        const grouped = groupByMarket(results);
        const offset = grouped.length;
        if (results.length > 0 && results[selectedIdx - offset]) {
          handleSelect(results[selectedIdx - offset]!.symbol);
        } else if (recentSearches[selectedIdx]) {
          setQuery(recentSearches[selectedIdx]!);
        }
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [open, onClose, results, selectedIdx, recentSearches, handleSelect]);

  useEffect(() => {
    if (!listRef.current) return;
    const selected = listRef.current.querySelector('[data-selected="true"]') as HTMLElement | undefined;
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
  }, []);

  if (!open) return null;

  const grouped = results.length > 0 ? groupByMarket(results) : [];
  let flatIdx = 0;

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
        onClick={e => e.stopPropagation()}
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
            onChange={e => setQuery(e.target.value)}
            placeholder="搜索股票代码或名称..."
            style={{
              flex: 1, background: 'transparent', border: 'none', outline: 'none',
              fontFamily: FONT_MONO, fontSize: '16px', color: TEXT_PRIMARY, padding: 0,
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

        <div ref={listRef} style={{ maxHeight: '424px', overflow: 'auto' }}>
          {results.length === 0 && !query && recentSearches.length > 0 && (
            <div>
              <div style={{
                padding: '12px 20px 6px', fontFamily: FONT_MONO, fontSize: '9px',
                color: TEXT_TERTIARY, letterSpacing: '0.08em', textTransform: 'uppercase',
              }}>
                RECENT
              </div>
              {recentSearches.map((sym, i) => {
                const isSel = i === selectedIdx;
                return (
                  <div
                    key={sym}
                    data-selected={isSel}
                    style={{
                      display: 'flex', alignItems: 'center',
                      height: '40px', padding: '0 20px', gap: '12px',
                      background: isSel ? ACCENT_MUTED : 'transparent',
                      borderLeft: isSel ? '2px solid #C9A96E' : '2px solid transparent',
                      cursor: 'pointer',
                      transition: `background ${DUR_FAST} ${EASE_OUT}`,
                    }}
                    onMouseEnter={() => setSelectedIdx(i)}
                    onClick={() => setQuery(sym)}
                  >
                    <span style={{ fontFamily: FONT_MONO, fontSize: '13px', color: ACCENT, fontVariantNumeric: 'tabular-nums' }}>{sym}</span>
                    <span style={{ fontFamily: FONT_SANS, fontSize: '11px', color: TEXT_SECONDARY }}>最近搜索</span>
                  </div>
                );
              })}
            </div>
          )}

          {results.length === 0 && query && (
            <div style={{
              textAlign: 'center', padding: '64px 0',
              fontFamily: FONT_MONO, fontSize: '13px',
              color: TEXT_MUTED, letterSpacing: '0.06em',
            }}>
              NO RESULTS
            </div>
          )}

          {results.length === 0 && !query && recentSearches.length === 0 && (
            <div style={{
              textAlign: 'center', padding: '64px 0',
              fontFamily: FONT_MONO, fontSize: '13px',
              color: TEXT_MUTED, letterSpacing: '0.06em',
            }}>
              TYPE TO SEARCH
            </div>
          )}

          {grouped.map(({ group, items }) => (
            <div key={group}>
              <div style={{
                padding: '12px 20px 6px', fontFamily: FONT_MONO, fontSize: '9px',
                color: TEXT_TERTIARY, letterSpacing: '0.08em', textTransform: 'uppercase',
                borderTop: flatIdx > 0 ? '1px solid rgba(255,255,255,0.03)' : 'none',
              }}>
                {group}
              </div>
              {items.map(stock => {
                const currentIdx = flatIdx++;
                const hasPrice = stock.price !== undefined && stock.price > 0;
                const isSel = currentIdx === selectedIdx;
                return (
                  <div
                    key={stock.symbol}
                    data-selected={isSel}
                    style={{
                      display: 'flex', alignItems: 'center',
                      height: '48px', padding: '0 20px', gap: '12px',
                      background: isSel ? ACCENT_MUTED : 'transparent',
                      borderLeft: isSel ? '2px solid #C9A96E' : '2px solid transparent',
                      cursor: 'pointer',
                      transition: `background ${DUR_FAST} ${EASE_OUT}, border-color ${DUR_FAST} ${EASE_OUT}`,
                    }}
                    onMouseEnter={() => setSelectedIdx(currentIdx)}
                    onClick={() => handleSelect(stock.symbol)}
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
                    <MarketTag market={stock.market} symbol={stock.symbol} />
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
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
