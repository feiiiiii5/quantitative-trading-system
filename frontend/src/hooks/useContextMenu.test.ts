import { describe, it, expect, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useContextMenu } from './useContextMenu';
import type { MenuItem } from './useContextMenu';

function makeItems(data: string): MenuItem[] {
  return [
    { type: 'item', label: `Action for ${data}`, action: vi.fn() },
    { type: 'separator' },
    { type: 'item', label: 'Delete', action: vi.fn(), danger: true },
  ];
}

describe('useContextMenu', () => {
  it('returns null state initially', () => {
    const { result } = renderHook(() => useContextMenu(makeItems));
    expect(result.current.state).toBeNull();
  });

  it('onContextMenu sets state with x, y, data', () => {
    const { result } = renderHook(() => useContextMenu(makeItems));
    const fakeEvent = {
      preventDefault: vi.fn(),
      clientX: 100,
      clientY: 200,
    } as unknown as React.MouseEvent;

    act(() => {
      result.current.onContextMenu(fakeEvent, 'AAPL');
    });

    expect(result.current.state).toEqual({ x: 100, y: 200, data: 'AAPL' });
    expect(fakeEvent.preventDefault).toHaveBeenCalled();
  });

  it('close sets state to null', () => {
    const { result } = renderHook(() => useContextMenu(makeItems));
    const fakeEvent = {
      preventDefault: vi.fn(),
      clientX: 50,
      clientY: 60,
    } as unknown as React.MouseEvent;

    act(() => {
      result.current.onContextMenu(fakeEvent, 'GOOG');
    });
    expect(result.current.state).not.toBeNull();

    act(() => {
      result.current.close();
    });
    expect(result.current.state).toBeNull();
  });

  it('menuItems are derived from items callback', () => {
    const { result } = renderHook(() => useContextMenu(makeItems));

    expect(result.current.menuItems).toEqual([]);

    const fakeEvent = {
      preventDefault: vi.fn(),
      clientX: 10,
      clientY: 20,
    } as unknown as React.MouseEvent;

    act(() => {
      result.current.onContextMenu(fakeEvent, 'TSLA');
    });

    expect(result.current.menuItems).toHaveLength(3);
    expect(result.current.menuItems[0]).toEqual(
      expect.objectContaining({ label: 'Action for TSLA' }),
    );
    expect(result.current.menuItems[1]).toEqual({ type: 'separator' });
    expect(result.current.menuItems[2]).toEqual(
      expect.objectContaining({ label: 'Delete', danger: true }),
    );
  });
});
