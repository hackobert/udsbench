/** WebSocket-Client mit automatischem Reconnect (exponentielles Backoff). */

export type WsState = "connecting" | "open" | "closed";

export interface WsHandlers {
  onMessage: (data: unknown) => void;
  onOpen?: () => void;
  onClose?: (code: number) => void;
  onStateChange?: (state: WsState) => void;
}

export interface WsOptions {
  minDelayMs?: number;
  maxDelayMs?: number;
  /** Für Tests injizierbar. */
  WebSocketImpl?: typeof WebSocket;
}

/** Close-Code des Backends bei fehlendem/ungültigem Token. */
export const WS_UNAUTHORIZED = 4401;

export class ReconnectingSocket {
  private ws: WebSocket | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private attempts = 0;
  private stopped = false;
  private readonly minDelay: number;
  private readonly maxDelay: number;
  private readonly Impl: typeof WebSocket;
  state: WsState = "closed";

  constructor(
    private readonly urlFactory: () => string,
    private readonly handlers: WsHandlers,
    opts: WsOptions = {},
  ) {
    this.minDelay = opts.minDelayMs ?? 500;
    this.maxDelay = opts.maxDelayMs ?? 10000;
    this.Impl = opts.WebSocketImpl ?? WebSocket;
  }

  start(): void {
    this.stopped = false;
    this.connect();
  }

  /** Nächste Wartezeit (exportiert für Tests). */
  nextDelay(): number {
    return Math.min(this.maxDelay, this.minDelay * 2 ** Math.min(this.attempts, 10));
  }

  private setState(s: WsState): void {
    this.state = s;
    this.handlers.onStateChange?.(s);
  }

  private connect(): void {
    if (this.stopped) return;
    this.setState("connecting");
    let ws: WebSocket;
    try {
      ws = new this.Impl(this.urlFactory());
    } catch {
      this.schedule();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this.attempts = 0;
      this.setState("open");
      this.handlers.onOpen?.();
    };
    ws.onmessage = (ev: MessageEvent) => {
      let data: unknown;
      try {
        data = JSON.parse(String(ev.data));
      } catch {
        return;
      }
      this.handlers.onMessage(data);
    };
    ws.onclose = (ev: CloseEvent) => {
      this.ws = null;
      this.setState("closed");
      this.handlers.onClose?.(ev.code);
      if (ev.code === WS_UNAUTHORIZED) this.attempts = Math.max(this.attempts, 4);
      this.schedule();
    };
    ws.onerror = () => {
      /* onclose folgt */
    };
  }

  private schedule(): void {
    if (this.stopped || this.timer) return;
    const delay = this.nextDelay();
    this.attempts++;
    this.timer = setTimeout(() => {
      this.timer = null;
      this.connect();
    }, delay);
  }

  /** Sofort neu verbinden (z. B. nach Token-Änderung). */
  reconnect(): void {
    this.attempts = 0;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    if (this.ws) {
      const old = this.ws;
      this.ws = null;
      old.onclose = null;
      old.close();
    }
    this.connect();
  }

  send(obj: unknown): boolean {
    if (this.ws && this.ws.readyState === 1) {
      this.ws.send(JSON.stringify(obj));
      return true;
    }
    return false;
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    this.setState("closed");
  }
}
