# P0: 机构级量化交易终端 — 基础架构设计

## 概述

将现有 Vue 3 前端完全重写为基于 Next.js 15 + React 19 的机构级交易终端。后端 FastAPI 保持不变，前端从零搭建。

## 项目分解

| 阶段 | 子项目 | 核心内容 | 依赖 |
|------|--------|---------|------|
| P0 | 基础架构 | Monorepo + Next.js + Zustand + TanStack Query + WS + 设计系统 + Dock布局 | 无 |
| P1 | 实时行情终端 | Tick级数据 + OrderBook + 深度图 + 成交流 + GPU图表 | P0 |
| P2 | 专业K线 + 策略控制台 | TradingView深度定制 + 策略启停 + 参数热更新 + 实时PnL | P0 |
| P3 | 风控 + 回测 | 风险暴露 + 熔断 + 参数优化 + Monte Carlo | P0, P1 |
| P4 | AI分析 + 集成 | AI市场分析 + 因子分析 + E2E测试 + Storybook + CI/CD | P0-P3 |

本文档仅覆盖 P0。

## 关键决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 迁移策略 | 完全重写 | 干净架构，无历史包袱 |
| 项目位置 | 同仓库内新建 `terminal/` | 与后端共存，后续删除 frontend/ |
| K线系统 | TradingView 官方 Charting Library | 功能最完整 |
| 布局系统 | Dock 面板系统（react-mosaic） | 可拖拽、可调整、专业感 |
| Monorepo | Turborepo | 与 Next.js 深度集成 |
| 架构 | Feature-Sliced Design | 严格依赖规则，widget层适配Dock |

## 第1节：项目结构与 Monorepo

### 目录结构

```
quantitative-trading-system/
├── terminal/                          # 新 Next.js 前端
│   ├── turbo.json
│   ├── package.json
│   ├── pnpm-workspace.yaml
│   ├── packages/
│   │   ├── ui/                        # @qc/ui - 设计系统组件
│   │   │   ├── src/
│   │   │   │   ├── components/        # Button, Input, Badge, Panel...
│   │   │   │   ├── theme/             # TailwindCSS 主题 tokens
│   │   │   │   └── index.ts
│   │   │   ├── package.json
│   │   │   └── tsconfig.json
│   │   ├── ws-client/                 # @qc/ws - WebSocket 客户端
│   │   │   ├── src/
│   │   │   │   ├── client.ts          # WS连接管理、重连、心跳
│   │   │   │   ├── streams.ts         # 行情/交易/风控 数据流
│   │   │   │   ├── protocol.ts        # 消息协议编解码
│   │   │   │   └── index.ts
│   │   │   └── package.json
│   │   ├── types/                     # @qc/types - 共享类型
│   │   │   ├── src/
│   │   │   │   ├── market.ts          # StockQuote, KlineBar, Depth...
│   │   │   │   ├── trading.ts         # Order, Position, Trade...
│   │   │   │   ├── strategy.ts        # Strategy, Signal, Backtest...
│   │   │   │   ├── risk.ts            # RiskReport, Exposure...
│   │   │   │   └── index.ts
│   │   │   └── package.json
│   │   └── gpu-renderer/              # @qc/gpu - PixiJS/WebGL 渲染
│   │       ├── src/
│   │       │   ├── depth-canvas.tsx   # 深度图 GPU 渲染
│   │       │   ├── heatmap-canvas.tsx # 热力图 GPU 渲染
│   │       │   └── index.ts
│   │       └── package.json
│   └── apps/
│       └── terminal/                  # 主应用
│           ├── src/
│           │   ├── app/               # FSD App层 - 路由、布局、providers
│           │   ├── pages/             # FSD Pages层 - 页面组合
│           │   ├── widgets/           # FSD Widgets层 - 独立功能面板
│           │   ├── features/          # FSD Features层 - 业务功能
│           │   ├── entities/          # FSD Entities层 - 业务实体
│           │   └── shared/            # FSD Shared层 - 基础设施
│           ├── next.config.ts
│           ├── tailwind.config.ts
│           └── package.json
├── frontend/                          # 旧 Vue 前端（保留到迁移完成）
├── api/                               # Python 后端（不变）
├── core/                              # Python 核心引擎（不变）
└── tests/                             # Python 测试（不变）
```

### FSD 依赖规则

```
app → pages → widgets → features → entities → shared
                                            ↗
                                    packages/* (ui, ws, types, gpu)
```

每层只能引用比自己更内层的模块，禁止反向依赖。

## 第2节：技术栈与核心基础设施

### 技术栈精确版本

