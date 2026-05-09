# P0: 机构级量化交易终端 — 基础架构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建机构级量化交易终端的完整基础架构，包括 Monorepo、Next.js 15 应用、设计系统、WebSocket 客户端、Dock 布局、认证流程。

**Architecture:** Turborepo monorepo + Feature-Sliced Design 分层。4个共享包（types/ui/ws/gpu）+ 1个 Next.js 主应用。FSD 严格依赖规则：app → pages → widgets → features → entities → shared。

**Tech Stack:** Next.js 15, React 19, TypeScript 5.7, TailwindCSS 4, Framer Motion 12, Zustand 5, TanStack Query 5, react-mosaic, PixiJS 8, pnpm 10, Turborepo 2

---

## File Structure

### 新建文件清单

```
terminal/
├── turbo.json
├── package.json
├── pnpm-workspace.yaml
├── .gitignore
├── packages/
│   ├── types/
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   └── src/
│   │       ├── market.ts
│   │       ├── trading.ts
│   │       ├── strategy.ts
│   │       ├── risk.ts
│   │       └── index.ts
│   ├── ui/
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   ├── tailwind.config.ts
│   │   └── src/
│   │       ├── theme/
│   │       │   ├── tokens.ts
│   │       │   └── index.ts
│   │       ├── components/
│   │       │   ├── Panel.tsx
│   │       │   ├── DataGrid.tsx
│   │       │   ├── MetricCard.tsx
│   │       │   ├── PriceDisplay.tsx
│   │       │   ├── DepthBar.tsx
│   │       │   ├── StatusBadge.tsx
│   │       │   ├── CommandPalette.tsx
│   │       │   └── Toast.tsx
│   │       └── index.ts
│   ├── ws-client/
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   └── src/
│   │       ├── protocol.ts
│   │       ├── client.ts
│   │       ├── streams.ts
│   │       └── index.ts
│   └── gpu-renderer/
│       ├── package.json
│       ├── tsconfig.json
│       └── src/
│           ├── depth-canvas.tsx
│           ├── heatmap-canvas.tsx
│           └── index.ts
└── apps/
    └── terminal/
        ├── package.json
        ├── tsconfig.json
        ├── next.config.ts
        ├── tailwind.config.ts
        ├── postcss.config.mjs
        └── src/
            ├── app/
            │   ├── layout.tsx
            │   ├── globals.css
            │   ├── (auth)/
            │   │   ├── layout.tsx
            │   │   └── login/
            │   │       └── page.tsx
            │   └── (terminal)/
            │       ├── layout.tsx
            │       ├── page.tsx
            │       ├── dashboard/
            │       │   └── page.tsx
            │       ├── market/
            │       │   └── page.tsx
            │       ├── stock/
            │       │   └── [symbol]/
            │       │       └── page.tsx
            │       ├── strategy/
            │       │   └── page.tsx
            │       ├── backtest/
            │       │   └── page.tsx
            │       ├── portfolio/
            │       │   └── page.tsx
            │       ├── risk/
            │       │   └── page.tsx
            │       ├── screener/
            │       │   └── page.tsx
            │       └── settings/
            │           └── page.tsx
            ├── shared/
            │   ├── api/
            │   │   ├── client.ts
            │   │   └── index.ts
            │   ├── lib/
            │   │   ├── cn.ts
            │   │   └── format.ts
            │   └── config/
            │       └── index.ts
            ├── entities/
            │   ├── stock/
            │   │   ├── model/
            │   │   │   └── store.ts
            │   │   └── index.ts
            │   ├── position/
            │   │   ├── model/
            │   │   │   └── store.ts
            │   │   └── index.ts
            │   └── strategy/
            │       ├── model/
            │       │   └── store.ts
            │       └── index.ts
            ├── features/
            │   ├── auth/
            │   │   ├── model/
            │   │   │   └── use-auth.ts
            │   │   ├── ui/
            │   │   │   └── login-form.tsx
            │   │   └── index.ts
            │   └── market-data/
            │       ├── model/
            │       │   └── use-market-data.ts
            │       └── index.ts
            ├── widgets/
            │   ├── sidebar/
            │   │   ├── ui/
            │   │   │   └── sidebar.tsx
            │   │   └── index.ts
            │   ├── topbar/
            │   │   ├── ui/
            │   │   │   └── topbar.tsx
            │   │   └── index.ts
            │   └── dock-layout/
            │       ├── ui/
            │       │   └── dock-layout.tsx
            │       ├── model/
            │       │   └── use-dock-layout.ts
            │       └── index.ts
            ├── pages/
            │   └── (terminal)/
            │       └── dashboard.ts
            └── providers/
                ├── query-provider.tsx
                ├── ws-provider.tsx
                ├── theme-provider.tsx
                └── dock-provider.tsx
```

---

## Task 1: Monorepo 基础搭建

**Files:**
- Create: `terminal/package.json`
- Create: `terminal/pnpm-workspace.yaml`
- Create: `terminal/turbo.json`
- Create: `terminal/.gitignore`

- [ ] **Step 1: 创建 terminal 目录和 root package.json**

```bash
mkdir -p "/Users/fei/Desktop/大三下 /quantitative-trading-system/terminal"
```

```json
{
  "name": "quantcore-terminal",
  "private": true,
  "packageManager": "pnpm@10.12.1",
  "scripts": {
    "dev": "turbo run dev",
    "build": "turbo run build",
    "lint": "turbo run lint",
    "typecheck": "turbo run typecheck",
    "test": "turbo run test"
  }
}
```

- [ ] **Step 2: 创建 pnpm-workspace.yaml**

```yaml
packages:
  - "packages/*"
  - "apps/*"
```

- [ ] **Step 3: 创建 turbo.json**

```json
{
  "$schema": "https://turbo.build/schema.json",
  "tasks": {
    "build": {
      "dependsOn": ["^build"],
      "outputs": ["dist/**", ".next/**"]
    },
    "dev": {
      "cache": false,
      "persistent": true
    },
    "lint": {
      "dependsOn": ["^build"]
    },
    "typecheck": {
      "dependsOn": ["^build"]
    },
    "test": {
      "dependsOn": ["^build"]
    }
  }
}
```

- [ ] **Step 4: 创建 .gitignore**

```
node_modules
.next
dist
.turbo
*.tsbuildinfo
```

- [ ] **Step 5: 初始化 pnpm 并验证**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system/terminal" && pnpm install
```

Expected: pnpm 成功安装（无包时可能警告，但不应报错）

- [ ] **Step 6: Commit**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system" && git add terminal/ && git commit -m "feat: initialize Turborepo monorepo for institutional terminal"
```

---

## Task 2: @qc/types 共享类型包

**Files:**
- Create: `terminal/packages/types/package.json`
- Create: `terminal/packages/types/tsconfig.json`
- Create: `terminal/packages/types/src/market.ts`
- Create: `terminal/packages/types/src/trading.ts`
- Create: `terminal/packages/types/src/strategy.ts`
- Create: `terminal/packages/types/src/risk.ts`
- Create: `terminal/packages/types/src/index.ts`

- [ ] **Step 1: 创建 package.json**

```json
{
  "name": "@qc/types",
  "version": "0.0.1",
  "private": true,
  "main": "./src/index.ts",
  "types": "./src/index.ts",
  "scripts": {
    "typecheck": "tsc --noEmit"
  }
}
```

- [ ] **Step 2: 创建 tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "outDir": "./dist",
    "rootDir": "./src",
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true
  },
  "include": ["src"]
}
```

- [ ] **Step 3: 创建 src/market.ts**

```typescript
export interface StockQuote {
  symbol: string
  name: string
  price: number
  change: number
  change_pct: number
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount: number
  turnover_rate: number
  timestamp: number
}

export interface KlineBar {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount: number
}

export interface DepthLevel {
  price: number
  quantity: number
  order_count: number
}

export interface DepthData {
  asks: DepthLevel[]
  bids: DepthLevel[]
  timestamp: number
}

export interface TradeRecord {
  id: string
  price: number
  quantity: number
  direction: 'buy' | 'sell' | 'neutral'
  timestamp: number
}

export interface HeatmapItem {
  name: string
  change_pct: number
  amount: number
  value: number
  leader: string
}
```

- [ ] **Step 4: 创建 src/trading.ts**

```typescript
export interface Position {
  symbol: string
  name: string
  market: string
  shares: number
  avg_cost: number
  current_price: number
  market_value: number
  profit: number
  profit_pct: number
  weight: number
  stop_loss: number
  take_profit: number
  strategy: string
  entry_date: string
}

