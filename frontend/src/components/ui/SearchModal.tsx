import { useState, useEffect, useRef, useCallback, useMemo, memo } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiGet } from '@/api/client';
import { formatPrice, formatPercent, priceColor } from '@/utils/format';
import { useHotkeys } from '@/hooks/useHotkeys';
import { useMarketStore } from '@/stores/market';
import type { StockQuote } from '@/types';

interface SearchResult {
  symbol: string;
  name: string;
  code?: string;
  market?: string;
  sector?: string;
  price?: number;
  change_pct?: number;
}

interface SearchModalProps {
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

const MARKET_KEYS = ['a', 'hk', 'us', 'idx'] as const;
type MarketKey = (typeof MARKET_KEYS)[number];

const MARKET_STYLES: Record<MarketKey, { color: string; bg: string; label: string }> = {
  a: { color: 'var(--red)', bg: 'var(--red-soft)', label: 'A股' },
  hk: { color: 'var(--accent)', bg: 'var(--accent-soft)', label: '港股' },
  us: { color: 'var(--orange)', bg: 'var(--orange-soft)', label: '美股' },
  idx: { color: 'var(--green)', bg: 'var(--green-soft)', label: '指数' },
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

const MarketTag = memo(function MarketTag({ market, symbol }: { market?: string; symbol?: string }) {
  const s = resolveMarket(market, symbol);
  return (
    <span
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: '9px',
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        padding: '1px 6px',
        borderRadius: 'var(--r-xs)',
        background: s.bg,
        color: s.color,
      }}
    >
      {s.label}
    </span>
  );
});

function groupByMarket(results: SearchResult[]): Array<{ group: string; items: SearchResult[] }> {
  const groups = new Map<string, SearchResult[]>();
  for (const r of results) {
    const s = resolveMarket(r.market, r.symbol);
    const key = s.label;
    const existing = groups.get(key);
    if (existing) {
      existing.push(r);
    } else {
      groups.set(key, [r]);
    }
  }
  return Array.from(groups.entries()).map(([group, items]) => ({ group, items }));
}

