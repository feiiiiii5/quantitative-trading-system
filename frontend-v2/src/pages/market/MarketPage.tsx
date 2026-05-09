import { useEffect, useState, useCallback, useMemo } from 'react';
import { apiGet } from '@/api/client';
import { formatPrice, formatPercent, formatVolume, formatAmount, priceColor } from '@/utils/format';
import type { StockQuote } from '@/types';

type SortKey = 'symbol' | 'name' | 'price' | 'change_pct' | 'volume' | 'amount';
type SortDir = 'asc' | 'desc';
type MarketTab = 'all' | 'sh' | 'sz' | 'cy' | 'kc';

const TABS: Array<{ key: MarketTab; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'sh', label: '沪市' },
  { key: 'sz', label: '深市' },
  { key: 'cy', label: '创业板' },
  { key: 'kc', label: '科创板' },
];

function filterByMarket(stocks: StockQuote[], tab: MarketTab): StockQuote[] {
  if (tab === 'all') return stocks;
  if (tab === 'sh') return stocks.filter(s => s.symbol.startsWith('6'));
  if (tab === 'sz') return stocks.filter(s => s.symbol.startsWith('0') || s.symbol.startsWith('3'));
  if (tab === 'cy') return stocks.filter(s => s.symbol.startsWith('3'));
  if (tab === 'kc') return stocks.filter(s => s.symbol.startsWith('688'));
  return stocks;
}

