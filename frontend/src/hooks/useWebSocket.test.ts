import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useWebSocket, useWebSocketSubscription, useWsConnectionState } from './useWebSocket';

const {
  mockSubscribe,
  mockSubscribeSymbols,
  mockUnsubscribeSymbols,
  mockOnConnectionChange,
  mockIsConnected,
} = vi.hoisted(() => ({
  mockSubscribe: vi.fn(() => vi.fn()),
  mockSubscribeSymbols: vi.fn(),
  mockUnsubscribeSymbols: vi.fn(),
  mockOnConnectionChange: vi.fn(() => vi.fn()),
  mockIsConnected: vi.fn(() => false),
}));

vi.mock('@/services/websocket', () => ({
  wsManager: {
    subscribe: mockSubscribe,
    subscribeSymbols: mockSubscribeSymbols,
    unsubscribeSymbols: mockUnsubscribeSymbols,
    onConnectionChange: mockOnConnectionChange,
    isConnected: mockIsConnected,
  },
}));

describe('useWebSocket', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('calls wsManager.subscribe with channel on mount', () => {
    const handler = vi.fn();
    renderHook(() => useWebSocket('trades', handler));
    expect(mockSubscribe).toHaveBeenCalledTimes(1);
    expect(mockSubscribe).toHaveBeenCalledWith('trades', expect.any(Function));
  });

  it('unsubscribes on unmount', () => {
    const mockUnsub = vi.fn();
    mockSubscribe.mockReturnValue(mockUnsub);
    const handler = vi.fn();
    const { unmount } = renderHook(() => useWebSocket('trades', handler));
    expect(mockUnsub).not.toHaveBeenCalled();
    unmount();
    expect(mockUnsub).toHaveBeenCalledTimes(1);
  });

  it('uses stable handler ref that always calls latest handler', () => {
    const handler1 = vi.fn();
    const handler2 = vi.fn();
    const { rerender } = renderHook(
      ({ handler }) => useWebSocket('trades', handler),
      { initialProps: { handler: handler1 } },
    );
    const stableHandler = mockSubscribe.mock.calls[0][1] as (data: unknown) => void;
    stableHandler({ price: 100 });
    expect(handler1).toHaveBeenCalledWith({ price: 100 });
    rerender({ handler: handler2 });
    stableHandler({ price: 200 });
    expect(handler2).toHaveBeenCalledWith({ price: 200 });
    expect(handler1).toHaveBeenCalledTimes(1);
  });

  it('resubscribes when channel changes', () => {
    const handler = vi.fn();
    const { rerender } = renderHook(
      ({ channel }) => useWebSocket(channel, handler),
      { initialProps: { channel: 'trades' } },
    );
    expect(mockSubscribe).toHaveBeenCalledWith('trades', expect.any(Function));
    rerender({ channel: 'kline' });
    expect(mockSubscribe).toHaveBeenCalledWith('kline', expect.any(Function));
    expect(mockSubscribe).toHaveBeenCalledTimes(2);
  });
});

describe('useWebSocketSubscription', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('calls subscribeSymbols with symbols on mount', () => {
    renderHook(() => useWebSocketSubscription(['BTCUSDT', 'ETHUSDT']));
    expect(mockSubscribeSymbols).toHaveBeenCalledTimes(1);
    expect(mockSubscribeSymbols).toHaveBeenCalledWith(['BTCUSDT', 'ETHUSDT']);
  });

  it('calls unsubscribeSymbols on unmount', () => {
    const { unmount } = renderHook(() => useWebSocketSubscription(['BTCUSDT']));
    expect(mockUnsubscribeSymbols).not.toHaveBeenCalled();
    unmount();
    expect(mockUnsubscribeSymbols).toHaveBeenCalledTimes(1);
    expect(mockUnsubscribeSymbols).toHaveBeenCalledWith(['BTCUSDT']);
  });

  it('skips subscribing when symbols is empty', () => {
    renderHook(() => useWebSocketSubscription([]));
    expect(mockSubscribeSymbols).not.toHaveBeenCalled();
  });

  it('skips unsubscribing when symbols is empty on unmount', () => {
    const { unmount } = renderHook(() => useWebSocketSubscription([]));
    unmount();
    expect(mockUnsubscribeSymbols).not.toHaveBeenCalled();
  });

  it('resubscribes when symbols change', () => {
    const { rerender } = renderHook(
      ({ symbols }) => useWebSocketSubscription(symbols),
      { initialProps: { symbols: ['BTCUSDT'] } },
    );
    expect(mockSubscribeSymbols).toHaveBeenCalledWith(['BTCUSDT']);
    rerender({ symbols: ['ETHUSDT'] });
    expect(mockSubscribeSymbols).toHaveBeenCalledWith(['ETHUSDT']);
    expect(mockSubscribeSymbols).toHaveBeenCalledTimes(2);
  });
});

describe('useWsConnectionState', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns initial state from isConnected', () => {
    mockIsConnected.mockReturnValue(true);
    const { result } = renderHook(() => useWsConnectionState());
    expect(result.current).toBe(true);
  });

  it('returns false when not connected', () => {
    mockIsConnected.mockReturnValue(false);
    const { result } = renderHook(() => useWsConnectionState());
    expect(result.current).toBe(false);
  });

  it('registers connection change listener on mount', () => {
    renderHook(() => useWsConnectionState());
    expect(mockOnConnectionChange).toHaveBeenCalledTimes(1);
    expect(mockOnConnectionChange).toHaveBeenCalledWith(expect.any(Function));
  });

  it('updates state when connection change callback fires', async () => {
    mockIsConnected.mockReturnValue(false);
    let connectionCallback: ((connected: boolean) => void) | undefined;
    mockOnConnectionChange.mockImplementation((cb: (connected: boolean) => void) => {
      connectionCallback = cb;
      return vi.fn();
    });
    const { result } = renderHook(() => useWsConnectionState());
    expect(result.current).toBe(false);
    connectionCallback!(true);
    await waitFor(() => expect(result.current).toBe(true));
  });

  it('unsubscribes on unmount', () => {
    const mockUnsub = vi.fn();
    mockOnConnectionChange.mockReturnValue(mockUnsub);
    const { unmount } = renderHook(() => useWsConnectionState());
    expect(mockUnsub).not.toHaveBeenCalled();
    unmount();
    expect(mockUnsub).toHaveBeenCalledTimes(1);
  });
});