export interface Order {
  id: string
  symbol: string
  name: string
  direction: 'buy' | 'sell'
  type: 'market' | 'limit' | 'stop'
  price: number
  quantity: number
  filled: number
  status: 'pending' | 'partial' | 'filled' | 'cancelled' | 'rejected'
  created_at: string
  updated_at: string
}

export interface NewOrder {
  symbol: string
  direction: 'buy' | 'sell'
  type: 'market' | 'limit' | 'stop'
  price: number
  quantity: number
}

export interface Trade {
  id: string
  order_id: string
  symbol: string
  direction: 'buy' | 'sell'
  price: number
  quantity: number
  commission: number
  timestamp: string
}
```

- [ ] **Step 5: 创建 src/strategy.ts**

```typescript
export interface Strategy {
  id: string
  name: string
  type: string
  status: 'running' | 'stopped' | 'error'
  params: Record<string, unknown>
  pnl: number
  pnl_pct: number
  sharpe: number
  max_drawdown: number
  win_rate: number
  trade_count: number
  started_at: string | null
  stopped_at: string | null
}

export interface StrategySignal {
  id: string
  strategy_id: string
  symbol: string
  direction: 'long' | 'short' | 'close'
  price: number
  strength: number
  timestamp: string
}

export interface BacktestResult {
  id: string
  strategy_id: string
  start_date: string
  end_date: string
  initial_capital: number
  final_capital: number
  total_return: number
  annual_return: number
  sharpe: number
  max_drawdown: number
  win_rate: number
  trade_count: number
  equity_curve: { time: number; value: number }[]
  drawdown_curve: { time: number; value: number }[]
}
```

- [ ] **Step 6: 创建 src/risk.ts**

```typescript
export interface RiskExposure {
  total_exposure: number
  long_exposure: number
  short_exposure: number
  net_exposure: number
  beta: number
  var_95: number
  var_99: number
  cvar: number
  timestamp: number
}

export interface RiskAlert {
  id: string
  type: 'position_limit' | 'drawdown' | 'concentration' | 'correlation' | 'circuit_breaker'
  severity: 'info' | 'warning' | 'critical'
  message: string
  value: number
  threshold: number
  timestamp: string
  acknowledged: boolean
}

export interface CircuitBreaker {
  id: string
  name: string
  status: 'active' | 'triggered' | 'cooldown'
  trigger_count: number
  last_triggered: string | null
  cooldown_until: string | null
}
```

- [ ] **Step 7: 创建 src/index.ts**

```typescript
export * from './market'
export * from './trading'
export * from './strategy'
export * from './risk'
```

- [ ] **Step 8: 验证类型检查**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system/terminal" && pnpm install && pnpm --filter @qc/types typecheck
```

Expected: 类型检查通过，无错误

- [ ] **Step 9: Commit**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system" && git add terminal/packages/types/ && git commit -m "feat: add @qc/types shared type definitions"
```

---

## Task 3: @qc/ws WebSocket 客户端包

**Files:**
- Create: `terminal/packages/ws-client/package.json`
- Create: `terminal/packages/ws-client/tsconfig.json`
- Create: `terminal/packages/ws-client/src/protocol.ts`
- Create: `terminal/packages/ws-client/src/client.ts`
- Create: `terminal/packages/ws-client/src/streams.ts`
- Create: `terminal/packages/ws-client/src/index.ts`

- [ ] **Step 1: 创建 package.json**

```json
{
  "name": "@qc/ws",
  "version": "0.0.1",
  "private": true,
  "main": "./src/index.ts",
  "types": "./src/index.ts",
  "dependencies": {
    "@qc/types": "workspace:*"
  },
  "scripts": {
    "typecheck": "tsc --noEmit"
  }
}
```

- [ ] **Step 2: 创建 tsconfig.json**（同 @qc/types 的 tsconfig.json）

- [ ] **Step 3: 创建 src/protocol.ts**

```typescript
export type WSChannel =
  | `sub:market:${string}`
  | `sub:depth:${string}`
  | `sub:trade:${string}`
  | `sub:strategy:status`
  | `sub:risk:exposure`

export interface WSMessage {
  ch: string
  data: unknown
  ts: number
}

export interface WSSubscribe {
  action: 'sub' | 'unsub'
  ch: string
}

export function encodeMessage(msg: WSSubscribe): string {
  return JSON.stringify(msg)
}

export function decodeMessage(raw: string): WSMessage {
  return JSON.parse(raw) as WSMessage
}
```

- [ ] **Step 4: 创建 src/client.ts**

```typescript
import { encodeMessage, decodeMessage, type WSChannel, type WSMessage, type WSSubscribe } from './protocol'

type Callback = (data: unknown, msg: WSMessage) => void
type Unsubscribe = () => void
type StatusCallback = (status: 'connecting' | 'connected' | 'disconnected' | 'error') => void

const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 30000
const HEARTBEAT_MS = 30000

export class QuantCoreWS {
  private ws: WebSocket | null = null
  private url: string = ''
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private reconnectAttempts = 0
  private subscriptions = new Map<string, Set<Callback>>()
  private statusCallbacks = new Set<StatusCallback>()
  private messageQueue: string[] = []

  connect(url: string): void {
    this.url = url
    this.reconnectAttempts = 0
    this.doConnect()
  }

  disconnect(): void {
    this.clearTimers()
    if (this.ws) {
      this.ws.onopen = null
      this.ws.onclose = null
      this.ws.onerror = null
      this.ws.onmessage = null
      this.ws.close()
      this.ws = null
    }
    this.emitStatus('disconnected')
  }

  subscribe(channel: string, cb: Callback): Unsubscribe {
    if (!this.subscriptions.has(channel)) {
      this.subscriptions.set(channel, new Set())
      this.sendSubscribe('sub', channel)
    }
    this.subscriptions.get(channel)!.add(cb)
    return () => {
      const cbs = this.subscriptions.get(channel)
      if (cbs) {
        cbs.delete(cb)
        if (cbs.size === 0) {
          this.subscriptions.delete(channel)
          this.sendSubscribe('unsub', channel)
        }
      }
    }
  }

  onStatus(cb: StatusCallback): Unsubscribe {
    this.statusCallbacks.add(cb)
    return () => { this.statusCallbacks.delete(cb) }
  }

  private doConnect(): void {
    this.emitStatus('connecting')
    this.ws = new WebSocket(this.url)

    this.ws.onopen = () => {
      this.reconnectAttempts = 0
      this.startHeartbeat()
      this.flushQueue()
      this.resubscribeAll()
      this.emitStatus('connected')
    }

    this.ws.onclose = () => {
      this.clearTimers()
      this.emitStatus('disconnected')
      this.scheduleReconnect()
    }

    this.ws.onerror = () => {
      this.emitStatus('error')
    }

    this.ws.onmessage = (event) => {
      const msg = decodeMessage(String(event.data))
      const cbs = this.subscriptions.get(msg.ch)
      if (cbs) {
        for (const cb of cbs) {
          cb(msg.data, msg)
        }
      }
    }
  }

  private scheduleReconnect(): void {
    const delay = Math.min(RECONNECT_BASE_MS * Math.pow(2, this.reconnectAttempts), RECONNECT_MAX_MS)
    this.reconnectAttempts++
    this.reconnectTimer = setTimeout(() => this.doConnect(), delay)
  }

  private startHeartbeat(): void {
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ action: 'ping' }))
      }
    }, HEARTBEAT_MS)
  }

  private clearTimers(): void {
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null }
    if (this.heartbeatTimer) { clearInterval(this.heartbeatTimer); this.heartbeatTimer = null }
  }

  private sendSubscribe(action: WSSubscribe['action'], ch: string): void {
    const msg = encodeMessage({ action, ch })
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(msg)
    } else {
      this.messageQueue.push(msg)
    }
  }

  private flushQueue(): void {
    if (!this.ws) return
    for (const msg of this.messageQueue) {
      this.ws.send(msg)
    }
    this.messageQueue = []
  }

  private resubscribeAll(): void {
    for (const ch of this.subscriptions.keys()) {
      this.sendSubscribe('sub', ch)
    }
  }

  private emitStatus(status: Parameters<StatusCallback>[0]): void {
    for (const cb of this.statusCallbacks) {
      cb(status)
    }
  }
}

