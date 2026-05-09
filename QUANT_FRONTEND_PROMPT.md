# INSTITUTIONAL QUANTITATIVE TRADING TERMINAL — FRONTEND BUILD PROMPT

## IDENTITY & MISSION

You are a principal frontend engineer who has shipped trading UIs at Citadel, Two Sigma, and Binance. Build a professional quantitative trading terminal from scratch — not a web dashboard, a real trading terminal. Target aesthetic and density: Bloomberg Terminal meets TradingView Pro meets Binance Advanced. Every design and engineering decision must reflect institutional standards.

---

## TECH STACK — NON-NEGOTIABLE

```
Runtime        : Vite 5 + React 19 (NOT Next.js — pure SPA, no SSR needed)
Language       : TypeScript 5.x, strict mode, no `any` anywhere
State (global) : Zustand 5 (sliced stores, devtools middleware)
State (server) : TanStack Query v5 (stale-while-revalidate, optimistic updates)
Styling        : Tailwind CSS v3 + CSS custom properties for all design tokens
Animations UI  : Framer Motion (page transitions, panels, modals ONLY)
Animations data: CSS transitions only (price flash, P&L color) — never Framer for data
Charts         : TradingView Lightweight Charts v5 (open-source npm package)
GPU canvas     : PixiJS v8 — ONLY for: OrderBook depth renderer, heatmap, tick flow
Realtime       : Native WebSocket + custom reconnection manager
Tables         : TanStack Virtual (virtualization) + custom table components
Workers        : Comlink + Web Workers for all heavy math
Forms          : react-hook-form + zod
Testing        : Vitest + React Testing Library + Playwright
Tooling        : ESLint (typescript-eslint strict) + Prettier + Husky
```

**BANNED**: Redux, MobX, jQuery, Ant Design, MUI, Next.js, Moment.js, lodash (use native ES), any component library that ships its own design system.

---

## ARCHITECTURE: FEATURE-SLICED DESIGN (FSD)

Strict FSD layer hierarchy. Upper layers may import lower; lower layers NEVER import upper.

```
src/
├── app/                    # App entry, providers, router, global styles
│   ├── providers/          # QueryClient, WS, Zustand, theme
│   ├── router.tsx
│   └── main.tsx
├── pages/                  # Route-level components (lazy loaded)
│   ├── terminal/           # Main trading terminal (default route)
│   ├── backtester/
│   ├── strategies/
│   ├── risk/
│   └── settings/
├── widgets/                # Self-contained panels composed from features
│   ├── ChartPanel/
│   ├── OrderBookPanel/
│   ├── StrategyConsole/
│   ├── RiskMonitor/
│   ├── TradePanel/
│   └── AIAnalysis/
├── features/               # Business logic units (each owns its store slice)
│   ├── market-data/        # WS feeds, tick normalization
│   ├── order-book/         # Order book state, depth calculation
│   ├── charting/           # Chart instance management, indicator registry
│   ├── strategy-control/   # Strategy lifecycle, param hot-update
│   ├── risk-management/    # Exposure, VaR, circuit breaker state
│   ├── order-entry/        # Order form, validation, submission
│   ├── backtest/           # Backtest job management, results
│   └── ai-panel/           # AI analysis requests and streaming response
├── entities/               # Core domain types + pure transformers
│   ├── tick/
│   ├── order/
│   ├── strategy/
│   ├── position/
│   └── alert/
└── shared/                 # Zero business logic — pure utilities
    ├── api/                # HTTP client (axios instance + interceptors)
    ├── ws/                 # WebSocket engine (see Section 1)
    ├── workers/            # Web Worker wrappers (Comlink)
    ├── hooks/              # useDebounce, useThrottle, useRAFState
    ├── ui/                 # Primitive UI components (Button, Badge, Tooltip)
    └── lib/                # formatPrice, formatVolume, IANA timezone utils
```

Each `feature/` directory structure:
```
feature-name/
├── model/      store.ts (Zustand slice), types.ts
├── api/        queries.ts (TanStack Query), mutations.ts
├── lib/        pure functions, no side effects
├── ui/         components that belong to this feature
└── index.ts    public API — only export what other layers need
```

---

## SECTION 1: WEBSOCKET ENGINE

Build `shared/ws/WebSocketEngine.ts` — a singleton class.

