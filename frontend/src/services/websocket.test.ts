import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { wsManager } from './websocket';

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static readonly OPEN = 1;
  static readonly CLOSED = 3;
  static readonly CONNECTING = 0;
  static readonly CLOSING = 2;

  url: string;
  readyState: number = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  sent: string[] = [];

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
  }

  simulateOpen(): void {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  simulateClose(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  }

  simulateError(): void {
    this.onerror?.(new Event('error'));
  }

  simulateMessage(data: unknown): void {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }
}

function getLatestMock(): MockWebSocket {
  return MockWebSocket.instances[MockWebSocket.instances.length - 1];
}

vi.stubGlobal('WebSocket', MockWebSocket);

describe('WSManager', () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    wsManager.disconnect();
    wsManager.unsubscribeSymbols(wsManager.getSubscribedSymbols());
    vi.useFakeTimers();
  });

  afterEach(() => {
    wsManager.disconnect();
    vi.useRealTimers();
  });

  describe('connect()', () => {
    it('creates WebSocket with correct URL', () => {
      wsManager.connect('ws://localhost:8080');
      expect(MockWebSocket.instances).toHaveLength(1);
      expect(MockWebSocket.instances[0].url).toBe('ws://localhost:8080');
    });

    it('skips if already connected to same URL', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      wsManager.connect('ws://localhost:8080');
      expect(MockWebSocket.instances).toHaveLength(1);
    });

    it('reconnects to a different URL', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      wsManager.connect('ws://localhost:9090');
      expect(MockWebSocket.instances).toHaveLength(2);
      expect(MockWebSocket.instances[1].url).toBe('ws://localhost:9090');
    });

    it('cleans up previous connection before creating new one', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      const firstWs = getLatestMock();
      wsManager.connect('ws://localhost:9090');
      expect(firstWs.onopen).toBeNull();
      expect(firstWs.onclose).toBeNull();
      expect(firstWs.onerror).toBeNull();
      expect(firstWs.onmessage).toBeNull();
    });
  });

  describe('subscribe()', () => {
    it('adds handler and dispatches messages to it', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      const handler = vi.fn();
      wsManager.subscribe('ticker', handler);
      getLatestMock().simulateMessage({ type: 'ticker', price: 100 });
      expect(handler).toHaveBeenCalledWith({ type: 'ticker', price: 100 });
    });

    it('returns unsubscribe function that removes handler', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      const handler = vi.fn();
      const unsub = wsManager.subscribe('ticker', handler);
      unsub();
      getLatestMock().simulateMessage({ type: 'ticker', price: 100 });
      expect(handler).not.toHaveBeenCalled();
    });

    it('supports wildcard channel', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      const handler = vi.fn();
      wsManager.subscribe('*', handler);
      getLatestMock().simulateMessage({ type: 'ticker', price: 100 });
      expect(handler).toHaveBeenCalledWith({ type: 'ticker', price: 100 });
    });

    it('uses channel field as fallback', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      const handler = vi.fn();
      wsManager.subscribe('trade', handler);
      getLatestMock().simulateMessage({ channel: 'trade', amount: 5 });
      expect(handler).toHaveBeenCalledWith({ channel: 'trade', amount: 5 });
    });

    it('does not dispatch to handlers of other channels', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      const handler = vi.fn();
      wsManager.subscribe('ticker', handler);
      getLatestMock().simulateMessage({ type: 'orderbook', depth: 10 });
      expect(handler).not.toHaveBeenCalled();
    });

    it('ignores non-JSON messages without throwing', () => {
      wsManager.connect('ws://localhost:8080');
      const mock = getLatestMock();
      mock.simulateOpen();
      const handler = vi.fn();
      wsManager.subscribe('ticker', handler);
      expect(() => {
        mock.onmessage?.({ data: 'not-json' } as MessageEvent);
      }).not.toThrow();
      expect(handler).not.toHaveBeenCalled();
    });
  });

  describe('subscribeSymbols()', () => {
    it('adds symbols to pending subscriptions', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      wsManager.subscribeSymbols(['AAPL', 'GOOG']);
      expect(wsManager.getSubscribedSymbols()).toEqual(expect.arrayContaining(['AAPL', 'GOOG']));
    });

    it('sends subscribe message if WS is open', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      wsManager.subscribeSymbols(['AAPL']);
      expect(getLatestMock().sent).toContainEqual(
        JSON.stringify({ type: 'subscribe', symbols: ['AAPL'] }),
      );
    });

    it('does not send subscribe message if WS is not open', () => {
      wsManager.connect('ws://localhost:8080');
      wsManager.subscribeSymbols(['AAPL']);
      expect(getLatestMock().sent).toHaveLength(0);
    });

    it('deduplicates symbols', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      wsManager.subscribeSymbols(['AAPL']);
      wsManager.subscribeSymbols(['AAPL', 'GOOG']);
      expect(wsManager.getSubscribedSymbols()).toEqual(expect.arrayContaining(['AAPL', 'GOOG']));
      expect(wsManager.getSubscribedSymbols().filter(s => s === 'AAPL')).toHaveLength(1);
    });
  });

  describe('unsubscribeSymbols()', () => {
    it('removes symbols from pending subscriptions', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      wsManager.subscribeSymbols(['AAPL', 'GOOG']);
      wsManager.unsubscribeSymbols(['AAPL']);
      expect(wsManager.getSubscribedSymbols()).toEqual(['GOOG']);
    });

    it('sends unsubscribe message if WS is open', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      wsManager.subscribeSymbols(['AAPL', 'GOOG']);
      wsManager.unsubscribeSymbols(['AAPL']);
      expect(getLatestMock().sent).toContainEqual(
        JSON.stringify({ type: 'unsubscribe', symbols: ['AAPL'] }),
      );
    });

    it('does not send unsubscribe message if WS is not open', () => {
      wsManager.connect('ws://localhost:8080');
      const mock = getLatestMock();
      mock.simulateOpen();
      wsManager.subscribeSymbols(['AAPL']);
      mock.readyState = MockWebSocket.CLOSED;
      wsManager.unsubscribeSymbols(['AAPL']);
      const unsubscribeMessages = mock.sent.filter(s => {
        try {
          return JSON.parse(s).type === 'unsubscribe';
        } catch { return false; }
      });
      expect(unsubscribeMessages).toHaveLength(0);
    });
  });

  describe('flushPendingSubscriptions()', () => {
    it('auto-sends subscribe for all pending symbols on open', () => {
      wsManager.connect('ws://localhost:8080');
      wsManager.subscribeSymbols(['AAPL', 'GOOG']);
      expect(getLatestMock().sent).toHaveLength(0);
      getLatestMock().simulateOpen();
      const flushMessage = getLatestMock().sent.find(s => {
        try {
          const parsed = JSON.parse(s);
          return parsed.type === 'subscribe' && parsed.symbols.length === 2;
        } catch { return false; }
      });
      expect(flushMessage).toBeDefined();
      const parsed = JSON.parse(flushMessage!);
      expect(parsed.symbols).toEqual(expect.arrayContaining(['AAPL', 'GOOG']));
    });

    it('does not send subscribe if no pending symbols', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      const subscribeMessages = getLatestMock().sent.filter(s => {
        try {
          return JSON.parse(s).type === 'subscribe';
        } catch { return false; }
      });
      expect(subscribeMessages).toHaveLength(0);
    });
  });

  describe('onConnectionChange()', () => {
    it('fires callback with true on connect', () => {
      const cb = vi.fn();
      wsManager.onConnectionChange(cb);
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      expect(cb).toHaveBeenCalledWith(true);
    });

    it('fires callback with false on disconnect', () => {
      const cb = vi.fn();
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      wsManager.onConnectionChange(cb);
      getLatestMock().simulateClose();
      expect(cb).toHaveBeenCalledWith(false);
    });

    it('returns unsubscribe function', () => {
      const cb = vi.fn();
      const unsub = wsManager.onConnectionChange(cb);
      unsub();
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      expect(cb).not.toHaveBeenCalled();
    });

    it('fires for multiple listeners', () => {
      const cb1 = vi.fn();
      const cb2 = vi.fn();
      wsManager.onConnectionChange(cb1);
      wsManager.onConnectionChange(cb2);
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      expect(cb1).toHaveBeenCalledWith(true);
      expect(cb2).toHaveBeenCalledWith(true);
    });
  });

  describe('isConnected() / getSubscribedSymbols()', () => {
    it('isConnected returns false initially', () => {
      expect(wsManager.isConnected()).toBe(false);
    });

    it('isConnected returns true after open', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      expect(wsManager.isConnected()).toBe(true);
    });

    it('isConnected returns false after close', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      getLatestMock().simulateClose();
      expect(wsManager.isConnected()).toBe(false);
    });

    it('getSubscribedSymbols returns empty array initially', () => {
      expect(wsManager.getSubscribedSymbols()).toEqual([]);
    });

    it('getSubscribedSymbols returns subscribed symbols', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      wsManager.subscribeSymbols(['AAPL']);
      expect(wsManager.getSubscribedSymbols()).toEqual(['AAPL']);
    });
  });

  describe('disconnect()', () => {
    it('cleans up WebSocket and clears connected state', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      expect(wsManager.isConnected()).toBe(true);
      wsManager.disconnect();
      expect(wsManager.isConnected()).toBe(false);
    });

    it('clears reconnect timer', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      getLatestMock().simulateClose();
      wsManager.disconnect();
      const instancesBefore = MockWebSocket.instances.length;
      vi.advanceTimersByTime(60000);
      expect(MockWebSocket.instances).toHaveLength(instancesBefore);
    });

    it('nullifies WebSocket event handlers', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      const capturedWs = getLatestMock();
      wsManager.disconnect();
      expect(capturedWs.onopen).toBeNull();
      expect(capturedWs.onclose).toBeNull();
      expect(capturedWs.onerror).toBeNull();
      expect(capturedWs.onmessage).toBeNull();
    });
  });

  describe('auto-reconnect with exponential backoff', () => {
    it('schedules reconnect after close', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      getLatestMock().simulateClose();
      expect(MockWebSocket.instances).toHaveLength(1);
      vi.advanceTimersByTime(1000);
      expect(MockWebSocket.instances).toHaveLength(2);
    });

    it('doubles delay on each reconnect attempt', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      getLatestMock().simulateClose();
      vi.advanceTimersByTime(1000);
      expect(MockWebSocket.instances).toHaveLength(2);
      getLatestMock().simulateClose();
      vi.advanceTimersByTime(1000);
      expect(MockWebSocket.instances).toHaveLength(2);
      vi.advanceTimersByTime(1000);
      expect(MockWebSocket.instances).toHaveLength(3);
    });

    it('caps delay at maxDelay (30s)', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      getLatestMock().simulateClose();
      vi.advanceTimersByTime(1000);
      getLatestMock().simulateClose();
      vi.advanceTimersByTime(2000);
      getLatestMock().simulateClose();
      vi.advanceTimersByTime(4000);
      getLatestMock().simulateClose();
      vi.advanceTimersByTime(8000);
      getLatestMock().simulateClose();
      vi.advanceTimersByTime(16000);
      getLatestMock().simulateClose();
      vi.advanceTimersByTime(30000);
      expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(7);
    });

    it('resets delay on successful connection', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      getLatestMock().simulateClose();
      vi.advanceTimersByTime(1000);
      expect(MockWebSocket.instances).toHaveLength(2);
      getLatestMock().simulateOpen();
      getLatestMock().simulateClose();
      vi.advanceTimersByTime(1000);
      expect(MockWebSocket.instances).toHaveLength(3);
    });

    it('reconnects on error by closing the socket', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      getLatestMock().simulateError();
      expect(getLatestMock().readyState).toBe(MockWebSocket.CLOSED);
    });

    it('cancels reconnect timer on explicit disconnect', () => {
      wsManager.connect('ws://localhost:8080');
      getLatestMock().simulateOpen();
      getLatestMock().simulateClose();
      wsManager.disconnect();
      const countBefore = MockWebSocket.instances.length;
      vi.advanceTimersByTime(60000);
      expect(MockWebSocket.instances).toHaveLength(countBefore);
    });
  });
});
