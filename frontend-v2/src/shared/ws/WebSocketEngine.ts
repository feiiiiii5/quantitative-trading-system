type ChannelName = 'market' | 'orders' | 'system' | 'ai';

interface PollingConfig {
  url: string;
  intervalMs: number;
  enabled: boolean;
}

interface WSMessage {
  type: string;
  data: unknown;
  [key: string]: unknown;
}

interface BufferedMessage<T = unknown> {
  data: T;
  receivedAt: number;
}

type StatusCallback = (status: 'connecting' | 'connected' | 'disconnected' | 'error' | 'fatal') => void;

const VISUAL_TOPICS = /^(tick\.|orderbook\.)/;
const BUFFER_FLUSH_NON_VISUAL_MS = 50;
const MAX_BUFFER_SIZE = 500;
const HEARTBEAT_INTERVAL_MS = 15_000;
const HEARTBEAT_TIMEOUT_MS = 5_000;
const MAX_RECONNECT_ATTEMPTS = 10;

class WebSocketEngine {
  private connections = new Map<ChannelName, WebSocket>();
  private subscribers = new Map<string, Set<(data: unknown) => void>>();
  private buffers = new Map<string, BufferedMessage[]>();
  private statusCallbacks = new Set<StatusCallback>();
  private reconnectAttempts = new Map<ChannelName, number>();
  private reconnectTimers = new Map<ChannelName, ReturnType<typeof setTimeout>>();
  private heartbeatIntervals = new Map<ChannelName, ReturnType<typeof setInterval>>();
  private heartbeatTimers = new Map<ChannelName, ReturnType<typeof setTimeout>>();
  private flushRafId: number | null = null;
  private flushIntervalId: ReturnType<typeof setInterval> | null = null;
  private urls = new Map<ChannelName, string>();
  private intentionalClose = new Set<ChannelName>();
  private pollingIntervals = new Map<ChannelName, ReturnType<typeof setInterval>>();
  private pollingConfigs = new Map<ChannelName, PollingConfig>();

  connect(channel: ChannelName, url: string, polling?: PollingConfig): void {
    this.urls.set(channel, url);
    this.intentionalClose.delete(channel);
    this.reconnectAttempts.set(channel, 0);
    if (polling) {
      this.pollingConfigs.set(channel, polling);
    }
    this.doConnect(channel);
    this.startFlushLoop();
  }

  disconnect(channel: ChannelName): void {
    this.intentionalClose.add(channel);
    this.stopPolling(channel);
    this.cleanupChannel(channel);
    this.emitStatus('disconnected');
  }

  disconnectAll(): void {
    for (const ch of this.connections.keys()) {
      this.disconnect(ch);
    }
    this.stopFlushLoop();
  }

  subscribe<T>(topic: string, cb: (data: T) => void): () => void {
    if (!this.subscribers.has(topic)) {
      this.subscribers.set(topic, new Set());
    }
    const typedCb = cb as (data: unknown) => void;
    this.subscribers.get(topic)!.add(typedCb);
    return () => {
      const set = this.subscribers.get(topic);
      if (set) {
        set.delete(typedCb);
        if (set.size === 0) this.subscribers.delete(topic);
      }
    };
  }

  onStatus(cb: StatusCallback): () => void {
    this.statusCallbacks.add(cb);
    return () => { this.statusCallbacks.delete(cb); };
  }