**Requirements:**
- Manages multiple named connections: `'market' | 'orders' | 'system' | 'ai'`
- Exponential backoff reconnection: `delay = Math.min(500 * 2^attempt, 30_000)` ms; max 10 attempts then emit `'fatal'` event
- Heartbeat: send `{type:'ping'}` every 15s; if no `{type:'pong'}` within 5s → reconnect
- Per-message latency tracking: stamp `receivedAt = performance.now()` on every message
- Typed subscription system: `subscribe<T>(topic: string, cb: (data: T) => void) => () => void`
- Message buffering: NEVER deliver directly to subscribers. Buffer in a `Map<topic, T[]>`, flush via `requestAnimationFrame` for visual topics (`tick.*`, `orderbook.*`) and via `setInterval(50ms)` for non-visual topics (`orders.*`, `risk.*`)
- Backpressure: if buffer for a topic exceeds 500 items, drop oldest entries and emit a `'lag'` metric event

```typescript
// Usage pattern (enforce everywhere)
const unsub = wsEngine.subscribe<OrderBookUpdate>('orderbook.BTCUSDT', (update) => {
  useOrderBookStore.getState().applyUpdate(update);
});
// cleanup in useEffect return
```

All Zustand store updates from WebSocket MUST go through this buffered path — no direct `setState` in WebSocket `onmessage` handlers anywhere in the codebase.

---

## SECTION 2: DESIGN SYSTEM & VISUAL LANGUAGE

Implement in `app/styles/tokens.css`. All colors, spacing, typography as CSS custom properties.

```css
:root {
  /* Background layers (darkest → lightest) */
  --bg-base:       #060A0F;   /* app background */
  --bg-surface:    #0C1117;   /* panel background */
  --bg-elevated:   #111820;   /* cards, dropdowns */
  --bg-highlight:  #1A2332;   /* hover states */
  --bg-border:     #1E2D3D;   /* borders */

  /* Text */
  --text-primary:  #E8EEF4;
  --text-secondary:#8BA0B4;
  --text-muted:    #4A6278;
  --text-accent:   #00B4D8;

  /* Semantic: financial */
  --color-bid:     #00C896;   /* green for bids/buys/positive */
  --color-ask:     #FF4D6A;   /* red for asks/sells/negative */
  --color-neutral: #7B8FA6;
  --color-warning: #F59E0B;
  --color-critical:#FF2D55;

  /* Chart specific */
  --chart-bg:         #060A0F;
  --chart-grid:       #0F1923;
  --chart-crosshair:  #2A4A6A;
  --chart-candle-up:  #00C896;
  --chart-candle-down:#FF4D6A;

  /* Typography */
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
  --font-ui:   'Inter', system-ui, sans-serif;
  --font-size-xs: 10px;
  --font-size-sm: 11px;
  --font-size-md: 12px;   /* default for dense data */
  --font-size-lg: 13px;
  --font-size-xl: 15px;

  /* Spacing (4px base grid) */
  --space-1: 4px; --space-2: 8px; --space-3: 12px;
  --space-4: 16px; --space-6: 24px; --space-8: 32px;
}
```

Rules:
- All financial numbers use `font-family: var(--font-mono)` with tabular-nums
- Price cells: 8 decimal places for crypto, 2 for equities — use `Intl.NumberFormat` with `maximumFractionDigits`
- Never hardcode a color — always reference CSS variables
- Panel titles: uppercase, 10px, letter-spacing 0.1em, `var(--text-muted)`
- Active/selected state: left border `2px solid var(--color-bid)` + `background: var(--bg-highlight)`

---

## SECTION 3: TERMINAL LAYOUT SYSTEM

The main terminal page is a **CSS Grid-based dockable panel system**.

```typescript
// Layout store (Zustand) — persisted to localStorage
interface LayoutConfig {
  panels: PanelConfig[];
  gridTemplate: string;  // CSS grid-template-areas value
}

interface PanelConfig {
  id: string;
  type: PanelType;  // 'chart' | 'orderbook' | 'trades' | 'strategy' | 'risk' | 'order-entry'
  area: string;     // grid-area name
  visible: boolean;
  width?: number;
  height?: number;
}
```

Default 4-region layout:
```
┌─────────────────────┬──────────────┬─────────────┐
│                     │              │  Strategy   │
│   TradingChart      │  OrderBook   │  Console    │
│   (flex: 1)         │  (280px)     │  (320px)    │
├─────────────────────┤              ├─────────────┤
│  Trade Feed         │  Depth Chart │  Risk       │
│  (200px height)     │  (200px)     │  Monitor    │
└─────────────────────┴──────────────┴─────────────┘
```