export const wsClient = new QuantCoreWS()
```

- [ ] **Step 5: 创建 src/streams.ts**

```typescript
import { wsClient } from './client'
import type { StockQuote, DepthData, TradeRecord, Strategy, RiskExposure } from '@qc/types'
import type { Unsubscribe } from './client'

export function subscribeQuote(symbol: string, cb: (quote: StockQuote) => void): Unsubscribe {
  return wsClient.subscribe(`sub:market:${symbol}`, (data) => {
    cb(data as StockQuote)
  })
}

export function subscribeDepth(symbol: string, cb: (depth: DepthData) => void): Unsubscribe {
  return wsClient.subscribe(`sub:depth:${symbol}`, (data) => {
    cb(data as DepthData)
  })
}

export function subscribeTrades(symbol: string, cb: (trade: TradeRecord) => void): Unsubscribe {
  return wsClient.subscribe(`sub:trade:${symbol}`, (data) => {
    cb(data as TradeRecord)
  })
}

export function subscribeStrategyStatus(cb: (strategy: Strategy) => void): Unsubscribe {
  return wsClient.subscribe('sub:strategy:status', (data) => {
    cb(data as Strategy)
  })
}

export function subscribeRiskExposure(cb: (risk: RiskExposure) => void): Unsubscribe {
  return wsClient.subscribe('sub:risk:exposure', (data) => {
    cb(data as RiskExposure)
  })
}
```

- [ ] **Step 6: 创建 src/index.ts**

```typescript
export { QuantCoreWS, wsClient } from './client'
export { subscribeQuote, subscribeDepth, subscribeTrades, subscribeStrategyStatus, subscribeRiskExposure } from './streams'
export type { WSChannel, WSMessage, WSSubscribe } from './protocol'
```

- [ ] **Step 7: 验证类型检查**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system/terminal" && pnpm install && pnpm --filter @qc/ws typecheck
```

Expected: 类型检查通过

- [ ] **Step 8: Commit**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system" && git add terminal/packages/ws-client/ && git commit -m "feat: add @qc/ws WebSocket client with reconnection and multiplexing"
```

---

## Task 4: @qc/ui 设计系统包

**Files:**
- Create: `terminal/packages/ui/package.json`
- Create: `terminal/packages/ui/tsconfig.json`
- Create: `terminal/packages/ui/tailwind.config.ts`
- Create: `terminal/packages/ui/src/theme/tokens.ts`
- Create: `terminal/packages/ui/src/theme/index.ts`
- Create: `terminal/packages/ui/src/components/Panel.tsx`
- Create: `terminal/packages/ui/src/components/MetricCard.tsx`
- Create: `terminal/packages/ui/src/components/PriceDisplay.tsx`
- Create: `terminal/packages/ui/src/components/StatusBadge.tsx`
- Create: `terminal/packages/ui/src/components/Toast.tsx`
- Create: `terminal/packages/ui/src/index.ts`

- [ ] **Step 1: 创建 package.json**

```json
{
  "name": "@qc/ui",
  "version": "0.0.1",
  "private": true,
  "main": "./src/index.ts",
  "types": "./src/index.ts",
  "dependencies": {
    "react": "^19.1.0",
    "react-dom": "^19.1.0",
    "framer-motion": "^12.0.0",
    "clsx": "^2.1.1",
    "tailwind-merge": "^3.0.0"
  },
  "peerDependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "scripts": {
    "typecheck": "tsc --noEmit"
  }
}
```

- [ ] **Step 2: 创建 tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "jsx": "react-jsx",
    "declaration": true,
    "sourceMap": true,
    "outDir": "./dist",
    "rootDir": "./src",
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true
  },
  "include": ["src"]
}
```

- [ ] **Step 3: 创建 src/theme/tokens.ts**

```typescript
export const colors = {
  bg: {
    void: '#050507',
    surface: '#0a0a0f',
    raised: '#12121a',
    overlay: '#1a1a24',
  },
  text: {
    primary: '#e8e8f0',
    secondary: '#9898a8',
    muted: '#585868',
    tertiary: '#383848',
  },
  accent: {
    DEFAULT: '#3b82f6',
    muted: '#1e3a5f',
    hover: '#60a5fa',
  },
  rise: {
    DEFAULT: '#22c55e',
    muted: '#166534',
    rgb: '34,197,94',
  },
  fall: {
    DEFAULT: '#ef4444',
    muted: '#7f1d1d',
    rgb: '239,68,68',
  },
  warn: {
    DEFAULT: '#f59e0b',
    muted: '#78350f',
  },
  border: {
    hair: '#1a1a24',
    dim: '#252530',
    mid: '#353545',
  },
} as const

export const spacing = {
  0: '0px',
  0.5: '2px',
  1: '4px',
  1.5: '6px',
  2: '8px',
  3: '12px',
  4: '16px',
  5: '20px',
  6: '24px',
  8: '32px',
  10: '40px',
  12: '48px',
  16: '64px',
} as const

export const radii = {
  sm: '4px',
  md: '6px',
  lg: '8px',
  xl: '12px',
} as const

export const fonts = {
  sans: 'Inter, -apple-system, system-ui, sans-serif',
  mono: '"JetBrains Mono", "SF Mono", "Fira Code", monospace',
} as const

export const durations = {
  fast: '100ms',
  normal: '200ms',
  slow: '300ms',
} as const

export const easings = {
  mechanical: 'cubic-bezier(0.4, 0, 0.2, 1)',
  spring: 'cubic-bezier(0.175, 0.885, 0.32, 1.275)',
} as const
```

- [ ] **Step 4: 创建 src/theme/index.ts**

```typescript
export * from './tokens'
```

- [ ] **Step 5: 创建 src/components/Panel.tsx**

```tsx
'use client'

import { type ReactNode, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { clsx } from 'clsx'

interface PanelProps {
  title: string
  icon?: ReactNode
  accent?: string
  collapsible?: boolean
  defaultCollapsed?: boolean
  actions?: ReactNode
  children: ReactNode
  className?: string
}

export function Panel({
  title,
  icon,
  accent = 'var(--accent)',
  collapsible = false,
  defaultCollapsed = false,
  actions,
  children,
  className,
}: PanelProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed)

  return (
    <div className={clsx('flex flex-col bg-[var(--bg-surface)] border border-[var(--border-hair)] rounded-[var(--r-md)] overflow-hidden', className)}>
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border-hair)] select-none">
        <div className="flex items-center gap-2">
          <span className="w-1 h-3 rounded-full" style={{ background: accent }} />
          {icon}
          <span className="font-mono text-[11px] font-semibold tracking-widest text-[var(--text-secondary)] uppercase">
            {title}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {actions}
          {collapsible && (
            <button
              onClick={() => setCollapsed(!collapsed)}
              className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors text-xs font-mono"
              aria-label={collapsed ? 'Expand panel' : 'Collapse panel'}
            >
              {collapsed ? '+' : '−'}
            </button>
          )}
        </div>
      </div>
      <AnimatePresence initial={false}>
        {!collapsed && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15, ease: [0.4, 0, 0.2, 1] }}
            className="overflow-hidden"
          >
            {children}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
```

- [ ] **Step 6: 创建 src/components/MetricCard.tsx**

```tsx
'use client'

import { motion } from 'framer-motion'
import { clsx } from 'clsx'

interface MetricCardProps {
  label: string
  value: string | number
  change?: number
  prefix?: string
  suffix?: string
  className?: string
}

export function MetricCard({ label, value, change, prefix, suffix, className }: MetricCardProps) {
  const isPositive = change !== undefined && change >= 0

  return (
    <div className={clsx('flex flex-col gap-1 px-3 py-2', className)}>
      <span className="font-mono text-[10px] tracking-widest text-[var(--text-muted)] uppercase">
        {label}
      </span>
      <div className="flex items-baseline gap-1.5">
        {prefix && <span className="font-mono text-xs text-[var(--text-muted)]">{prefix}</span>}
        <motion.span
          key={String(value)}
          initial={{ opacity: 0.7, y: 2 }}
          animate={{ opacity: 1, y: 0 }}
          className="font-mono text-lg font-semibold text-[var(--text-primary)] tabular-nums"
        >
          {value}
        </motion.span>
        {suffix && <span className="font-mono text-xs text-[var(--text-muted)]">{suffix}</span>}
        {change !== undefined && (
          <span className={clsx('font-mono text-[11px] tabular-nums', isPositive ? 'text-[var(--rise)]' : 'text-[var(--fall)]')}>
            {isPositive ? '▲' : '▼'} {Math.abs(change).toFixed(2)}%
          </span>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 7: 创建 src/components/PriceDisplay.tsx**

```tsx
'use client'