export const SearchModal = memo(function SearchModal({ open, onClose }: SearchModalProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [loading, setLoading] = useState(false);
  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const cachedStocks = useMarketStore(s => s.stocks);

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
        const searchResults = Array.isArray(data) ? data : [];
        if (searchResults.length > 0 && cachedStocks.length > 0) {
          const priceMap = new Map<string, StockQuote>();
          for (const s of cachedStocks) {
            priceMap.set(s.symbol, s);
          }
          for (const r of searchResults) {
            const quote = priceMap.get(r.symbol);
            if (quote) {
              r.price = quote.price;
              r.change_pct = quote.change_pct;
            }
          }
        } else if (searchResults.length > 0) {
          try {
            const stocksData = await apiGet<StockQuote[]>('/market/stocks');
            if (Array.isArray(stocksData)) {
              const priceMap = new Map<string, StockQuote>();
              for (const s of stocksData) {
                priceMap.set(s.symbol, s);
              }
              for (const r of searchResults) {
                const quote = priceMap.get(r.symbol);
                if (quote) {
                  r.price = quote.price;
                  r.change_pct = quote.change_pct;
                }
              }
            }
          } catch { /* price enrichment optional */ }
        }
        setResults(searchResults);
        setSelectedIdx(0);
      } catch {
        setResults([]);
      }
      setLoading(false);
    }, 200);
    return () => clearTimeout(timer);
  }, [query]);

  const addToRecent = useCallback((symbol: string) => {
    const current = loadRecent().filter((s) => s !== symbol);
    saveRecent([symbol, ...current].slice(0, MAX_RECENT));
  }, []);

  const handleSelect = useCallback(
    (symbol: string) => {
      addToRecent(symbol);
      navigate(`/stock/${symbol}`);
      onClose();
    },
    [addToRecent, navigate, onClose],
  );

  const grouped = useMemo(
    () => results.length > 0 ? groupByMarket(results) : [],
    [results],
  );

  const flattenedItems = useMemo(() => {
    const items: Array<{ type: 'header'; group: string; flatIdx: number } | { type: 'stock'; stock: SearchResult; flatIdx: number }> = [];
    let idx = 0;
    for (const { group, items: stocks } of grouped) {
      items.push({ type: 'header', group, flatIdx: idx++ });
      for (const stock of stocks) {
        items.push({ type: 'stock', stock, flatIdx: idx++ });
      }
    }
    return items;
  }, [grouped]);

  const flatCount = results.length > 0
    ? flattenedItems.length
    : recentSearches.length;

  useHotkeys(
    open
      ? {
          escape: onClose,
          arrowdown: () => setSelectedIdx((i) => Math.min(i + 1, flatCount - 1)),
          arrowup: () => setSelectedIdx((i) => Math.max(i - 1, 0)),
          enter: () => {
            if (results.length > 0) {
              const item = flattenedItems.find(it => it.flatIdx === selectedIdx && it.type === 'stock');
              if (item && item.type === 'stock') {
                handleSelect(item.stock.symbol);
              }
            } else if (recentSearches[selectedIdx]) {
              handleSelect(recentSearches[selectedIdx]!);
            }
          },
        }
      : {},
  );

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

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        background: 'rgba(0,0,0,0.5)',
        backdropFilter: 'blur(24px)',
        WebkitBackdropFilter: 'blur(24px)',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'flex-start',
        paddingTop: '18vh',
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: '560px',
          maxHeight: '480px',
          background: 'var(--bg-elevated)',
          border: '1px solid var(--separator)',
          borderRadius: 'var(--r-xl)',
          boxShadow: 'var(--shadow-lg)',
          overflow: 'hidden',
          animation: 'search-modal-scale-in var(--dur-base) var(--ease-spring)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            height: '56px',
            display: 'flex',
            alignItems: 'center',
            padding: '0 var(--s5)',
            gap: 'var(--s3)',
            borderBottom: '1px solid var(--separator)',
          }}
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--label-tertiary)"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="11" cy="11" r="8" />
            <path d="M21 21l-4.35-4.35" />
          </svg>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索股票代码或名称..."
            style={{
              flex: 1,
              background: 'transparent',
              border: 'none',
              outline: 'none',
              boxShadow: 'none',
              fontFamily: 'var(--font-mono)',
              fontSize: '16px',
              color: 'var(--label-primary)',
              padding: 0,
            }}
          />
          {loading && (
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '9px',
                color: 'var(--accent)',
                letterSpacing: '0.08em',
                animation: 'search-modal-pulse-dot 1.2s ease-in-out infinite',
              }}
            >
              SEARCHING
            </span>
          )}
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '10px',
              color: 'var(--label-quaternary)',
              border: '1px solid var(--separator)',
              padding: '0 8px',
              borderRadius: 'var(--r-xs)',
              lineHeight: '20px',
            }}
          >
            ESC
          </span>
        </div>

        <div ref={listRef} style={{ maxHeight: '424px', overflow: 'auto' }}>
          {results.length === 0 && !query && recentSearches.length > 0 && (
            <div>
              <div
                style={{
                  padding: 'var(--s3) var(--s5) 6px',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '9px',
                  color: 'var(--label-tertiary)',
                  letterSpacing: '0.08em',
                  textTransform: 'uppercase',
                }}
              >
                RECENT
              </div>
              {recentSearches.map((sym, i) => {
                const isSel = i === selectedIdx;
                return (
                  <div
                    key={sym}
                    data-selected={isSel}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      height: '40px',
                      padding: '0 var(--s5)',
                      gap: 'var(--s3)',
                      background: isSel ? 'var(--accent-soft)' : 'transparent',
                      borderLeft: isSel ? '3px solid var(--accent)' : '3px solid transparent',
                      cursor: 'pointer',
                      transition: 'background var(--dur-fast) var(--ease-apple), border-color var(--dur-fast) var(--ease-apple)',
                    }}
                    onMouseEnter={() => setSelectedIdx(i)}
                    onClick={() => handleSelect(sym)}
                  >
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: '13px',
                        color: 'var(--accent)',
                        fontVariantNumeric: 'tabular-nums',
                      }}
                    >
                      {sym}
                    </span>
                    <span
                      style={{
                        fontFamily: 'var(--font-sans)',
                        fontSize: '11px',
                        color: 'var(--label-secondary)',
                      }}
                    >
                      最近搜索
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          {results.length === 0 && query && (
            <div
              style={{
                textAlign: 'center',
                padding: '64px 0',
                fontFamily: 'var(--font-mono)',
                fontSize: '13px',
                color: 'var(--label-quaternary)',
                letterSpacing: '0.06em',
              }}
            >
              NO RESULTS
            </div>
          )}

          {results.length === 0 && !query && recentSearches.length === 0 && (
            <div
              style={{
                textAlign: 'center',
                padding: '64px 0',
                fontFamily: 'var(--font-mono)',
                fontSize: '13px',
                color: 'var(--label-quaternary)',
                letterSpacing: '0.06em',
              }}
            >
              TYPE TO SEARCH
            </div>
          )}

          {flattenedItems.map((item) => {
            if (item.type === 'header') {
              return (
                <div key={`header-${item.group}`}>
                  <div
                    style={{
                      padding: 'var(--s3) var(--s5) 6px',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '9px',
                      color: 'var(--label-tertiary)',
                      letterSpacing: '0.08em',
                      textTransform: 'uppercase',
                      borderTop: item.flatIdx > 0 ? '1px solid var(--separator)' : 'none',
                    }}
                  >
                    {item.group}
                  </div>
                </div>
              );
            }
            const stock = item.stock;
            const hasPrice = stock.price !== undefined && stock.price > 0;
            const isSel = item.flatIdx === selectedIdx;
            return (
              <div
                key={stock.symbol}
                data-selected={isSel}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  height: '48px',
                  padding: '0 var(--s5)',
                  gap: 'var(--s3)',
                  background: isSel ? 'var(--accent-soft)' : 'transparent',
                  borderLeft: isSel ? '3px solid var(--accent)' : '3px solid transparent',
                  cursor: 'pointer',
                  transition: 'background var(--dur-fast) var(--ease-apple), border-color var(--dur-fast) var(--ease-apple)',
                }}
                onMouseEnter={() => setSelectedIdx(item.flatIdx)}
                onClick={() => handleSelect(stock.symbol)}
              >
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '13px',
                    color: 'var(--accent)',
                    width: '80px',
                    fontVariantNumeric: 'tabular-nums',
                  }}
                >
                  {stock.symbol}
                </span>
                <span
                  style={{
                    fontFamily: 'var(--font-sans)',
                    fontSize: '13px',
                    color: 'var(--label-primary)',
                    flex: 1,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {stock.name}
                </span>
                <MarketTag market={stock.market} symbol={stock.symbol} />
                {hasPrice && (
                  <>
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: '13px',
                        color: priceColor(stock.change_pct ?? 0),
                        fontVariantNumeric: 'tabular-nums',
                      }}
                    >
                      {formatPrice(stock.price!)}
                    </span>
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: '11px',
                        color: priceColor(stock.change_pct ?? 0),
                        fontVariantNumeric: 'tabular-nums',
                        width: '70px',
                        textAlign: 'right',
                      }}
                    >
                      {stock.change_pct !== undefined ? formatPercent(stock.change_pct) : ''}
                    </span>
                  </>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
});