- Panels are resizable via drag-handle (CSS resize or custom pointer-events handler)
- Panel header has: title, symbol selector (where applicable), settings gear icon, minimize/maximize/close icons
- Minimized panels collapse to header-only bar and dock to a bottom toolbar
- Layout saved automatically on any resize/move; restored on reload
- Add `LayoutEditor` mode (toggled via gear icon in top nav): drag-and-drop panel reordering

---

## SECTION 4: TRADINGVIEW CHART COMPONENT

Use `lightweight-charts` npm package. Build `widgets/ChartPanel/TradingChart.tsx`.

**Chart initialization (critical — never recreate on re-render):**
```typescript
const chartRef = useRef<IChartApi | null>(null);
const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
const containerRef = useRef<HTMLDivElement>(null);

useEffect(() => {
  const chart = createChart(containerRef.current!, {
    layout: { background: { color: 'var(--chart-bg)' }, textColor: 'var(--text-secondary)' },
    grid: { vertLines: { color: 'var(--chart-grid)' }, horzLines: { color: 'var(--chart-grid)' } },
    crosshair: { mode: CrosshairMode.Normal, vertLine: { color: 'var(--chart-crosshair)' }, horzLine: { color: 'var(--chart-crosshair)' } },
    rightPriceScale: { borderColor: 'var(--bg-border)' },
    timeScale: { borderColor: 'var(--bg-border)', timeVisible: true, secondsVisible: false },
    handleScroll: true, handleScale: true,
  });
  chartRef.current = chart;
  seriesRef.current = chart.addCandlestickSeries({
    upColor: 'var(--chart-candle-up)', downColor: 'var(--chart-candle-down)',
    borderVisible: false, wickUpColor: 'var(--chart-candle-up)', wickDownColor: 'var(--chart-candle-down)',
  });
  return () => { chart.remove(); chartRef.current = null; };
}, []); // EMPTY DEPS — never recreate

// Real-time update (called from WS subscription)
// Use series.update() for live ticks — NEVER setData() on updates
```

**Required features:**
- Volume sub-pane (histogram, separate `HistogramSeries` below price pane)
- Indicator overlay support: accept `IndicatorConfig[]` prop; implement SMA, EMA, BOLL, VWAP as `LineSeries` overlays
- Strategy signal markers: `series.setMarkers()` for entry (▲ green) / exit (▼ red) signals from strategy engine
- Timeframe selector bar: 1m 5m 15m 1h 4h 1d 1w — styled as pill buttons, active state highlighted
- On timeframe change: call REST API for historical bars, `series.setData(bars)`, then resume WS stream
- Floating OHLCV tooltip: custom HTML overlay div, updated via `chart.subscribeCrosshairMove()`
- Synchronized crosshair: if multiple chart panels open, `subscribeCrosshairMove` on each and call `chart2.setCrosshairPosition()` to sync

---

## SECTION 5: ORDER BOOK (PIXI.JS RENDERER)

The OrderBook depth visualization uses PixiJS — NOT React components. Build `features/order-book/ui/OrderBookRenderer.ts`.

**Architecture:**
```typescript
class OrderBookRenderer {
  private app: PIXI.Application;
  private bidGraphics: PIXI.Graphics;
  private askGraphics: PIXI.Graphics;
  private textPool: TextPool;  // object pool for PIXI.Text — avoid GC

  constructor(canvas: HTMLCanvasElement) {
    this.app = new PIXI.Application({ canvas, backgroundColor: 0x060A0F,
                                       antialias: false, resolution: window.devicePixelRatio });
  }

  // Called from WS buffer flush — target 60fps render loop
  render(bids: Level[], asks: Level[], maxTotal: number): void {
    // Draw depth bars as filled rectangles (GPU accelerated)
    // Bid bars: right-aligned green rectangles, width proportional to cumulative total
    // Ask bars: right-aligned red rectangles
    // Use Graphics.clear() + redraws — do NOT create new Graphics objects per frame
  }
}
```

DOM layer (React) sits on top of PixiJS canvas for text rendering (prices, sizes) — use absolute-positioned divs synced to canvas coordinates. Text changes driven by React state, depth bars by PixiJS.

**OrderBook panel React wrapper** `widgets/OrderBookPanel/index.tsx`:
- Top section: spread display, mid-price, asks (20 levels, red)
- Middle: current price, large and prominent
- Bottom section: bids (20 levels, green)
- Right side: PixiJS canvas for depth chart
- "Group" selector: 0.01 / 0.1 / 1 / 10 / 100 — buckets levels before render
- Price cells flash on change: CSS `@keyframes flash-bid` / `flash-ask` (opacity pulse, 300ms)
- Use `React.memo` on every row with custom `areEqual` comparator

---