import { useEffect, useState, useRef } from 'react'
import { clsx } from 'clsx'

interface PriceDisplayProps {
  price: number
  change?: number
  decimals?: number
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

export function PriceDisplay({ price, change, decimals = 2, size = 'md', className }: PriceDisplayProps) {
  const [flash, setFlash] = useState<'up' | 'down' | null>(null)
  const prevPrice = useRef(price)

  useEffect(() => {
    if (price !== prevPrice.current) {
      setFlash(price > prevPrice.current ? 'up' : 'down')
      prevPrice.current = price
      const t = setTimeout(() => setFlash(null), 300)
      return () => clearTimeout(t)
    }
  }, [price])

  const sizeClasses = {
    sm: 'text-sm',
    md: 'text-xl',
    lg: 'text-3xl',
  }

  const colorClass = change !== undefined
    ? change >= 0 ? 'text-[var(--rise)]' : 'text-[var(--fall)]'
    : 'text-[var(--text-primary)]'

  return (
    <span
      className={clsx(
        'font-mono font-semibold tabular-nums transition-colors duration-150',
        sizeClasses[size],
        colorClass,
        flash === 'up' && 'bg-[rgba(34,197,94,0.15)]',
        flash === 'down' && 'bg-[rgba(239,68,68,0.15)]',
        className,
      )}
    >
      {price.toFixed(decimals)}
    </span>
  )
}
```

- [ ] **Step 8: 创建 src/components/StatusBadge.tsx**

```tsx
'use client'

import { clsx } from 'clsx'

type Status = 'running' | 'stopped' | 'error' | 'pending'

interface StatusBadgeProps {
  status: Status
  label?: string
  className?: string
}

const statusConfig: Record<Status, { color: string; dot: string; label: string }> = {
  running: { color: 'text-[var(--rise)] border-[var(--rise)]', dot: 'bg-[var(--rise)]', label: 'RUNNING' },
  stopped: { color: 'text-[var(--text-muted)] border-[var(--border-mid)]', dot: 'bg-[var(--text-muted)]', label: 'STOPPED' },
  error: { color: 'text-[var(--fall)] border-[var(--fall)]', dot: 'bg-[var(--fall)]', label: 'ERROR' },
  pending: { color: 'text-[var(--warn)] border-[var(--warn)]', dot: 'bg-[var(--warn)]', label: 'PENDING' },
}

export function StatusBadge({ status, label, className }: StatusBadgeProps) {
  const config = statusConfig[status]
  return (
    <span className={clsx('inline-flex items-center gap-1.5 px-1.5 py-0.5 border rounded font-mono text-[10px] tracking-widest', config.color, className)}>
      <span className={clsx('w-1.5 h-1.5 rounded-full', config.dot, status === 'running' && 'animate-pulse')} />
      {label ?? config.label}
    </span>
  )
}
```

- [ ] **Step 9: 创建 src/components/Toast.tsx**

```tsx
'use client'

import { motion, AnimatePresence } from 'framer-motion'
import { clsx } from 'clsx'
import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'

type ToastType = 'success' | 'error' | 'warning' | 'info'

interface Toast {
  id: string
  type: ToastType
  message: string
}

interface ToastContextValue {
  addToast: (type: ToastType, message: string) => void
}

const ToastContext = createContext<ToastContextValue>({ addToast: () => {} })

export function useToast() {
  return useContext(ToastContext)
}

const typeStyles: Record<ToastType, string> = {
  success: 'border-[var(--rise)] text-[var(--rise)]',
  error: 'border-[var(--fall)] text-[var(--fall)]',
  warning: 'border-[var(--warn)] text-[var(--warn)]',
  info: 'border-[var(--accent)] text-[var(--accent)]',
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const addToast = useCallback((type: ToastType, message: string) => {
    const id = String(Date.now())
    setToasts((prev) => [...prev, { id, type, message }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 4000)
  }, [])

  return (
    <ToastContext.Provider value={{ addToast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-[10000] flex flex-col gap-2">
        <AnimatePresence>
          {toasts.map((toast) => (
            <motion.div
              key={toast.id}
              initial={{ opacity: 0, x: 50, scale: 0.95 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 50, scale: 0.95 }}
              transition={{ duration: 0.2 }}
              className={clsx(
                'px-4 py-2 bg-[var(--bg-raised)] border rounded-[var(--r-md)] font-mono text-xs tracking-wide shadow-lg',
                typeStyles[toast.type],
              )}
            >
              {toast.message}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  )
}
```

- [ ] **Step 10: 创建 src/index.ts**

```typescript
export { Panel } from './components/Panel'
export { MetricCard } from './components/MetricCard'
export { PriceDisplay } from './components/PriceDisplay'
export { StatusBadge } from './components/StatusBadge'
export { ToastProvider, useToast } from './components/Toast'
export * from './theme'
```

- [ ] **Step 11: 安装依赖并验证**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system/terminal" && pnpm install && pnpm --filter @qc/ui typecheck
```

Expected: 类型检查通过

- [ ] **Step 12: Commit**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system" && git add terminal/packages/ui/ && git commit -m "feat: add @qc/ui design system with Panel, MetricCard, PriceDisplay, StatusBadge, Toast"
```

---

## Task 5: Next.js 15 主应用 — 项目骨架

**Files:**
- Create: `terminal/apps/terminal/package.json`
- Create: `terminal/apps/terminal/tsconfig.json`
- Create: `terminal/apps/terminal/next.config.ts`
- Create: `terminal/apps/terminal/tailwind.config.ts`
- Create: `terminal/apps/terminal/postcss.config.mjs`
- Create: `terminal/apps/terminal/src/app/layout.tsx`
- Create: `terminal/apps/terminal/src/app/globals.css`
- Create: `terminal/apps/terminal/src/shared/lib/cn.ts`
- Create: `terminal/apps/terminal/src/shared/lib/format.ts`

- [ ] **Step 1: 创建 package.json**

```json
{
  "name": "@qc/terminal",
  "version": "0.0.1",
  "private": true,
  "scripts": {
    "dev": "next dev --turbopack",
    "build": "next build",
    "start": "next start",
    "lint": "next lint",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "next": "^15.3.0",
    "react": "^19.1.0",
    "react-dom": "^19.1.0",
    "@qc/types": "workspace:*",
    "@qc/ui": "workspace:*",
    "@qc/ws": "workspace:*",
    "zustand": "^5.0.0",
    "@tanstack/react-query": "^5.80.0",
    "axios": "^1.9.0",
    "framer-motion": "^12.0.0",
    "react-mosaic-component": "^6.1.0",
    "clsx": "^2.1.1",
    "tailwind-merge": "^3.0.0"
  },
  "devDependencies": {
    "typescript": "^5.7.0",
    "@types/react": "^19.1.0",
    "@types/react-dom": "^19.1.0",
    "tailwindcss": "^4.1.0",
    "@tailwindcss/postcss": "^4.1.0"
  }
}
```

- [ ] **Step 2: 创建 tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": {
      "@/*": ["./src/*"],
      "@qc/types": ["../../packages/types/src"],
      "@qc/ui": ["../../packages/ui/src"],
      "@qc/ws": ["../../packages/ws-client/src"]
    }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 3: 创建 next.config.ts**

```typescript
import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ['@qc/ui', '@qc/ws', '@qc/types'],
  async rewrites() {
    const backend = process.env.BACKEND_URL ?? 'http://localhost:8081'
    return [
      { source: '/api/:path*', destination: `${backend}/api/:path*` },
    ]
  },
}

export default nextConfig
```

- [ ] **Step 4: 创建 tailwind.config.ts**

```typescript
import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './src/**/*.{ts,tsx}',
    '../../packages/ui/src/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        'bg-void': '#050507',
        'bg-surface': '#0a0a0f',
        'bg-raised': '#12121a',
        'bg-overlay': '#1a1a24',
        'text-primary': '#e8e8f0',
        'text-secondary': '#9898a8',
        'text-muted': '#585868',
        accent: '#3b82f6',
        rise: '#22c55e',
        fall: '#ef4444',
        warn: '#f59e0b',
        'border-hair': '#1a1a24',
        'border-dim': '#252530',
        'border-mid': '#353545',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"SF Mono"', 'monospace'],
      },
    },
  },
  plugins: [],
}

export default config
```

- [ ] **Step 5: 创建 postcss.config.mjs**

```javascript
const config = {
  plugins: {
    '@tailwindcss/postcss': {},
  },
}

export default config
```

- [ ] **Step 6: 创建 src/app/globals.css**

```css
@import 'tailwindcss';

:root {
  --bg-void: #050507;
  --bg-surface: #0a0a0f;
  --bg-raised: #12121a;
  --bg-overlay: #1a1a24;
  --text-primary: #e8e8f0;
  --text-secondary: #9898a8;
  --text-muted: #585868;
  --text-tertiary: #383848;
  --accent: #3b82f6;
  --accent-muted: #1e3a5f;
  --rise: #22c55e;
  --rise-muted: #166534;
  --rise-rgb: 34,197,94;
  --fall: #ef4444;
  --fall-muted: #7f1d1d;
  --fall-rgb: 239,68,68;
  --warn: #f59e0b;
  --warn-muted: #78350f;
  --border-hair: #1a1a24;
  --border-dim: #252530;
  --border-mid: #353545;
  --r-sm: 4px;
  --r-md: 6px;
  --r-lg: 8px;
  --r-xl: 12px;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html {
  color-scheme: dark;
}

body {
  background: var(--bg-void);
  color: var(--text-primary);
  font-family: 'Inter', -apple-system, system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  overflow: hidden;
}

::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--border-mid);
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--text-muted);
}

