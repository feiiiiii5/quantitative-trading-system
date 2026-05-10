type MessageHandler = (data: unknown) => void;

class WSManager {
  private ws: WebSocket | null = null;
  private url = '';
  private reconnectDelay = 1000;
  private maxDelay = 30000;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private subscribers = new Map<string, Set<MessageHandler>>();
  private connected = false;
  private listeners = new Set<(connected: boolean) => void>();

  private static instance: WSManager | null = null;

  static getInstance(): WSManager {
    if (!WSManager.instance) {
      WSManager.instance = new WSManager();
    }
    return WSManager.instance;
  }

  connect(url: string): void {
    if (this.ws && this.url === url && this.ws.readyState === WebSocket.OPEN) return;
    this.url = url;
    this.cleanup();
    this.doConnect();
  }

  private doConnect(): void {
    try {
      this.ws = new WebSocket(this.url);
      this.ws.onopen = () => {
        this.connected = true;
        this.reconnectDelay = 1000;
        this.notifyConnection(true);
      };
      this.ws.onclose = () => {
        this.connected = false;
        this.notifyConnection(false);
        this.scheduleReconnect();
      };
      this.ws.onerror = () => {
        this.ws?.close();
      };
      this.ws.onmessage = (event: MessageEvent) => {
        try {
          const msg = JSON.parse(event.data as string) as { type?: string; channel?: string; [k: string]: unknown };
          const channel = msg.type ?? msg.channel ?? '';
          const handlers = this.subscribers.get(channel);
          if (handlers) {
            for (const h of handlers) h(msg);
          }
          const wildcardHandlers = this.subscribers.get('*');
          if (wildcardHandlers) {
            for (const h of wildcardHandlers) h(msg);
          }
        } catch { /* ignore non-JSON */ }
      };
    } catch { this.scheduleReconnect(); }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => {
      this.doConnect();
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxDelay);
    }, this.reconnectDelay);
  }

  subscribe(channel: string, callback: MessageHandler): () => void {
    if (!this.subscribers.has(channel)) {
      this.subscribers.set(channel, new Set());
    }
    this.subscribers.get(channel)!.add(callback);
    return () => {
      this.subscribers.get(channel)?.delete(callback);
    };
  }

  onConnectionChange(cb: (connected: boolean) => void): () => void {
    this.listeners.add(cb);
    return () => { this.listeners.delete(cb); };
  }

  send(msg: object): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  isConnected(): boolean {
    return this.connected;
  }

  private notifyConnection(v: boolean): void {
    for (const l of this.listeners) l(v);
  }

  private cleanup(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.onmessage = null;
      this.ws.close();
      this.ws = null;
    }
  }

  disconnect(): void {
    this.cleanup();
    this.connected = false;
  }
}

export const wsManager = WSManager.getInstance();
