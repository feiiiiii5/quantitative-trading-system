import { useState, useEffect, useRef, useCallback, useMemo, memo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useHotkeys } from '@/hooks/useHotkeys';
import { useMarketStore } from '@/stores/market';
import { useRiskStore } from '@/stores/risk';
import type { StockQuote } from '@/types';

interface Command {
  id: string;
  label: string;
  category: '导航' | '操作' | '搜索';
  keywords: string[];
  shortcut?: string;
  action: () => void;
}

interface SearchResult {
  symbol: string;
  name: string;
  price?: number;
  change_pct?: number;
}

interface CommandPaletteProps {
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
  } catch {}
}

export const CommandPalette = memo(function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const [query, setQuery] = useState('');
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const cachedStocks = useMarketStore(s => s.stocks);
  const triggerKillSwitch = useRiskStore(s => s.triggerKillSwitch);

  const commands: Command[] = useMemo(() => [
    { id: 'nav.dashboard', label: '前往 Dashboard', category: '导航', keywords: ['dashboard', '仪表盘', '首页'], shortcut: '⌘1', action: () => navigate('/') },
    { id: 'nav.market', label: '前往市场行情', category: '导航', keywords: ['market', '行情', '股票'], shortcut: '⌘2', action: () => navigate('/market') },
    { id: 'nav.strategy', label: '前往策略中心', category: '导航', keywords: ['strategy', '策略', '回测'], shortcut: '⌘3', action: () => navigate('/strategy') },
    { id: 'nav.risk', label: '前往风险管理', category: '导航', keywords: ['risk', '风险', '风控'], shortcut: '⌘4', action: () => navigate('/risk') },
    { id: 'nav.terminal', label: '前往交易终端', category: '导航', keywords: ['terminal', '交易', '下单'], shortcut: '⌘5', action: () => navigate('/terminal') },
    { id: 'act.refresh', label: '刷新全部数据', category: '操作', keywords: ['refresh', '刷新', '更新'], action: () => { queryClient.invalidateQueries(); onClose(); } },
    { id: 'act.killswitch', label: '紧急停止交易', category: '操作', keywords: ['kill', 'stop', '停止', '紧急'], action: () => { triggerKillSwitch(); onClose(); } },
  ], [navigate, queryClient, onClose, triggerKillSwitch]);

  useEffect(() => {
    if (open) {
      setQuery('');
      setSearchResults([]);
      setSelectedIdx(0);
      setRecentSearches(loadRecent());
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  useEffect(() => {
    if (!query) { setSearchResults([]); return; }
    setLoading(true);
    const ac = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`, { signal: ac.signal });
        if (!response.ok) throw new Error(`Search failed: ${response.status}`);
        const data = await response.json();
        if (!ac.signal.aborted) {
          const results = Array.isArray(data) ? data : [];
          if (results.length > 0 && cachedStocks.length > 0) {
            const priceMap = new Map(cachedStocks.map(s => [s.symbol, s]));
            for (const r of results) {
              const q = priceMap.get(r.symbol) as StockQuote | undefined;
              if (q) { r.price = q.price; r.change_pct = q.change_pct; }
            }
          }
          setSearchResults(results);
          setSelectedIdx(0);
        }
      } catch { if (!ac.signal.aborted) setSearchResults([]); }
      if (!ac.signal.aborted) setLoading(false);
    }, 200);
    return () => { clearTimeout(timer); ac.abort(); };
  }, [query, cachedStocks]);

  const addToRecent = useCallback((symbol: string) => {
    const current = loadRecent().filter(s => s !== symbol);
    saveRecent([symbol, ...current].slice(0, MAX_RECENT));
  }, []);

  const filteredItems = useMemo(() => {
    const q = query.toLowerCase().trim();
    const matchedCommands = q
      ? commands.filter(c => c.label.toLowerCase().includes(q) || c.keywords.some(k => k.includes(q)))
      : commands;
    const cmdItems = matchedCommands.map(c => ({ type: 'command' as const, data: c }));

    const searchItems = searchResults.map(s => ({
      type: 'search' as const,
      data: {
        id: `search-${s.symbol}`,
        label: `${s.symbol} ${s.name}`,
        category: '搜索' as const,
        keywords: [],
        shortcut: undefined as string | undefined,
        action: () => { addToRecent(s.symbol); navigate(`/stock/${s.symbol}`); onClose(); },
      },
    }));

    const recentItems = !query && recentSearches.length > 0
      ? recentSearches.map(sym => ({
          type: 'recent' as const,
          data: {
            id: `recent-${sym}`,
            label: sym,
            category: '搜索' as const,
            keywords: [],
            shortcut: undefined as string | undefined,
            action: () => { addToRecent(sym); navigate(`/stock/${sym}`); onClose(); },
          },
        }))
      : [];

    return [...cmdItems, ...searchItems, ...recentItems];
  }, [query, commands, searchResults, recentSearches, navigate, onClose, addToRecent]);

  const totalCount = filteredItems.length;

  const handleSelect = useCallback((idx: number) => {
    const item = filteredItems[idx];
    if (item) {
      item.data.action();
    }
  }, [filteredItems]);

  useHotkeys(open ? {
    escape: onClose,
    arrowdown: () => setSelectedIdx(i => Math.min(i + 1, totalCount - 1)),
    arrowup: () => setSelectedIdx(i => Math.max(i - 1, 0)),
    enter: () => handleSelect(selectedIdx),
  } : {});

  useEffect(() => {
    if (!listRef.current) return;
    const el = listRef.current.querySelector('[data-selected="true"]') as HTMLElement | undefined;
    el?.scrollIntoView({ block: 'nearest' });
  }, [selectedIdx]);

  useEffect(() => {
    const styleId = 'command-palette-keyframes';
    if (document.getElementById(styleId)) return;
    const sheet = document.createElement('style');
    sheet.id = styleId;
    sheet.textContent = `
      @keyframes command-palette-scale-in {
        from { transform: scale(0.96); opacity: 0; }
        to { transform: scale(1); opacity: 1; }
      }
      @keyframes command-palette-pulse-dot {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.3; }
      }
    `;
    document.head.appendChild(sheet);
  }, []);

  if (!open) return null;

  const groupedItems: Array<{ type: 'header'; label: string } | { type: 'item'; item: typeof filteredItems[number]; idx: number }> = [];
  let lastCategory = '';
  for (const [i, item] of filteredItems.entries()) {
    const cat = item.data.category;
    if (cat !== lastCategory) {
      groupedItems.push({ type: 'header', label: cat });
      lastCategory = cat;
    }
    groupedItems.push({ type: 'item', item, idx: i });
  }

  return (
    <div
      style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(24px)', WebkitBackdropFilter: 'blur(24px)', display: 'flex', justifyContent: 'center', alignItems: 'flex-start', paddingTop: '18vh' }}
      onClick={onClose}
    >
      <div
        style={{ width: '560px', maxHeight: '480px', background: 'var(--bg-elevated)', border: '1px solid var(--separator)', borderRadius: 'var(--r-xl)', boxShadow: 'var(--shadow-lg)', overflow: 'hidden', animation: 'command-palette-scale-in var(--dur-base) var(--ease-spring)' }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ height: '56px', display: 'flex', alignItems: 'center', padding: '0 var(--s5)', gap: 'var(--s3)', borderBottom: '1px solid var(--separator)' }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--label-tertiary)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
          </svg>
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="搜索股票、命令或操作..."
            style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', boxShadow: 'none', fontFamily: 'var(--font-mono)', fontSize: '16px', color: 'var(--label-primary)', padding: 0 }}
          />
          {loading && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--accent)', letterSpacing: '0.08em', animation: 'command-palette-pulse-dot 1.2s ease-in-out infinite' }}>SEARCHING</span>}
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-quaternary)', border: '1px solid var(--separator)', padding: '0 8px', borderRadius: 'var(--r-xs)', lineHeight: '20px' }}>ESC</span>
        </div>
        <div ref={listRef} style={{ maxHeight: '424px', overflow: 'auto' }}>
          {filteredItems.length === 0 && query && (
            <div style={{ textAlign: 'center', padding: '64px 0', fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--label-quaternary)', letterSpacing: '0.06em' }}>NO RESULTS</div>
          )}
          {filteredItems.length === 0 && !query && recentSearches.length === 0 && (
            <div style={{ textAlign: 'center', padding: '64px 0', fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--label-quaternary)', letterSpacing: '0.06em' }}>TYPE TO SEARCH</div>
          )}
          {groupedItems.map((entry, gi) => {
            if (entry.type === 'header') {
              return (
                <div key={`header-${gi}`}>
                  <div style={{ padding: 'var(--s3) var(--s5) 6px', fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-tertiary)', letterSpacing: '0.08em', textTransform: 'uppercase', borderTop: gi > 0 ? '1px solid var(--separator)' : 'none' }}>
                    {entry.label}
                  </div>
                </div>
              );
            }
            const { item, idx } = entry;
            const isSel = idx === selectedIdx;
            const cmd = item.data;
            const catColor = cmd.category === '操作' ? 'var(--orange)' : cmd.category === '导航' ? 'var(--accent)' : 'var(--green)';
            return (
              <div
                key={cmd.id}
                data-selected={isSel}
                onClick={() => handleSelect(idx)}
                onMouseEnter={() => setSelectedIdx(idx)}
                style={{
                  display: 'flex', alignItems: 'center', height: 44, padding: '0 var(--s5)', gap: 'var(--s3)',
                  background: isSel ? 'var(--accent-soft)' : 'transparent',
                  borderLeft: isSel ? '3px solid var(--accent)' : '3px solid transparent',
                  cursor: 'pointer', transition: 'background var(--dur-fast) var(--ease-apple), border-color var(--dur-fast) var(--ease-apple)',
                }}
              >
                <span style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: catColor, background: `${catColor}18`, padding: '1px 6px', borderRadius: 'var(--r-xs)', letterSpacing: '0.05em' }}>{cmd.category}</span>
                <span style={{ flex: 1, fontFamily: 'var(--font-sans)', fontSize: 13, color: 'var(--label-primary)' }}>{cmd.label}</span>
                {cmd.shortcut && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-quaternary)', border: '1px solid var(--separator)', padding: '0 6px', borderRadius: 'var(--r-xs)', lineHeight: '18px' }}>{cmd.shortcut}</span>}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
});