::selection {
  background: rgba(59, 130, 246, 0.3);
}

input, select, textarea {
  font-family: inherit;
}

.mono {
  font-family: 'JetBrains Mono', 'SF Mono', 'Fira Code', monospace;
}

.tabular-nums {
  font-variant-numeric: tabular-nums;
}

@keyframes flash-rise {
  0% { background: rgba(34,197,94,0.2); }
  100% { background: transparent; }
}

@keyframes flash-fall {
  0% { background: rgba(239,68,68,0.2); }
  100% { background: transparent; }
}

.flash-rise { animation: flash-rise 0.3s ease-out; }
.flash-fall { animation: flash-fall 0.3s ease-out; }
```

- [ ] **Step 7: 创建 src/shared/lib/cn.ts**

```typescript
import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
```

- [ ] **Step 8: 创建 src/shared/lib/format.ts**

```typescript
export function formatPrice(price: number, decimals = 2): string {
  return price.toFixed(decimals)
}

export function formatPct(pct: number, decimals = 2): string {
  const sign = pct >= 0 ? '+' : ''
  return `${sign}${pct.toFixed(decimals)}%`
}

export function formatVolume(vol: number): string {
  if (vol >= 1e8) return `${(vol / 1e8).toFixed(2)}亿`
  if (vol >= 1e4) return `${(vol / 1e4).toFixed(2)}万`
  return vol.toFixed(0)
}

export function formatAmount(amount: number): string {
  if (amount >= 1e12) return `${(amount / 1e12).toFixed(2)}万亿`
  if (amount >= 1e8) return `${(amount / 1e8).toFixed(2)}亿`
  if (amount >= 1e4) return `${(amount / 1e4).toFixed(2)}万`
  return amount.toFixed(2)
}

export function formatTime(ts: number | string): string {
  const d = typeof ts === 'string' ? new Date(ts) : new Date(ts)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
```

- [ ] **Step 9: 创建 src/app/layout.tsx**

```tsx
import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'QuantCore Terminal',
  description: 'Institutional-grade quantitative trading terminal',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className="dark">
      <body className="bg-bg-void text-text-primary antialiased">
        {children}
      </body>
    </html>
  )
}
```

- [ ] **Step 10: 安装依赖并验证构建**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system/terminal" && pnpm install && pnpm --filter @qc/terminal build
```

Expected: Next.js 构建成功

- [ ] **Step 11: Commit**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system" && git add terminal/apps/terminal/ && git commit -m "feat: scaffold Next.js 15 terminal app with TailwindCSS and design tokens"
```

---

## Task 6: Zustand Stores + TanStack Query Providers

**Files:**
- Create: `terminal/apps/terminal/src/entities/stock/model/store.ts`
- Create: `terminal/apps/terminal/src/entities/stock/index.ts`
- Create: `terminal/apps/terminal/src/entities/position/model/store.ts`
- Create: `terminal/apps/terminal/src/entities/position/index.ts`
- Create: `terminal/apps/terminal/src/entities/strategy/model/store.ts`
- Create: `terminal/apps/terminal/src/entities/strategy/index.ts`
- Create: `terminal/apps/terminal/src/providers/query-provider.tsx`
- Create: `terminal/apps/terminal/src/providers/ws-provider.tsx`
- Create: `terminal/apps/terminal/src/providers/theme-provider.tsx`

- [ ] **Step 1: 创建 stock store**

```typescript
// src/entities/stock/model/store.ts
import { create } from 'zustand'
import type { StockQuote, DepthData, TradeRecord } from '@qc/types'

interface MarketState {
  quotes: Record<string, StockQuote>
  depths: Record<string, DepthData>
  recentTrades: Record<string, TradeRecord[]>
  updateQuote: (symbol: string, quote: Partial<StockQuote>) => void
  updateDepth: (symbol: string, depth: DepthData) => void
  appendTrade: (symbol: string, trade: TradeRecord) => void
}

export const useMarketStore = create<MarketState>((set) => ({
  quotes: {},
  depths: {},
  recentTrades: {},
  updateQuote: (symbol, quote) =>
    set((state) => ({
      quotes: {
        ...state.quotes,
        [symbol]: { ...state.quotes[symbol], ...quote } as StockQuote,
      },
    })),
  updateDepth: (symbol, depth) =>
    set((state) => ({
      depths: { ...state.depths, [symbol]: depth },
    })),
  appendTrade: (symbol, trade) =>
    set((state) => {
      const trades = [...(state.recentTrades[symbol] ?? []), trade].slice(-100)
      return { recentTrades: { ...state.recentTrades, [symbol]: trades } }
    }),
}))
```

- [ ] **Step 2: 创建 stock index.ts**

```typescript
export { useMarketStore } from './model/store'
```

- [ ] **Step 3: 创建 position store**

```typescript
// src/entities/position/model/store.ts
import { create } from 'zustand'
import type { Position, Order } from '@qc/types'

interface TradingState {
  positions: Position[]
  orders: Order[]
  totalAssets: number
  setPositions: (positions: Position[]) => void
  setOrders: (orders: Order[]) => void
  setTotalAssets: (total: number) => void
}

export const useTradingStore = create<TradingState>((set) => ({
  positions: [],
  orders: [],
  totalAssets: 0,
  setPositions: (positions) => set({ positions }),
  setOrders: (orders) => set({ orders }),
  setTotalAssets: (totalAssets) => set({ totalAssets }),
}))
```

- [ ] **Step 4: 创建 position index.ts**

```typescript
export { useTradingStore } from './model/store'
```

- [ ] **Step 5: 创建 strategy store**

```typescript
// src/entities/strategy/model/store.ts
import { create } from 'zustand'
import type { Strategy } from '@qc/types'

interface StrategyState {
  strategies: Strategy[]
  setStrategies: (strategies: Strategy[]) => void
  updateStrategy: (id: string, patch: Partial<Strategy>) => void
}

export const useStrategyStore = create<StrategyState>((set) => ({
  strategies: [],
  setStrategies: (strategies) => set({ strategies }),
  updateStrategy: (id, patch) =>
    set((state) => ({
      strategies: state.strategies.map((s) => (s.id === id ? { ...s, ...patch } : s)),
    })),
}))
```

- [ ] **Step 6: 创建 strategy index.ts**

```typescript
export { useStrategyStore } from './model/store'
```

- [ ] **Step 7: 创建 query-provider.tsx**

```tsx
'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'

export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5_000,
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      }),
  )

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}
```

- [ ] **Step 8: 创建 ws-provider.tsx**

```tsx
'use client'

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { wsClient } from '@qc/ws'

type WSStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

interface WSContextValue {
  status: WSStatus
}

const WSContext = createContext<WSContextValue>({ status: 'disconnected' })