  send(channel: ChannelName, msg: object): void {
    const ws = this.connections.get(channel);
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg));
    }
  }

  private doConnect(channel: ChannelName): void {
    const url = this.urls.get(channel);
    if (!url) return;
    this.emitStatus('connecting');
    const ws = new WebSocket(url);
    this.connections.set(channel, ws);

    ws.onopen = () => {
      this.reconnectAttempts.set(channel, 0);
      this.startHeartbeat(channel);
      this.stopPolling(channel);
      this.emitStatus('connected');
    };

    ws.onmessage = (event) => {
      this.resetHeartbeatTimeout(channel);
      try {
        const msg = JSON.parse(event.data) as WSMessage;
        if (msg.type === 'pong') return;
        this.bufferMessage(msg.type, msg.data ?? msg);
      } catch {
        // ignore parse errors
      }
    };

    ws.onclose = () => {
      this.connections.delete(channel);
      this.stopHeartbeat(channel);
      if (!this.intentionalClose.has(channel)) {
        this.startPolling(channel);
        this.scheduleReconnect(channel);
      } else {
        this.emitStatus('disconnected');
      }
    };

    ws.onerror = () => {
      this.emitStatus('error');
    };
  }

  private bufferMessage(topic: string, data: unknown): void {
    if (!this.buffers.has(topic)) {
      this.buffers.set(topic, []);
    }
    const buf = this.buffers.get(topic)!;
    buf.push({ data, receivedAt: performance.now() });
    if (buf.length > MAX_BUFFER_SIZE) {
      buf.splice(0, buf.length - MAX_BUFFER_SIZE);
      this.deliverToSubscribers('__system__', { type: 'lag', topic, droppedCount: buf.length });
    }
  }

  private flushBuffers(isVisual: boolean): void {
    const topicPattern = isVisual ? VISUAL_TOPICS : /^(?!(tick\.|orderbook\.))/;
    for (const [topic, buf] of this.buffers.entries()) {
      if (topicPattern.test(topic) === isVisual) {
        if (buf.length === 0) continue;
        const items = buf.splice(0);
        const cbs = this.subscribers.get(topic);
        if (cbs) {
          for (const item of items) {
            for (const cb of cbs) {
              try { cb(item.data); } catch { /* swallow */ }
            }
          }
        }
      }
    }
  }

  private startFlushLoop(): void {
    if (this.flushRafId !== null) return;
    const flushVisual = () => {
      this.flushBuffers(true);
      this.flushRafId = requestAnimationFrame(flushVisual);
    };
    this.flushRafId = requestAnimationFrame(flushVisual);
    this.flushIntervalId = setInterval(() => this.flushBuffers(false), BUFFER_FLUSH_NON_VISUAL_MS);
  }

  private stopFlushLoop(): void {
    if (this.flushRafId !== null) {
      cancelAnimationFrame(this.flushRafId);
      this.flushRafId = null;
    }
    if (this.flushIntervalId !== null) {
      clearInterval(this.flushIntervalId);
      this.flushIntervalId = null;
    }
  }

  private scheduleReconnect(channel: ChannelName): void {
    const attempts = (this.reconnectAttempts.get(channel) ?? 0) + 1;
    this.reconnectAttempts.set(channel, attempts);
    if (attempts > MAX_RECONNECT_ATTEMPTS) {
      this.emitStatus('fatal');
      return;
    }
    const delay = Math.min(500 * Math.pow(2, attempts - 1), 30_000);
    const timer = setTimeout(() => this.doConnect(channel), delay);
    this.reconnectTimers.set(channel, timer);
    this.emitStatus('disconnected');
  }

  private startHeartbeat(channel: ChannelName): void {
    this.stopHeartbeat(channel);
    const interval = setInterval(() => {
      const ws = this.connections.get(channel);
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }));
        const timeout = setTimeout(() => {
          ws.close();
          this.scheduleReconnect(channel);
        }, HEARTBEAT_TIMEOUT_MS);
        this.heartbeatTimers.set(channel, timeout);
      }
    }, HEARTBEAT_INTERVAL_MS);
    this.heartbeatIntervals.set(channel, interval);
  }

  private stopHeartbeat(channel: ChannelName): void {
    const interval = this.heartbeatIntervals.get(channel);
    if (interval) { clearInterval(interval); this.heartbeatIntervals.delete(channel); }
    this.resetHeartbeatTimeout(channel);
  }

  private resetHeartbeatTimeout(channel: ChannelName): void {
    const timer = this.heartbeatTimers.get(channel);
    if (timer) { clearTimeout(timer); this.heartbeatTimers.delete(channel); }
  }

  private startPolling(channel: ChannelName): void {
    const config = this.pollingConfigs.get(channel);
    if (!config?.enabled) return;
    const interval = setInterval(async () => {
      try {
        const response = await fetch(config.url);
        const data = await response.json();
        this.bufferMessage(channel, data);
      } catch {
        // polling error — silently retry next interval
      }
    }, config.intervalMs);
    this.pollingIntervals.set(channel, interval);
  }

  private stopPolling(channel: ChannelName): void {
    const interval = this.pollingIntervals.get(channel);
    if (interval) {
      clearInterval(interval);
      this.pollingIntervals.delete(channel);
    }
  }

  private cleanupChannel(channel: ChannelName): void {
    const ws = this.connections.get(channel);
    if (ws) {
      ws.onopen = null;
      ws.onclose = null;
      ws.onerror = null;
      ws.onmessage = null;
      ws.close();
      this.connections.delete(channel);
    }
    this.stopHeartbeat(channel);
    const timer = this.reconnectTimers.get(channel);
    if (timer) { clearTimeout(timer); this.reconnectTimers.delete(channel); }
  }

  private deliverToSubscribers(topic: string, data: unknown): void {
    const cbs = this.subscribers.get(topic);
    if (cbs) {
      for (const cb of cbs) {
        try { cb(data); } catch { /* swallow */ }
      }
    }
  }

  private emitStatus(status: Parameters<StatusCallback>[0]): void {
    for (const cb of this.statusCallbacks) {
      try { cb(status); } catch { /* swallow */ }
    }
  }
}

export const wsEngine = new WebSocketEngine();
export type { ChannelName, PollingConfig, StatusCallback, WSMessage };