## SECTION 6: STRATEGY CONSOLE WIDGET

`widgets/StrategyConsole/` — shows all running strategies in real-time.

**Strategy Card component** (one per running strategy):
```
┌─ MOMENTUM_BTC ────────────────── ● RUNNING ─┐
│ Symbol: BTCUSDT    Capital: $50,000           │
│ ─────────────────────────────────────────    │
│ PnL Today    Sharpe(30d)  Max DD    Win Rate  │
│ +$1,243.50    2.34        -3.2%     67.4%     │
│ ─────────────────────────────────────────    │
│ Position: LONG 0.342 BTC @ $43,210           │
│ Unreal. PnL: +$287.40                        │
│ ─────────────────────────────────────────    │
│ [▶ RESUME] [⏸ PAUSE] [⏹ STOP] [⚙ PARAMS]   │
└──────────────────────────────────────────────┘
```

- Status badge: RUNNING (green pulse dot), PAUSED (amber), STOPPED (grey), ERROR (red blink)
- P&L: green if positive, red if negative, monospace font, 2 decimal places
- **Parameter hot-update drawer**: slides in from right, renders form fields dynamically from JSON Schema returned by backend (`GET /api/strategies/{id}/schema`). On submit: `PUT /api/strategies/{id}/parameters` — optimistic update in Zustand, rollback on error
- Equity micro-chart: small Lightweight Charts `AreaSeries` (80px height) showing today's equity curve, no axes, embedded in card footer
- All numeric values animate via CSS counter or requestAnimationFrame interpolation — no jarring jumps

---

## SECTION 7: RISK MONITOR WIDGET

`widgets/RiskMonitor/` — always-visible, real-time risk state.

**Required sub-components:**
1. **Circuit Breaker Status** — large colored banner: ACTIVE (green) / WARNING (amber pulse) / TRIPPED (red full-screen overlay with halt message)
2. **Exposure Bars** — horizontal bars per asset class: current exposure / max allowed. Color: green → amber (80%) → red (100%)
3. **VaR Display** — two cards: 95% VaR and 99% VaR in dollar terms, updated every 5s
4. **Drawdown Gauge** — semicircle SVG meter: current drawdown % of daily limit. CSS animated arc stroke-dashoffset
5. **Position Table** — virtual list (TanStack Virtual), columns: Symbol | Side | Qty | Avg Entry | Market Price | Unreal P&L | % of Portfolio. Rows sorted by absolute exposure descending
6. **Alert Feed** — latest 20 alerts, each with severity icon, timestamp, message. Auto-scroll to new alerts. Critical alerts trigger a `window.Notification` if permission granted

---

## SECTION 8: BACKTESTER PAGE

`pages/backtester/` — full-page view, not a panel.

**Config panel (left sidebar 340px):**
- Strategy selector (combobox with search)
- Symbol multi-select
- Date range picker (custom, not a library widget)
- Capital input + commission rate + slippage model (market/realistic/zero)
- Parameter grid: rendered dynamically from strategy JSON Schema (same schema used in hot-update drawer)
- "Run Backtest" → `POST /api/backtest/run` → returns `{ job_id }`

**Progress overlay:**
- TanStack Query `refetchInterval: 1500` polling `GET /api/backtest/status/{job_id}`
- Animated progress bar + "Simulating: 2024-03-15" current date display

**Results dashboard (fills remaining space):**
- Layout: 2-column grid
- Left column:
  - Equity curve (Lightweight Charts `AreaSeries`, drawdown shading as `HistogramSeries` below)
  - Monthly returns heatmap (custom SVG, 12 cols × N years, green/red cells, hover tooltip)
- Right column:
  - Metrics table (18 metrics in a clean 2-col layout, monospace values)
  - Trade P&L distribution histogram (custom SVG bars)
  - Drawdown periods table (start, end, depth, duration, recovery)
- Full trade log at bottom: TanStack Virtual table, 100k rows smooth scroll

**Monte Carlo panel** (expandable section):
- Run `POST /api/backtest/{id}/montecarlo` → returns 1000 equity curve paths
- Render percentile bands (5th, 25th, 50th, 75th, 95th) as Lightweight Charts `LineSeries`

---

## SECTION 9: AI ANALYSIS PANEL

`widgets/AIAnalysis/` — collapsible panel.

- Input: text area "Ask the AI about current market conditions..."
- On submit: `POST /api/ai/analyze` with current symbol, strategy list, risk state as context
- Response: **streamed** via Server-Sent Events (`EventSource`). Render tokens progressively into a markdown renderer (`react-markdown` + syntax highlighting for code blocks)
- Quick-action chips: "Analyze current risk exposure", "Suggest parameter adjustments for BTCUSDT", "Explain today's drawdown"
- Factor Analysis tab: table of top-N alpha factors with IC (Information Coefficient), t-stat, decay, updated daily