export function useWSStatus() {
  return useContext(WSContext)
}

export function WSProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<WSStatus>('disconnected')

  useEffect(() => {
    const wsUrl = process.env.NEXT_PUBLIC_WS_URL ?? `ws://${window.location.host}/ws`
    wsClient.connect(wsUrl)

    const unsub = wsClient.onStatus(setStatus)
    return () => {
      unsub()
      wsClient.disconnect()
    }
  }, [])

  return <WSContext.Provider value={{ status }}>{children}</WSContext.Provider>
}
```

- [ ] **Step 9: 创建 theme-provider.tsx**

```tsx
'use client'

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

type Theme = 'dark' | 'light' | 'system'
type ResolvedTheme = 'dark' | 'light'

interface ThemeContextValue {
  theme: ResolvedTheme
  mode: Theme
  setMode: (mode: Theme) => void
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: 'dark',
  mode: 'dark',
  setMode: () => {},
})

export function useTheme() {
  return useContext(ThemeContext)
}

function getSystemPreference(): ResolvedTheme {
  if (typeof window === 'undefined') return 'dark'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function resolveTheme(mode: Theme): ResolvedTheme {
  return mode === 'system' ? getSystemPreference() : mode
}

const STORAGE_KEY = 'quantcore-theme'

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<Theme>(() => {
    if (typeof window === 'undefined') return 'dark'
    const stored = localStorage.getItem(STORAGE_KEY) as Theme | null
    return stored === 'system' || stored === 'light' ? stored : 'dark'
  })
  const [theme, setTheme] = useState<ResolvedTheme>(() => resolveTheme(mode))

  useEffect(() => {
    const resolved = resolveTheme(mode)
    setTheme(resolved)
    document.documentElement.setAttribute('data-theme', resolved)
    localStorage.setItem(STORAGE_KEY, mode)
  }, [mode])

  useEffect(() => {
    if (mode !== 'system') return
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = (e: MediaQueryListEvent) => {
      const resolved = e.matches ? 'dark' : 'light'
      setTheme(resolved)
      document.documentElement.setAttribute('data-theme', resolved)
    }
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [mode])

  const setMode = (m: Theme) => setModeState(m)

  return (
    <ThemeContext.Provider value={{ theme, mode, setMode }}>
      {children}
    </ThemeContext.Provider>
  )
}
```

- [ ] **Step 10: 更新 root layout 集成 providers**

```tsx
// src/app/layout.tsx
import type { Metadata } from 'next'
import { QueryProvider } from '@/providers/query-provider'
import { WSProvider } from '@/providers/ws-provider'
import { ThemeProvider } from '@/providers/theme-provider'
import { ToastProvider } from '@qc/ui'
import './globals.css'

export const metadata: Metadata = {
  title: 'QuantCore Terminal',
  description: 'Institutional-grade quantitative trading terminal',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className="dark">
      <body className="bg-bg-void text-text-primary antialiased">
        <QueryProvider>
          <WSProvider>
            <ThemeProvider>
              <ToastProvider>
                {children}
              </ToastProvider>
            </ThemeProvider>
          </WSProvider>
        </QueryProvider>
      </body>
    </html>
  )
}
```

- [ ] **Step 11: 验证构建**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system/terminal" && pnpm --filter @qc/terminal build
```

Expected: 构建成功

- [ ] **Step 12: Commit**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system" && git add terminal/ && git commit -m "feat: add Zustand stores, TanStack Query, WS and Theme providers"
```

---

## Task 7: 认证流程 + API 客户端

**Files:**
- Create: `terminal/apps/terminal/src/shared/api/client.ts`
- Create: `terminal/apps/terminal/src/shared/api/index.ts`
- Create: `terminal/apps/terminal/src/features/auth/model/use-auth.ts`
- Create: `terminal/apps/terminal/src/features/auth/ui/login-form.tsx`
- Create: `terminal/apps/terminal/src/features/auth/index.ts`
- Create: `terminal/apps/terminal/src/app/(auth)/layout.tsx`
- Create: `terminal/apps/terminal/src/app/(auth)/login/page.tsx`

- [ ] **Step 1: 创建 API 客户端**

```typescript
// src/shared/api/client.ts
import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('auth_token') || localStorage.getItem('auth_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      sessionStorage.removeItem('auth_token')
      localStorage.removeItem('auth_token')
      sessionStorage.removeItem('refresh_token')
      localStorage.removeItem('refresh_token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  },
)

export { api }
```

- [ ] **Step 2: 创建 API index**

```typescript
export { api } from './client'
```

- [ ] **Step 3: 创建 use-auth.ts**

```typescript
// src/features/auth/model/use-auth.ts
import { create } from 'zustand'
import { api } from '@/shared/api'

interface AuthState {
  token: string | null
  user: { id: string; username: string; email: string } | null
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  token: typeof window !== 'undefined' ? sessionStorage.getItem('auth_token') : null,
  user: null,
  isAuthenticated: typeof window !== 'undefined' ? !!sessionStorage.getItem('auth_token') : false,

  login: async (username, password) => {
    const { data } = await api.post('/auth/login', { username, password })
    const token = data.token as string
    sessionStorage.setItem('auth_token', token)
    set({ token, user: data.user, isAuthenticated: true })
  },

  logout: () => {
    sessionStorage.removeItem('auth_token')
    localStorage.removeItem('auth_token')
    set({ token: null, user: null, isAuthenticated: false })
  },
}))
```

- [ ] **Step 4: 创建 login-form.tsx**

```tsx
'use client'

import { useState } from 'react'
import { useAuthStore } from '../model/use-auth'
import { useRouter } from 'next/navigation'

export function LoginForm() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const login = useAuthStore((s) => s.login)
  const router = useRouter()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(username, password)
      router.push('/dashboard')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4 w-full max-w-sm">
      <div className="flex flex-col gap-1">
        <label className="font-mono text-[10px] tracking-widest text-[var(--text-muted)] uppercase">Username</label>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="px-3 py-2 bg-[var(--bg-void)] border border-[var(--border-mid)] rounded-[var(--r-md)] text-[var(--text-primary)] font-mono text-sm outline-none focus:border-[var(--accent)] transition-colors"
          autoComplete="username"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="font-mono text-[10px] tracking-widest text-[var(--text-muted)] uppercase">Password</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="px-3 py-2 bg-[var(--bg-void)] border border-[var(--border-mid)] rounded-[var(--r-md)] text-[var(--text-primary)] font-mono text-sm outline-none focus:border-[var(--accent)] transition-colors"
          autoComplete="current-password"
        />
      </div>
      {error && <p className="text-[var(--fall)] font-mono text-xs">{error}</p>}
      <button
        type="submit"
        disabled={loading || !username || !password}
        className="px-4 py-2 bg-[var(--accent)] text-white font-mono text-xs tracking-widest uppercase rounded-[var(--r-md)] hover:bg-[var(--accent)]/80 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {loading ? 'CONNECTING...' : 'LOGIN'}
      </button>
    </form>
  )
}
```

- [ ] **Step 5: 创建 auth index.ts**

```typescript
export { useAuthStore } from './model/use-auth'
export { LoginForm } from './ui/login-form'
```

- [ ] **Step 6: 创建 (auth)/layout.tsx**

```tsx
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg-void)]">
      {children}
    </div>
  )
}
```

- [ ] **Step 7: 创建 login/page.tsx**

```tsx
import { LoginForm } from '@/features/auth'

export default function LoginPage() {
  return (
    <div className="flex flex-col items-center gap-8">
      <div className="flex flex-col items-center gap-2">
        <h1 className="font-mono text-2xl font-bold tracking-wider text-[var(--text-primary)]">
          QUANTCORE
        </h1>
        <p className="font-mono text-xs tracking-widest text-[var(--text-muted)] uppercase">
          Institutional Trading Terminal
        </p>
      </div>
      <LoginForm />
    </div>
  )
}
```

- [ ] **Step 8: 验证构建**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system/terminal" && pnpm --filter @qc/terminal build
```

Expected: 构建成功