| 类别 | 技术 | 版本 | 用途 |
|------|------|------|------|
| 框架 | Next.js | 15.x | App Router, SSR, RSC |
| UI | React | 19.x | Concurrent, Compiler |
| 语言 | TypeScript | 5.7.x | 严格模式 |
| 样式 | TailwindCSS | 4.x | CSS-in-JS零运行时 |
| 动画 | Framer Motion | 12.x | GPU加速动画 |
| 状态 | Zustand | 5.x | 轻量全局状态 |
| 数据 | TanStack Query | 5.x | 服务端状态缓存 |
| WS | 原生 WebSocket | - | 实时数据流 |
| K线 | TradingView Charting Library | 27.x | 专业K线 |
| GPU | PixiJS | 8.x | WebGL渲染 |
| 构建 | Turborepo | 2.x | Monorepo编排 |
| 包管理 | pnpm | 10.x | workspace |

### WebSocket 基础设施（@qc/ws）

核心架构：多路复用单连接 + 自动重连 + 心跳

```typescript
class QuantCoreWS {
  private ws: WebSocket | null
  private reconnectTimer: NodeJS.Timeout | null
  private heartbeatTimer: NodeJS.Timeout | null
  private subscriptions: Map<string, Set<Callback>>
  private messageQueue: EncodedMessage[]

  connect(url: string): void
  subscribe(channel: string, cb: Callback): Unsubscribe
  unsubscribe(channel: string, cb: Callback): void
  send(channel: string, data: unknown): void

  // 频道协议
  // sub:market:SH600519  → 订阅行情
  // sub:depth:SH600519   → 订阅深度
  // sub:trade:SH600519   → 订阅成交流
  // sub:strategy:status  → 订阅策略状态
  // sub:risk:exposure    → 订阅风险暴露
}
```

### Zustand Store 架构

按 FSD entities 层拆分 store，每个实体一个 slice，通过 Zustand 的 slice pattern 组合：

```typescript
interface MarketSlice {
  quotes: Record<string, StockQuote>
  updateQuote: (symbol: string, quote: Partial<StockQuote>) => void
}

interface TradingSlice {
  positions: Position[]
  orders: Order[]
  executeOrder: (order: NewOrder) => Promise<void>
}

interface StrategySlice {
  activeStrategies: Strategy[]
  startStrategy: (id: string) => Promise<void>
  stopStrategy: (id: string) => Promise<void>
}

type RootStore = MarketSlice & TradingSlice & StrategySlice
```

### TanStack Query 策略

| 数据类型 | staleTime | 更新方式 |
|----------|-----------|---------|
| 静态数据（基本面） | 60s | 定时 refetch |
| 实时数据（行情） | 5s | WS推送 → setQueryData |
| 策略数据 | Infinity | 手动刷新 |

## 第3节：Dock 布局系统 + 设计系统

### Dock 布局系统

使用 react-mosaic 实现可拖拽、可调整大小的面板系统。布局状态持久化到 localStorage。

预设布局模板：
- "行情模式": K线60% + OrderBook20% + 成交流20%
- "策略模式": K线40% + 策略控制台30% + PnL30%
- "风控模式": 风险暴露40% + 仓位监控30% + 告警30%
- "全屏K线": K线100%

### 面板注册表

```typescript
interface PanelRegistry {
  'kline':           { title: 'K线图表',   component: LazyKlinePanel }
  'orderbook':       { title: '订单簿',    component: LazyOrderBookPanel }
  'trade-flow':      { title: '成交流',    component: LazyTradeFlowPanel }
  'depth-chart':     { title: '深度图',    component: LazyDepthPanel }
  'strategy-console':{ title: '策略控制台', component: LazyStrategyPanel }
  'pnl-dashboard':   { title: 'PnL仪表盘', component: LazyPnLPanel }
  'risk-monitor':    { title: '风控监控',   component: LazyRiskPanel }
  'position-table':  { title: '持仓列表',   component: LazyPositionPanel }
  'market-heatmap':  { title: '市场热力图', component: LazyHeatmapPanel }
  'ai-insights':     { title: 'AI分析',     component: LazyAIPanel }
  'backtest':        { title: '回测系统',   component: LazyBacktestPanel }
  'alerts':          { title: '告警中心',   component: LazyAlertPanel }
}
```

### 设计系统色彩体系

```css
--bg-void:       #050507    /* 最深背景 */
--bg-surface:    #0a0a0f    /* 面板背景 */
--bg-raised:     #12121a    /* 浮层背景 */
--bg-overlay:    #1a1a24    /* 悬浮背景 */

--text-primary:  #e8e8f0    /* 主文字 */
--text-secondary:#9898a8    /* 次文字 */
--text-muted:    #585868    /* 辅助文字 */

--accent:        #3b82f6    /* 主强调 */
--accent-muted:  #1e3a5f    /* 弱强调 */

--rise:          #22c55e    /* 涨 */
--fall:          #ef4444    /* 跌 */
--warn:          #f59e0b    /* 警告 */

--rise-rgb:      34,197,94
--fall-rgb:      239,68,68
```