export function MarketPage() {
  const [stocks, setStocks] = useState<StockQuote[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>('symbol');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [filter, setFilter] = useState('');
  const [activeTab, setActiveTab] = useState<MarketTab>('all');
  const [watchlist, setWatchlist] = useState<Set<string>>(new Set());

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const data = await apiGet<StockQuote[]>('/market/stocks');
        setStocks(Array.isArray(data) ? data : []);
      } catch {
        setStocks([]);
      }
      setLoading(false);
    };
    load();
  }, []);

  const handleSort = useCallback((key: SortKey) => {
    setSortKey(key);
    setSortDir(d => (key === sortKey && d === 'asc' ? 'desc' : 'asc'));
  }, [sortKey]);

  const toggleWatch = useCallback((symbol: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setWatchlist(prev => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      return next;
    });
  }, []);

  const filtered = useMemo(() => {
    const byMarket = filterByMarket(stocks, activeTab);
    if (!filter) return byMarket;
    return byMarket.filter(s =>
      s.symbol.includes(filter) || s.name?.includes(filter)
    );
  }, [stocks, activeTab, filter]);

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      const av = a[sortKey] ?? 0;
      const bv = b[sortKey] ?? 0;
      if (typeof av === 'string' && typeof bv === 'string') {
        return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      return sortDir === 'asc' ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
  }, [filtered, sortKey, sortDir]);

  return (
    <div style={{
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      background: '#000000',
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        height: '48px',
        padding: '0 24px',
        borderBottom: '1px solid rgba(255,255,255,0.04)',
        background: '#050505',
        gap: '0',
        flexShrink: 0,
      }}>
        <span style={{
          fontFamily: "'Cormorant Garamond', serif",
          fontSize: '20px',
          color: '#C9A96E',
          letterSpacing: '0.02em',
          whiteSpace: 'nowrap',
          marginRight: '32px',
        }}>
          股票市场
        </span>

        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '2px',
          flex: 1,
          justifyContent: 'center',
        }}>
          {TABS.map(tab => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: '10px',
                textTransform: 'uppercase' as const,
                letterSpacing: '0.08em',
                color: activeTab === tab.key ? '#C9A96E' : '#5E5854',
                background: activeTab === tab.key ? 'rgba(201,169,110,0.08)' : 'transparent',
                border: 'none',
                borderRadius: '3px',
                padding: '5px 12px',
                cursor: 'pointer',
                transition: 'all 160ms cubic-bezier(0,0,0.2,1)',
                whiteSpace: 'nowrap',
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          marginLeft: '32px',
        }}>
          <span style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: '10px',
            color: '#3A3633',
            fontVariantNumeric: 'tabular-nums',
          }}>
            {sorted.length} ITEMS
          </span>
          <input
            value={filter}
            onChange={e => setFilter(e.target.value)}
            placeholder="FILTER..."
            style={{
              width: '200px',
              height: '28px',
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: '10px',
              textTransform: 'uppercase' as const,
              letterSpacing: '0.05em',
              color: '#F0EBE3',
              background: '#0a0a0a',
              border: '1px solid rgba(255,255,255,0.04)',
              borderRadius: '3px',
              padding: '0 10px',
              outline: 'none',
              transition: 'border-color 160ms cubic-bezier(0,0,0.2,1)',
            }}
          />
        </div>
      </div>

      <div style={{ flex: 1, overflow: 'auto' }}>
        {loading ? (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            gap: '12px',
          }}>
            <span style={{
              fontFamily: "'Cormorant Garamond', serif",
              fontSize: '48px',
              fontWeight: 300,
              color: '#C9A96E',
              lineHeight: 1,
            }}>
              Q
            </span>
            <span style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: '10px',
              color: '#3A3633',
              letterSpacing: '0.12em',
            }}>
              LOADING
            </span>
          </div>
        ) : (
          <table style={{
            width: '100%',
            borderCollapse: 'collapse',
          }}>
            <thead>
              <tr>
                {([
                  { label: 'CODE', key: 'symbol' as SortKey, width: '70px', align: 'left' as const },
                  { label: 'NAME', key: 'name' as SortKey, width: undefined, align: 'left' as const },
                  { label: 'PRICE', key: 'price' as SortKey, width: '100px', align: 'right' as const },
                  { label: 'CHANGE', key: 'change_pct' as SortKey, width: '100px', align: 'right' as const },
                  { label: 'VOLUME', key: 'volume' as SortKey, width: '110px', align: 'right' as const },
                  { label: 'AMOUNT', key: 'amount' as SortKey, width: '120px', align: 'right' as const },
                ]).map(col => (
                  <th
                    key={col.key}
                    onClick={() => handleSort(col.key)}
                    style={{
                      position: 'sticky',
                      top: 0,
                      zIndex: 1,
                      padding: '10px 12px',
                      textAlign: col.align,
                      cursor: 'pointer',
                      fontFamily: "'JetBrains Mono', monospace",
                      fontSize: '9px',
                      textTransform: 'uppercase' as const,
                      letterSpacing: '0.1em',
                      color: sortKey === col.key ? '#9B9490' : '#5E5854',
                      background: '#050505',
                      borderBottom: '1px solid rgba(255,255,255,0.06)',
                      userSelect: 'none',
                      whiteSpace: 'nowrap',
                      transition: 'color 160ms cubic-bezier(0,0,0.2,1)',
                      ...(col.width ? { width: col.width } : {}),
                    }}
                  >
                    {col.label}{sortKey === col.key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
                  </th>
                ))}
                <th style={{
                  position: 'sticky',
                  top: 0,
                  zIndex: 1,
                  width: '40px',
                  padding: '10px 0',
                  textAlign: 'center',
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: '9px',
                  textTransform: 'uppercase' as const,
                  letterSpacing: '0.1em',
                  color: '#5E5854',
                  background: '#050505',
                  borderBottom: '1px solid rgba(255,255,255,0.06)',
                }}>
                  ★
                </th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(s => (
                <tr
                  key={s.symbol}
                  style={{
                    height: '40px',
                    cursor: 'pointer',
                    borderBottom: '1px solid rgba(255,255,255,0.02)',
                    transition: 'background 280ms cubic-bezier(0,0,0.2,1)',
                  }}
                  onMouseEnter={e => {
                    e.currentTarget.style.background = 'rgba(255,255,255,0.015)';
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.background = 'transparent';
                  }}
                >
                  <td style={{
                    padding: '0 12px',
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: '11px',
                    color: '#C9A96E',
                    fontVariantNumeric: 'tabular-nums',
                    width: '70px',
                  }}>
                    {s.symbol}
                  </td>
                  <td style={{
                    padding: '0 12px',
                    fontFamily: "system sans-serif",
                    fontSize: '13px',
                    fontWeight: 500,
                    color: '#F0EBE3',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}>
                    {s.name}
                  </td>
                  <td style={{
                    padding: '0 12px',
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: '12px',
                    color: '#F0EBE3',
                    fontVariantNumeric: 'tabular-nums',
                    textAlign: 'right',
                    width: '100px',
                  }}>
                    {formatPrice(s.price)}
                  </td>
                  <td style={{
                    padding: '0 12px',
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: '12px',
                    color: priceColor(s.change_pct),
                    fontVariantNumeric: 'tabular-nums',
                    textAlign: 'right',
                    fontWeight: 500,
                    width: '100px',
                  }}>
                    {formatPercent(s.change_pct)}
                  </td>
                  <td style={{
                    padding: '0 12px',
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: '12px',
                    color: '#9B9490',
                    fontVariantNumeric: 'tabular-nums',
                    textAlign: 'right',
                    width: '110px',
                  }}>
                    {formatVolume(s.volume)}
                  </td>
                  <td style={{
                    padding: '0 12px',
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: '12px',
                    color: '#9B9490',
                    fontVariantNumeric: 'tabular-nums',
                    textAlign: 'right',
                    width: '120px',
                  }}>
                    {formatAmount(s.amount)}
                  </td>
                  <td style={{
                    padding: '0',
                    textAlign: 'center',
                    width: '40px',
                  }}>
                    <button
                      onClick={e => toggleWatch(s.symbol, e)}
                      style={{
                        background: 'none',
                        border: 'none',
                        cursor: 'pointer',
                        color: watchlist.has(s.symbol) ? '#C9A96E' : '#3A3633',
                        fontSize: '14px',
                        padding: '2px',
                        transition: 'color 160ms cubic-bezier(0,0,0.2,1)',
                        lineHeight: 1,
                      }}
                    >
                      {watchlist.has(s.symbol) ? '★' : '☆'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