- [ ] **Step 9: Commit**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system" && git add terminal/ && git commit -m "feat: add auth flow with login page and API client"
```

---

## Task 8: Dock 布局系统 + 侧边栏 + 顶栏

**Files:**
- Create: `terminal/apps/terminal/src/widgets/dock-layout/model/use-dock-layout.ts`
- Create: `terminal/apps/terminal/src/widgets/dock-layout/ui/dock-layout.tsx`
- Create: `terminal/apps/terminal/src/widgets/dock-layout/index.ts`
- Create: `terminal/apps/terminal/src/widgets/sidebar/ui/sidebar.tsx`
- Create: `terminal/apps/terminal/src/widgets/sidebar/index.ts`
- Create: `terminal/apps/terminal/src/widgets/topbar/ui/topbar.tsx`
- Create: `terminal/apps/terminal/src/widgets/topbar/index.ts`
- Create: `terminal/apps/terminal/src/app/(terminal)/layout.tsx`
- Create: `terminal/apps/terminal/src/app/(terminal)/page.tsx`
- Create: `terminal/apps/terminal/src/app/(terminal)/dashboard/page.tsx`

- [ ] **Step 1: 创建 use-dock-layout.ts**

```typescript
import { create } from 'zustand'

export type PanelId =
  | 'kline'
  | 'orderbook'
  | 'trade-flow'
  | 'depth-chart'
  | 'strategy-console'
  | 'pnl-dashboard'
  | 'risk-monitor'
  | 'position-table'
  | 'market-heatmap'
  | 'ai-insights'
  | 'backtest'
  | 'alerts'

interface PanelMeta {
  id: PanelId
  title: string
}

export const PANEL_REGISTRY: Record<PanelId, PanelMeta> = {
  'kline': { id: 'kline', title: 'K线图表' },
  'orderbook': { id: 'orderbook', title: '订单簿' },
  'trade-flow': { id: 'trade-flow', title: '成交流' },
  'depth-chart': { id: 'depth-chart', title: '深度图' },
  'strategy-console': { id: 'strategy-console', title: '策略控制台' },
  'pnl-dashboard': { id: 'pnl-dashboard', title: 'PnL仪表盘' },
  'risk-monitor': { id: 'risk-monitor', title: '风控监控' },
  'position-table': { id: 'position-table', title: '持仓列表' },
  'market-heatmap': { id: 'market-heatmap', title: '市场热力图' },
  'ai-insights': { id: 'ai-insights', title: 'AI分析' },
  'backtest': { id: 'backtest', title: '回测系统' },
  'alerts': { id: 'alerts', title: '告警中心' },
}

type LayoutPreset = 'trading' | 'strategy' | 'risk' | 'kline-only'

interface DockLayoutState {
  activePanels: PanelId[]
  preset: LayoutPreset
  setPreset: (preset: LayoutPreset) => void
  addPanel: (id: PanelId) => void
  removePanel: (id: PanelId) => void
}

const PRESETS: Record<LayoutPreset, PanelId[]> = {
  'trading': ['kline', 'orderbook', 'trade-flow'],
  'strategy': ['kline', 'strategy-console', 'pnl-dashboard'],
  'risk': ['risk-monitor', 'position-table', 'alerts'],
  'kline-only': ['kline'],
}

export const useDockLayout = create<DockLayoutState>((set) => ({
  activePanels: PRESETS.trading,
  preset: 'trading',
  setPreset: (preset) => set({ preset, activePanels: PRESETS[preset] }),
  addPanel: (id) => set((s) => ({ activePanels: s.activePanels.includes(id) ? s.activePanels : [...s.activePanels, id] })),
  removePanel: (id) => set((s) => ({ activePanels: s.activePanels.filter((p) => p !== id) })),
}))
```

- [ ] **Step 2: 创建 dock-layout.tsx**

```tsx
'use client'

import { useDockLayout, PANEL_REGISTRY, type PanelId } from '../model/use-dock-layout'
import { Panel } from '@qc/ui'
import { clsx } from 'clsx'

const PANEL_COMPONENTS: Record<PanelId, React.ComponentType> = {} as never

function LazyPanelContent({ id }: { id: PanelId }) {
  const Comp = PANEL_COMPONENTS[id]
  if (!Comp) {
    return (
      <div className="flex items-center justify-center h-full text-[var(--text-muted)] font-mono text-xs tracking-widest uppercase">
        {PANEL_REGISTRY[id].title} — COMING SOON
      </div>
    )
  }
  return <Comp />
}

export function DockLayout() {
  const { activePanels, removePanel } = useDockLayout()

  return (
    <div className="flex-1 grid gap-1 p-1 auto-rows-fr" style={{ gridTemplateColumns: `repeat(${Math.min(activePanels.length, 3)}, 1fr)` }}>
      {activePanels.map((id) => (
        <Panel
          key={id}
          title={PANEL_REGISTRY[id].title}
          collapsible
          actions={
            <button
              onClick={() => removePanel(id)}
              className="text-[var(--text-muted)] hover:text-[var(--fall)] transition-colors text-xs"
              aria-label={`Close ${PANEL_REGISTRY[id].title}`}
            >
              ✕
            </button>
          }
        >
          <LazyPanelContent id={id} />
        </Panel>
      ))}
    </div>
  )
}
```

- [ ] **Step 3: 创建 dock-layout index.ts**

```typescript
export { DockLayout } from './ui/dock-layout'
export { useDockLayout, PANEL_REGISTRY, type PanelId } from './model/use-dock-layout'
```

- [ ] **Step 4: 创建 sidebar.tsx**

```tsx
'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { clsx } from 'clsx'

const NAV_ITEMS = [
  { href: '/dashboard', label: 'DASHBOARD', icon: '◈' },
  { href: '/market', label: 'MARKET', icon: '◉' },
  { href: '/portfolio', label: 'PORTFOLIO', icon: '▤' },
  { href: '/strategy', label: 'STRATEGY', icon: '⚡' },
  { href: '/backtest', label: 'BACKTEST', icon: '↺' },
  { href: '/risk', label: 'RISK', icon: '⊘' },
  { href: '/screener', label: 'SCREENER', icon: '⊙' },
  { href: '/settings', label: 'SETTINGS', icon: '⚙' },
]

export function Sidebar() {
  const pathname = usePathname()

  return (
    <nav className="flex flex-col w-14 bg-[var(--bg-surface)] border-r border-[var(--border-hair)] py-2">
      {NAV_ITEMS.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          className={clsx(
            'flex flex-col items-center justify-center gap-0.5 py-2 text-[10px] font-mono tracking-widest transition-colors',
            pathname.startsWith(item.href)
              ? 'text-[var(--accent)] bg-[var(--bg-overlay)]'
              : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-overlay)]',
          )}
          aria-label={item.label}
        >
          <span className="text-base">{item.icon}</span>
          <span>{item.label.slice(0, 3)}</span>
        </Link>
      ))}
    </nav>
  )
}
```

- [ ] **Step 5: 创建 sidebar index.ts**

```typescript
export { Sidebar } from './ui/sidebar'
```

- [ ] **Step 6: 创建 topbar.tsx**

```tsx
'use client'

import { useTheme } from '@/providers/theme-provider'
import { useWSStatus } from '@/providers/ws-provider'
import { useAuthStore } from '@/features/auth'
import { useRouter } from 'next/navigation'
import { clsx } from 'clsx'

export function Topbar() {
  const { mode, setMode } = useTheme()
  const wsStatus = useWSStatus()
  const logout = useAuthStore((s) => s.logout)
  const router = useRouter()

  const statusColor = wsStatus.status === 'connected'
    ? 'bg-[var(--rise)]'
    : wsStatus.status === 'connecting'
      ? 'bg-[var(--warn)]'
      : 'bg-[var(--fall)]'

  return (
    <header className="flex items-center justify-between h-10 px-4 bg-[var(--bg-surface)] border-b border-[var(--border-hair)]">
      <div className="flex items-center gap-3">
        <span className="font-mono text-sm font-bold tracking-wider text-[var(--text-primary)]">QUANTCORE</span>
        <span className="font-mono text-[10px] tracking-widest text-[var(--text-muted)]">TERMINAL</span>
      </div>
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5">
          <span className={clsx('w-1.5 h-1.5 rounded-full', statusColor, wsStatus.status === 'connecting' && 'animate-pulse')} />
          <span className="font-mono text-[10px] tracking-widest text-[var(--text-muted)] uppercase">
            {wsStatus.status}
          </span>
        </div>
        <div className="flex gap-0">
          {(['dark', 'light', 'system'] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={clsx(
                'px-2 py-0.5 font-mono text-[10px] tracking-widest uppercase border transition-colors',
                mode === m
                  ? 'bg-[var(--bg-overlay)] text-[var(--accent)] border-[var(--accent)]'
                  : 'text-[var(--text-muted)] border-[var(--border-dim)] hover:text-[var(--text-secondary)]',
              )}
              aria-label={`Theme: ${m}`}
            >
              {m.slice(0, 1).toUpperCase()}
            </button>
          ))}
        </div>
        <button
          onClick={() => { logout(); router.push('/login') }}
          className="font-mono text-[10px] tracking-widest text-[var(--text-muted)] hover:text-[var(--fall)] uppercase transition-colors"
        >
          LOGOUT
        </button>
      </div>
    </header>
  )
}
```

- [ ] **Step 7: 创建 topbar index.ts**

```typescript
export { Topbar } from './ui/topbar'
```

- [ ] **Step 8: 创建 (terminal)/layout.tsx**

```tsx
import { Sidebar } from '@/widgets/sidebar'
import { Topbar } from '@/widgets/topbar'