### 组件清单

| 组件 | 用途 | 特性 |
|------|------|------|
| Panel | Dock面板容器 | 拖拽手柄、折叠、标题栏 |
| DataGrid | 高性能表格 | 虚拟滚动、增量更新、flash动画 |
| MetricCard | 指标卡片 | 实时数值、趋势箭头、微动画 |
| DepthBar | 深度条 | 买卖双向、比例可视化 |
| PriceDisplay | 价格显示 | 涨跌色、flash、tick动画 |
| OrderBook | 订单簿 | 虚拟滚动、增量更新 |
| TradeFlow | 成交流 | 时间轴、买卖标记 |
| StatusBadge | 状态标签 | 运行/停止/错误 |
| CommandPalette | 命令面板 | Cmd+K 快速操作 |
| Toast | 通知 | 成功/错误/警告 |

## 第4节：性能架构 + 数据流

### 架构图

```
Browser
├── React 19 Compiler (自动 memo)
├── Zustand (本地状态)
├── TanStack Query (服务端状态)
├── @qc/ws (WebSocket 客户端)
│   └── 单连接多路复用 + 自动重连 + 心跳
├── WebWorker 数据处理层
│   ├── 行情数据解析 (不阻塞主线程)
│   ├── 深度数据聚合
│   └── 技术指标计算
└── GPU 渲染层 (@qc/gpu)
    ├── PixiJS 深度图
    ├── PixiJS 热力图
    └── WebGL 粒子效果
```

### 关键性能策略

| 策略 | 实现 | 目标 |
|------|------|------|
| 增量更新 | WS推送 → queryClient.setQueryData 局部更新 | 避免全量refetch |
| 虚拟滚动 | @tanstack/react-virtual 用于表格/订单簿 | 10万行不卡 |
| React Compiler | 自动 memo，无需手动 useMemo/useCallback | 减少不必要渲染 |
| WebWorker | 行情解析、指标计算在 Worker 线程 | 主线程0阻塞 |
| GPU渲染 | PixiJS 渲染深度图/热力图 | 60fps |
| 代码分割 | Next.js 自动 + Dock面板动态 import | 首屏 < 1s |
| Flash动画 | CSS @keyframes + will-change | 价格变动视觉反馈 |
| 批量更新 | WS消息 16ms 批量合并 → 单次 setState | 减少渲染次数 |

### 数据流：行情更新路径

```
WS消息 → @qc/ws 解析 → WebWorker 计算
                           ↓
              Zustand store 更新 (batched)
                           ↓
              订阅组件 re-render (React Compiler 优化)
                           ↓
              DataGrid/PriceDisplay 增量更新
              DepthBar/Heatmap GPU 重绘
```

## 第5节：API对接 + 认证 + 路由

### API 对接

现有后端 FastAPI 保持不变，Next.js 通过 API Routes 代理：

```typescript
// next.config.ts
async rewrites() {
  return [
    { source: '/api/:path*', destination: 'http://localhost:8081/api/:path*' },
    { source: '/ws', destination: 'ws://localhost:8081/ws' },
  ]
}
```

API 客户端基于 axios，与现有后端完全兼容：
- 请求拦截器：注入 auth token (sessionStorage)
- 响应拦截器：401 → 刷新token/跳转登录
- 缓存：TanStack Query 管理
- 取消：AbortController + TanStack Query 内置

### 认证流程

```
登录页 → POST /api/auth/login → token存sessionStorage
                                     ↓
                              Axios拦截器自动注入
                              WS连接时URL参数传递
                              401 → 清除token → 跳转登录
```

### 路由结构

```
app/
├── (auth)/
│   ├── login/page.tsx          # 登录页
│   └── layout.tsx              # 无侧边栏布局
├── (terminal)/
│   ├── layout.tsx              # Dock布局 + 侧边栏
│   ├── page.tsx                # 默认 → 重定向到 /dashboard
│   ├── dashboard/page.tsx      # 仪表盘
│   ├── market/page.tsx         # 行情总览
│   ├── stock/[symbol]/page.tsx # 股票详情
│   ├── strategy/page.tsx       # 策略控制台
│   ├── backtest/page.tsx       # 回测系统
│   ├── portfolio/page.tsx      # 持仓管理
│   ├── risk/page.tsx           # 风控中心
│   ├── screener/page.tsx       # 选股器
│   └── settings/page.tsx       # 设置
└── layout.tsx                  # Root layout (providers)
```

### Providers 层级

```tsx
<QueryClientProvider>
  <WSProvider>
    <ThemeProvider>
      <DockLayoutProvider>
        {children}
      </DockLayoutProvider>
    </ThemeProvider>
  </WSProvider>
</QueryClientProvider>
```
