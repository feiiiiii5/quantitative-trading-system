import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';

const STORAGE_KEY = 'quant-market-view';

describe('useMarketViewPersist', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('returns defaults when no saved state', async () => {
    vi.resetModules();
    const { useMarketViewPersist } = await import('./useMarketViewPersist');
    const { result } = renderHook(() => useMarketViewPersist());
    expect(result.current.view.sortKey).toBe('symbol');
    expect(result.current.view.sortDir).toBe('asc');
    expect(result.current.view.activeTab).toBe('all');
    expect(result.current.view.changeRangeIdx).toBe(0);
    expect(result.current.view.sectorFilter).toBe('');
    expect(result.current.view.contentTab).toBe('market');
  });

  it('loads saved state from localStorage', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      sortKey: 'change_pct',
      sortDir: 'desc',
      activeTab: 'sh',
      changeRangeIdx: 2,
      sectorFilter: '银行',
      contentTab: 'sector',
    }));
    vi.resetModules();
    const { useMarketViewPersist } = await import('./useMarketViewPersist');
    const { result } = renderHook(() => useMarketViewPersist());
    expect(result.current.view.sortKey).toBe('change_pct');
    expect(result.current.view.sortDir).toBe('desc');
    expect(result.current.view.activeTab).toBe('sh');
    expect(result.current.view.changeRangeIdx).toBe(2);
    expect(result.current.view.sectorFilter).toBe('银行');
    expect(result.current.view.contentTab).toBe('sector');
  });

  it('persists updates to localStorage', async () => {
    vi.resetModules();
    const { useMarketViewPersist } = await import('./useMarketViewPersist');
    const { result } = renderHook(() => useMarketViewPersist());

    act(() => {
      result.current.update('sortKey', 'volume');
    });

    expect(result.current.view.sortKey).toBe('volume');
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY)!);
    expect(saved.sortKey).toBe('volume');
  });

  it('handles corrupted localStorage gracefully', async () => {
    localStorage.setItem(STORAGE_KEY, 'not-json{{{');
    vi.resetModules();
    const { useMarketViewPersist } = await import('./useMarketViewPersist');
    const { result } = renderHook(() => useMarketViewPersist());
    expect(result.current.view.sortKey).toBe('symbol');
  });

  it('partial saved state merges with defaults', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ sortKey: 'price' }));
    vi.resetModules();
    const { useMarketViewPersist } = await import('./useMarketViewPersist');
    const { result } = renderHook(() => useMarketViewPersist());
    expect(result.current.view.sortKey).toBe('price');
    expect(result.current.view.sortDir).toBe('asc');
    expect(result.current.view.contentTab).toBe('market');
  });
});