export default function TerminalLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex flex-col flex-1 overflow-hidden">
        <Topbar />
        <main className="flex-1 overflow-hidden">
          {children}
        </main>
      </div>
    </div>
  )
}
```

- [ ] **Step 9: 创建 (terminal)/page.tsx**

```typescript
import { redirect } from 'next/navigation'

export default function TerminalRootPage() {
  redirect('/dashboard')
}
```

- [ ] **Step 10: 创建 dashboard/page.tsx**

```tsx
import { DockLayout } from '@/widgets/dock-layout'

export default function DashboardPage() {
  return <DockLayout />
}
```

- [ ] **Step 11: 创建其余页面占位**

为 market, stock/[symbol], strategy, backtest, portfolio, risk, screener, settings 各创建一个 page.tsx，内容为简单的标题页面：

```tsx
export default function XxxPage() {
  return (
    <div className="flex items-center justify-center h-full">
      <span className="font-mono text-sm tracking-widest text-[var(--text-muted)] uppercase">XXX — COMING IN P1-P4</span>
    </div>
  )
}
```

- [ ] **Step 12: 验证构建 + dev 启动**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system/terminal" && pnpm --filter @qc/terminal build
```

Expected: 构建成功

- [ ] **Step 13: Commit**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system" && git add terminal/ && git commit -m "feat: add Dock layout, Sidebar, Topbar, and terminal page structure"
```

---

## Task 9: @qc/gpu PixiJS 渲染包（骨架）

**Files:**
- Create: `terminal/packages/gpu-renderer/package.json`
- Create: `terminal/packages/gpu-renderer/tsconfig.json`
- Create: `terminal/packages/gpu-renderer/src/depth-canvas.tsx`
- Create: `terminal/packages/gpu-renderer/src/heatmap-canvas.tsx`
- Create: `terminal/packages/gpu-renderer/src/index.ts`

- [ ] **Step 1: 创建 package.json**

```json
{
  "name": "@qc/gpu",
  "version": "0.0.1",
  "private": true,
  "main": "./src/index.ts",
  "types": "./src/index.ts",
  "dependencies": {
    "pixi.js": "^8.9.0",
    "@qc/types": "workspace:*",
    "react": "^19.1.0"
  },
  "peerDependencies": {
    "react": "^19.0.0"
  },
  "scripts": {
    "typecheck": "tsc --noEmit"
  }
}
```

- [ ] **Step 2: 创建 tsconfig.json**（同 @qc/ui）

- [ ] **Step 3: 创建 src/depth-canvas.tsx**

```tsx
'use client'

import { useEffect, useRef } from 'react'
import type { DepthData } from '@qc/types'

interface DepthCanvasProps {
  data: DepthData | null
  width?: number
  height?: number
  className?: string
}

export function DepthCanvas({ data, width = 400, height = 300, className }: DepthCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !data) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, width, height)

    const maxBidVol = Math.max(...data.bids.map((l) => l.quantity), 1)
    const maxAskVol = Math.max(...data.asks.map((l) => l.quantity), 1)
    const maxVol = Math.max(maxBidVol, maxAskVol)
    const barHeight = Math.max(1, (height - 20) / Math.max(data.bids.length, data.asks.length))

    data.bids.forEach((level, i) => {
      const barWidth = (level.quantity / maxVol) * (width / 2)
      ctx.fillStyle = 'rgba(34,197,94,0.3)'
      ctx.fillRect(width / 2 - barWidth, 10 + i * barHeight, barWidth, barHeight - 1)
    })

    data.asks.forEach((level, i) => {
      const barWidth = (level.quantity / maxVol) * (width / 2)
      ctx.fillStyle = 'rgba(239,68,68,0.3)'
      ctx.fillRect(width / 2, 10 + i * barHeight, barWidth, barHeight - 1)
    })
  }, [data, width, height])

  return <canvas ref={canvasRef} width={width} height={height} className={className} />
}
```

- [ ] **Step 4: 创建 src/heatmap-canvas.tsx**

```tsx
'use client'

import { useEffect, useRef } from 'react'
import type { HeatmapItem } from '@qc/types'

interface HeatmapCanvasProps {
  items: HeatmapItem[]
  width?: number
  height?: number
  className?: string
}

export function HeatmapCanvas({ items, width = 600, height = 360, className }: HeatmapCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !items.length) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, width, height)

    const total = items.reduce((sum, item) => sum + Math.abs(item.amount), 0)
    const sorted = [...items].sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount))

    let x = 0
    let y = 0
    let rowHeight = height

    for (const item of sorted) {
      const ratio = Math.abs(item.amount) / total
      const w = ratio * width

      if (x + w > width) {
        x = 0
        rowHeight = rowHeight * 0.6
        y += rowHeight
      }

      const alpha = Math.min(Math.abs(item.change_pct) / 5, 1)
      ctx.fillStyle = item.change_pct >= 0
        ? `rgba(34,197,94,${alpha})`
        : `rgba(239,68,68,${alpha})`
      ctx.fillRect(x, y, w - 1, rowHeight - 1)

      if (w > 40) {
        ctx.fillStyle = 'rgba(255,255,255,0.9)'
        ctx.font = '10px monospace'
        ctx.fillText(item.name, x + 4, y + 14)
        const pctStr = `${item.change_pct >= 0 ? '+' : ''}${item.change_pct.toFixed(1)}%`
        ctx.fillText(pctStr, x + 4, y + 26)
      }

      x += w
    }
  }, [items, width, height])

  return <canvas ref={canvasRef} width={width} height={height} className={className} />
}
```

- [ ] **Step 5: 创建 src/index.ts**

```typescript
export { DepthCanvas } from './depth-canvas'
export { HeatmapCanvas } from './heatmap-canvas'
```

- [ ] **Step 6: 验证类型检查**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system/terminal" && pnpm install && pnpm --filter @qc/gpu typecheck
```

Expected: 类型检查通过

- [ ] **Step 7: Commit**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system" && git add terminal/packages/gpu-renderer/ && git commit -m "feat: add @qc/gpu PixiJS renderer package with DepthCanvas and HeatmapCanvas"
```

---

## Task 10: 全量构建验证 + dev 启动测试

- [ ] **Step 1: 全量 Turborepo 构建**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system/terminal" && pnpm install && pnpm build
```

Expected: 所有包和主应用构建成功

- [ ] **Step 2: 类型检查**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system/terminal" && pnpm typecheck
```

Expected: 无类型错误

- [ ] **Step 3: 启动 dev 服务器**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system/terminal" && pnpm dev
```

Expected: Next.js dev 服务器启动，可访问 http://localhost:3000

- [ ] **Step 4: 最终 Commit**

```bash
cd "/Users/fei/Desktop/大三下 /quantitative-trading-system" && git add terminal/ && git commit -m "feat: P0 complete — institutional terminal foundation with Turborepo, Next.js 15, Zustand, TanStack Query, Dock layout, WS client, design system"
```

---

## Self-Review

1. **Spec coverage**: ✅ 第1节（Monorepo）→ Task 1; 第2节（技术栈/WS/Store/Query）→ Task 3,6; 第3节（Dock+设计系统）→ Task 4,8; 第4节（性能）→ Task 9 (GPU骨架); 第5节（API/认证/路由）→ Task 5,7
2. **Placeholder scan**: ✅ 无 TBD/TODO，所有步骤包含完整代码
3. **Type consistency**: ✅ 所有类型引用与 @qc/types 定义一致，store 接口与 provider 对齐