---

## SECTION 10: PERFORMANCE REQUIREMENTS — ENFORCE STRICTLY

**Rendering:**
- Never call `setState` directly from a WebSocket `onmessage` handler. Always use buffered dispatch (Section 1).
- All lists > 50 items: mandatory `useVirtual` from TanStack Virtual.
- `React.memo` on every component that receives data props. Zustand selectors must be atomic (select only what the component needs, not the whole slice).

**Web Workers (mandatory for):**
- Rolling Sharpe ratio calculation (`workers/sharpe.worker.ts`)
- Correlation matrix computation (`workers/correlation.worker.ts`)
- Backtest progress data transformation (`workers/backtest-transform.worker.ts`)
- All workers wrapped with `comlink` — no `postMessage` boilerplate in components

**Bundle targets (enforce in `vite.config.ts`):**
```typescript
build: {
  rollupOptions: {
    output: {
      manualChunks: {
        'vendor-react': ['react', 'react-dom'],
        'vendor-charts': ['lightweight-charts'],
        'vendor-pixi': ['pixi.js'],
        'vendor-motion': ['framer-motion'],
      }
    }
  }
}
// Target: initial JS < 180KB gzipped, LCP < 1.2s
```

**CSS animations for data (no JS animation libraries):**
```css
/* Price flash on tick update */
@keyframes flash-positive { 0%,100%{background:transparent} 50%{background:rgba(0,200,150,0.15)} }
@keyframes flash-negative { 0%,100%{background:transparent} 50%{background:rgba(255,77,106,0.15)} }
.price-up   { animation: flash-positive 300ms ease-out; }
.price-down { animation: flash-negative 300ms ease-out; }
```

Apply via toggling className — remove after animation ends (`animationend` event).

---

## SECTION 11: AUTH & SESSION

- Login page: email + password + TOTP 6-digit input. Minimal, full-screen centered, dark background.
- JWT: store `accessToken` in memory (Zustand), `refreshToken` in httpOnly cookie (never localStorage)
- Axios interceptor: on 401 → call `POST /auth/refresh` silently → retry original request
- Session expiry warning: modal at T-2 min with countdown
- Protected routes: `<AuthGuard>` wrapper that reads Zustand auth state; redirect to `/login` if unauthenticated
- API Key management page: list exchange keys (masked), add new (show secret once), revoke — in Settings page

---

## SECTION 12: ENGINEERING STANDARDS

**File & naming conventions:**
- Components: PascalCase files, named exports
- Hooks: `useCamelCase.ts`
- Stores: `useCamelCaseStore.ts`
- Types: colocated in `model/types.ts` per feature, re-exported via `index.ts`
- API layer: all `fetch`/`axios` calls in `*/api/*.ts` — zero inline fetches in components

**Error boundaries:** wrap every widget (`<WidgetErrorBoundary>`) — a crashed chart must not crash the terminal

**Accessibility (non-negotiable for keyboard-operated trading):**
- All interactive elements keyboard focusable
- Number inputs: support arrow keys for increment/decrement
- Modal: focus trap, Escape to close
- Order entry: Enter key submits, Tab moves between fields

**Storybook:** every `shared/ui/` component must have a `.stories.tsx` file

**E2E tests (Playwright):** test these critical paths:
1. Login → terminal loads → WebSocket connects → prices update
2. Strategy pause → status changes → resume
3. Backtest run → progress → results render
4. Order entry → validation error → valid submission → confirmation

---

## DELIVERABLE ORDER

Build in this sequence (each step should be independently committable):

1. `shared/` foundation: design tokens, WS engine, HTTP client, Worker wrappers
2. `app/` layer: providers, router, auth guard, layout shell
3. `entities/` domain types
4. `features/market-data/` + Zustand store + WS subscriptions
5. `widgets/ChartPanel/` — TradingView chart, timeframes, indicators
6. `features/order-book/` + PixiJS renderer + React wrapper panel
7. `widgets/StrategyConsole/` — strategy cards, param drawer
8. `widgets/RiskMonitor/` — all sub-components
9. `pages/backtester/` — full backtest flow
10. `widgets/AIAnalysis/` — SSE streaming panel
11. Auth flow: login, token refresh, API key management
12. Performance pass: bundle analysis, virtual scroll audit, animation audit
13. Storybook + E2E test suite
