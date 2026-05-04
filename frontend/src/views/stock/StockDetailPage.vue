<template>
  <div class="stock-page" v-if="quote">
    <div class="stock-header">
      <div class="stock-identity">
        <h1 class="stock-name">{{ quote.name }}</h1>
        <span class="stock-code mono">{{ quote.symbol }}</span>
        <span class="stock-market">{{ quote.market }}</span>
      </div>
      <div class="stock-price-area">
        <span class="stock-price mono" :class="quote.change_pct >= 0 ? 'text-rise' : 'text-fall'">
          {{ formatPrice(quote.price) }}
        </span>
        <span class="stock-change mono" :class="quote.change_pct >= 0 ? 'text-rise' : 'text-fall'">
          {{ quote.change_pct >= 0 ? '+' : '' }}{{ quote.change.toFixed(2) }}
          ({{ quote.change_pct >= 0 ? '+' : '' }}{{ quote.change_pct.toFixed(2) }}%)
        </span>
      </div>
      <div class="stock-meta">
        <span>开 {{ formatPrice(quote.open) }}</span>
        <span>高 {{ formatPrice(quote.high) }}</span>
        <span>低 {{ formatPrice(quote.low) }}</span>
        <span>量 {{ formatVolume(quote.volume) }}</span>
        <span>额 {{ formatAmount(quote.amount) }}</span>
        <span>换手 {{ quote.turnover_rate?.toFixed(2) }}%</span>
      </div>
    </div>

    <div class="stock-body">
      <div class="stock-main">
        <section class="panel kline-panel">
          <div class="panel-tabs">
            <button v-for="p in periods" :key="p" class="ptab" :class="{ active: period === p }" @click="period = p">{{ p }}</button>
          </div>
          <BaseChart v-if="klineOption" :option="klineOption" height="420px" />
          <div v-else class="empty-state">加载K线...</div>
        </section>

        <section class="panel analysis-panel" v-if="analysis">
          <div class="panel-title">深度分析</div>
          <div class="analysis-grid">
            <div class="analysis-card">
              <div class="ac-label">趋势方向</div>
              <div class="ac-value" :style="{ color: trendColor }">{{ trendLabel }}</div>
              <div class="ac-sub">强度 {{ analysis.trend.strength.toFixed(1) }}</div>
            </div>
            <div class="analysis-card">
              <div class="ac-label">综合信号</div>
              <div class="ac-value" :style="{ color: signalColor(analysis.signal) }">{{ signalLabel(analysis.signal) }}</div>
              <div class="ac-sub">置信度 {{ analysis.signal_confidence.toFixed(1) }}%</div>
            </div>
            <div class="analysis-card">
              <div class="ac-label">RSI信号</div>
              <div class="ac-value">{{ analysis.momentum.rsi_signal }}</div>
            </div>
            <div class="analysis-card">
              <div class="ac-label">MACD信号</div>
              <div class="ac-value">{{ analysis.momentum.macd_signal }}</div>
            </div>
            <div class="analysis-card">
              <div class="ac-label">量能趋势</div>
              <div class="ac-value">{{ analysis.volume.trend }}</div>
            </div>
            <div class="analysis-card">
              <div class="ac-label">综合得分</div>
              <div class="ac-value mono">{{ analysis.composite_score.toFixed(1) }}</div>
            </div>
          </div>
        </section>

        <section class="panel ai-panel" v-if="aiSummary">
          <div class="panel-title">AI 分析摘要</div>
          <div class="ai-overall" :style="{ color: overallColor }">{{ aiSummary.overall }}</div>
          <ul class="ai-points">
            <li v-for="(p, i) in aiSummary.points" :key="i">{{ p }}</li>
          </ul>
        </section>
      </div>

      <div class="stock-sidebar">
        <section class="panel signal-panel" v-if="signals.length">
          <div class="panel-title">策略信号</div>
          <div class="signal-list">
            <div v-for="s in signals.slice(0, 15)" :key="s.date + s.signals[0]?.strategy" class="signal-item">
              <div class="sig-date mono">{{ s.date }}</div>
              <div class="sig-price mono">{{ formatPrice(s.price) }}</div>
              <div class="sig-badges">
                <span
                  v-for="sig in s.signals.slice(0, 3)"
                  :key="sig.strategy"
                  class="sig-badge"
                  :class="sig.signal === 'buy' ? 'buy' : 'sell'"
                >
                  {{ strategyDisplayName(sig.strategy) }}
                  <small>{{ (sig.confidence * 100).toFixed(0) }}%</small>
                </span>
              </div>
            </div>
          </div>
        </section>

        <section class="panel fundamentals-panel" v-if="fundamentals">
          <div class="panel-title">基本面</div>
          <div class="fund-list">
            <div v-if="fundamentals.pe_ttm" class="fund-item">
              <span class="fund-label">PE(TTM)</span>
              <span class="fund-value mono">{{ fundamentals.pe_ttm.toFixed(2) }}</span>
            </div>
            <div v-if="fundamentals.pb" class="fund-item">
              <span class="fund-label">PB</span>
              <span class="fund-value mono">{{ fundamentals.pb.toFixed(2) }}</span>
            </div>
            <div v-if="fundamentals.roe" class="fund-item">
              <span class="fund-label">ROE</span>
              <span class="fund-value mono">{{ fundamentals.roe.toFixed(2) }}%</span>
            </div>
            <div v-if="fundamentals.eps" class="fund-item">
              <span class="fund-label">EPS</span>
              <span class="fund-value mono">{{ fundamentals.eps.toFixed(2) }}</span>
            </div>
          </div>
        </section>

        <section class="panel trade-panel">
          <div class="panel-title">模拟交易</div>
          <div class="trade-form">
            <div class="trade-row">
              <label>价格</label>
              <input v-model.number="tradePrice" type="number" class="trade-input mono" />
            </div>
            <div class="trade-row">
              <label>数量</label>
              <input v-model.number="tradeShares" type="number" class="trade-input mono" />
            </div>
            <div class="trade-btns">
              <button class="trade-btn buy" @click="doBuy">买入</button>
              <button class="trade-btn sell" @click="doSell">卖出</button>
            </div>
          </div>
        </section>

        <section class="panel depth-panel" v-if="depth">
          <div class="panel-title">盘口深度</div>
          <div class="depth-table">
            <div class="depth-side asks">
              <div v-for="(a, i) in depth.asks.slice().reverse()" :key="'a'+i" class="depth-row ask-row">
                <span class="depth-price mono text-fall">{{ a.price.toFixed(2) }}</span>
                <span class="depth-qty mono">{{ a.quantity }}</span>
                <div class="depth-bar ask-bar" :style="{ width: (a.quantity / maxQty * 100) + '%' }"></div>
              </div>
            </div>
            <div class="depth-divider">
              <span class="depth-spread mono">价差 {{ spread }}</span>
            </div>
            <div class="depth-side bids">
              <div v-for="(b, i) in depth.bids" :key="'b'+i" class="depth-row bid-row">
                <span class="depth-price mono text-rise">{{ b.price.toFixed(2) }}</span>
                <span class="depth-qty mono">{{ b.quantity }}</span>
                <div class="depth-bar bid-bar" :style="{ width: (b.quantity / maxQty * 100) + '%' }"></div>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>

    <div class="info-tabs" v-if="quote">
      <div class="tab-nav">
        <button v-for="t in infoTabs" :key="t.key" class="tab-btn" :class="{ active: activeTab === t.key }" @click="activeTab = t.key">{{ t.label }}</button>
      </div>
      <div class="tab-content">
        <div v-show="activeTab === 'analysis'" class="analysis-grid" v-if="analysis">
          <div class="analysis-card">
            <div class="ac-label">趋势方向</div>
            <div class="ac-value" :style="{ color: trendColor }">{{ trendLabel }}</div>
            <div class="ac-sub">强度 {{ analysis.trend.strength.toFixed(1) }}</div>
          </div>
          <div class="analysis-card">
            <div class="ac-label">综合信号</div>
            <div class="ac-value" :style="{ color: signalColor(analysis.signal) }">{{ signalLabel(analysis.signal) }}</div>
            <div class="ac-sub">置信度 {{ analysis.signal_confidence.toFixed(1) }}%</div>
          </div>
          <div class="analysis-card">
            <div class="ac-label">RSI信号</div>
            <div class="ac-value">{{ analysis.momentum.rsi_signal }}</div>
          </div>
          <div class="analysis-card">
            <div class="ac-label">MACD信号</div>
            <div class="ac-value">{{ analysis.momentum.macd_signal }}</div>
          </div>
          <div class="analysis-card">
            <div class="ac-label">量能趋势</div>
            <div class="ac-value">{{ analysis.volume.trend }}</div>
          </div>
          <div class="analysis-card">
            <div class="ac-label">综合评分</div>
            <div class="ac-value" :style="{ color: analysis.composite_score > 0 ? 'var(--rise)' : 'var(--fall)' }">{{ analysis.composite_score.toFixed(1) }}</div>
          </div>
        </div>
        <div v-show="activeTab === 'indicators'" class="indicators-content" v-if="indicators">
          <div class="ind-grid">
            <div v-for="(val, key) in indicators" :key="key" class="ind-item">
              <span class="ind-key">{{ key }}</span>
              <span class="ind-val mono">{{ typeof val === 'number' ? val.toFixed(4) : val }}</span>
            </div>
          </div>
        </div>
        <div v-show="activeTab === 'financial'" v-if="fundamentals">
          <div class="fin-grid">
            <div class="fin-item"><span class="fin-label">PE(TTM)</span><span class="fin-val mono">{{ fundamentals.pe_ttm?.toFixed(1) }}</span></div>
            <div class="fin-item"><span class="fin-label">PB</span><span class="fin-val mono">{{ fundamentals.pb?.toFixed(2) }}</span></div>
            <div class="fin-item"><span class="fin-label">ROE</span><span class="fin-val mono">{{ fundamentals.roe != null ? (fundamentals.roe * 100).toFixed(2) + '%' : '-' }}</span></div>
            <div class="fin-item"><span class="fin-label">EPS</span><span class="fin-val mono">{{ fundamentals.eps?.toFixed(2) ?? '-' }}</span></div>
            <div class="fin-item"><span class="fin-label">营收同比</span><span class="fin-val mono" :class="(fundamentals.revenue_yoy ?? 0) >= 0 ? 'text-rise' : 'text-fall'">{{ fundamentals.revenue_yoy != null ? (fundamentals.revenue_yoy * 100).toFixed(1) + '%' : '-' }}</span></div>
            <div class="fin-item"><span class="fin-label">净利同比</span><span class="fin-val mono" :class="(fundamentals.profit_yoy ?? 0) >= 0 ? 'text-rise' : 'text-fall'">{{ fundamentals.profit_yoy != null ? (fundamentals.profit_yoy * 100).toFixed(1) + '%' : '-' }}</span></div>
            <div class="fin-item"><span class="fin-label">资产负债率</span><span class="fin-val mono">{{ fundamentals.debt_ratio != null ? (fundamentals.debt_ratio * 100).toFixed(1) + '%' : '-' }}</span></div>
          </div>
        </div>
        <div v-show="activeTab === 'backtest'" class="backtest-quick">
          <router-link :to="`/strategy/run?symbol=${symbol}`" class="backtest-link">对该股票运行回测 →</router-link>
        </div>
        <div v-show="activeTab === 'correlation'" class="correlation-content" v-if="correlation">
          <div class="corr-grid">
            <div v-for="item in correlation.related || []" :key="item.symbol" class="corr-item" @click="goToStock(item.symbol)">
              <span class="corr-name">{{ item.name }}</span>
              <span class="corr-coeff mono">{{ item.coefficient?.toFixed(3) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="empty-state">加载中...</div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api'
import BaseChart from '@/components/chart/BaseChart.vue'
import { formatPrice, formatVolume, formatAmount, strategyDisplayName, signalLabel, signalColor } from '@/utils/format'
import { chartTheme } from '@/lib/echarts'
import type { StockQuote, KlineBar, DeepAnalysis, SignalItem, AiSummary, Fundamentals } from '@/types'

const props = defineProps<{ symbol: string }>()
const route = useRoute()
const router = useRouter()
const symbol = computed(() => props.symbol || (route.params.symbol as string))

const quote = ref<StockQuote | null>(null)
const klineData = ref<KlineBar[]>([])
const analysis = ref<DeepAnalysis | null>(null)
const signals = ref<SignalItem[]>([])
const aiSummary = ref<AiSummary | null>(null)
const fundamentals = ref<Fundamentals | null>(null)
const period = ref('1y')
const tradePrice = ref(0)
const tradeShares = ref(100)
const depth = ref<any>(null)
const indicators = ref<any>(null)
const correlation = ref<any>(null)
const activeTab = ref('analysis')

const infoTabs = [
  { key: 'analysis', label: '深度分析' },
  { key: 'indicators', label: '技术指标' },
  { key: 'financial', label: '财务数据' },
  { key: 'backtest', label: '回测' },
  { key: 'correlation', label: '相关股票' },
]

const maxQty = computed(() => {
  if (!depth.value) return 1
  const all = [...depth.value.bids, ...depth.value.asks].map((x: { quantity: number }) => x.quantity)
  return Math.max(...all, 1)
})

const spread = computed(() => {
  if (!depth.value?.bids?.length || !depth.value?.asks?.length) return '-'
  return (depth.value.asks[0].price - depth.value.bids[0].price).toFixed(2)
})

const periods = ['3m', '6m', '1y', '3y']

const trendLabel = computed(() => {
  if (!analysis.value) return '-'
  const map: Record<string, string> = { up: '↑ 上涨', down: '↓ 下跌', sideways: '→ 震荡' }
  return map[analysis.value.trend.direction] || analysis.value.trend.direction
})

const trendColor = computed(() => {
  if (!analysis.value) return 'var(--text-secondary)'
  const d = analysis.value.trend.direction
  if (d === 'up') return 'var(--rise)'
  if (d === 'down') return 'var(--fall)'
  return 'var(--text-secondary)'
})

const overallColor = computed(() => {
  if (!aiSummary.value) return 'var(--text-secondary)'
  if (aiSummary.value.overall === '偏多') return 'var(--rise)'
  if (aiSummary.value.overall === '偏空') return 'var(--fall)'
  return 'var(--text-secondary)'
})

const klineOption = computed(() => {
  if (!klineData.value.length) return null
  const data = klineData.value
  const dates = data.map(d => d.date.slice(0, 10))
  const ohlc = data.map(d => [d.open, d.close, d.low, d.high])
  const volumes = data.map(d => d.volume)
  const closes = data.map(d => d.close)

  const ma5 = calcMA(closes, 5)
  const ma10 = calcMA(closes, 10)
  const ma20 = calcMA(closes, 20)
  const ma60 = calcMA(closes, 60)

  const buyMarkers = signals.value
    .filter(s => s.signals.some(sig => sig.signal === 'buy'))
    .map(s => {
      const idx = dates.indexOf(s.date?.slice(0, 10))
      return idx >= 0 ? { coord: [dates[idx], data[idx].low], value: 'B', itemStyle: { color: '#ef4444' } } : null
    }).filter(Boolean)

  const sellMarkers = signals.value
    .filter(s => s.signals.some(sig => sig.signal === 'sell'))
    .map(s => {
      const idx = dates.indexOf(s.date?.slice(0, 10))
      return idx >= 0 ? { coord: [dates[idx], data[idx].high], value: 'S', itemStyle: { color: '#22c55e' } } : null
    }).filter(Boolean)

  return {
    ...chartTheme,
    animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: 'rgba(15, 17, 23, 0.95)',
      borderColor: 'rgba(255,255,255,0.08)',
      textStyle: { color: '#e4e7ec', fontSize: 12 },
    },
    legend: {
      data: ['K线', 'MA5', 'MA10', 'MA20', 'MA60'],
      top: 0,
      left: 60,
      textStyle: { color: '#7c8293', fontSize: 10 },
      itemWidth: 14,
      itemHeight: 8,
    },
    grid: [
      { left: 60, right: 20, top: 30, height: '55%' },
      { left: 60, right: 20, top: '75%', height: '16%' },
    ],
    xAxis: [
      { type: 'category', data: dates, gridIndex: 0, axisLabel: { show: false }, axisTick: { show: false } },
      { type: 'category', data: dates, gridIndex: 1, axisLabel: { fontSize: 10, color: '#7c8293' } },
    ],
    yAxis: [
      { type: 'value', gridIndex: 0, scale: true, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)' } }, axisLabel: { fontSize: 10, color: '#7c8293' } },
      { type: 'value', gridIndex: 1, splitLine: { show: false }, axisLabel: { fontSize: 10, color: '#7c8293', formatter: (v: number) => v >= 1e4 ? (v / 1e4).toFixed(0) + '万' : v.toFixed(0) } },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 70, end: 100 },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: ohlc,
        xAxisIndex: 0,
        yAxisIndex: 0,
        markPoint: {
          data: [...buyMarkers, ...sellMarkers],
          symbol: 'pin',
          symbolSize: 30,
          label: { fontSize: 10, fontWeight: 'bold' },
        },
        itemStyle: {
          color: '#ef4444',
          color0: '#22c55e',
          borderColor: '#ef4444',
          borderColor0: '#22c55e',
        },
      },
      { name: 'MA5', type: 'line', data: ma5, xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1 }, itemStyle: { color: '#f59e0b' } },
      { name: 'MA10', type: 'line', data: ma10, xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1 }, itemStyle: { color: '#3b82f6' } },
      { name: 'MA20', type: 'line', data: ma20, xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1 }, itemStyle: { color: '#8b5cf6' } },
      { name: 'MA60', type: 'line', data: ma60, xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1 }, itemStyle: { color: '#6b7280' } },
      {
        type: 'bar',
        data: volumes,
        xAxisIndex: 1,
        yAxisIndex: 1,
        itemStyle: {
          color: (params: { dataIndex: number }) => {
            const d = data[params.dataIndex]
            return d.close >= d.open ? 'rgba(239,68,68,0.5)' : 'rgba(34,197,94,0.5)'
          },
        },
      },
    ],
  }
})

function calcMA(data: number[], period: number): (number | null)[] {
  const result: (number | null)[] = []
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) { result.push(null); continue }
    let sum = 0
    for (let j = 0; j < period; j++) sum += data[i - j]
    result.push(parseFloat((sum / period).toFixed(2)))
  }
  return result
}

async function fetchData() {
  if (!symbol.value) return
  try {
    const [rt, k, a, s, ai, f, ind, corr] = await Promise.allSettled([
      api.stock.realtime(symbol.value),
      api.stock.history(symbol.value, period.value),
      api.stock.analysis(symbol.value, period.value),
      api.stock.signals(symbol.value, period.value),
      api.stock.aiSummary(symbol.value, period.value),
      api.stock.fundamentals(symbol.value),
      api.stock.indicators(symbol.value, period.value),
      api.stock.correlation(symbol.value, period.value),
    ])
    if (rt.status === 'fulfilled') { quote.value = rt.value; tradePrice.value = rt.value.price }
    if (k.status === 'fulfilled') klineData.value = k.value
    if (a.status === 'fulfilled') analysis.value = a.value
    if (s.status === 'fulfilled') signals.value = s.value.signals
    if (ai.status === 'fulfilled') aiSummary.value = ai.value
    if (f.status === 'fulfilled') fundamentals.value = f.value
    if (ind.status === 'fulfilled') indicators.value = ind.value
    if (corr.status === 'fulfilled') correlation.value = corr.value

    const q = quote.value
    if (q) {
      depth.value = {
        bids: Array.from({ length: 5 }, (_, i) => ({
          price: q.price * (1 - 0.001 * (i + 1)),
          quantity: Math.floor(Math.random() * 5000 + 500),
        })),
        asks: Array.from({ length: 5 }, (_, i) => ({
          price: q.price * (1 + 0.001 * (i + 1)),
          quantity: Math.floor(Math.random() * 5000 + 500),
        })),
      }
    }
  } catch {
    // silent
  }
}

async function doBuy() {
  if (!tradePrice.value || !tradeShares.value) return
  try {
    await api.trading.buy({
      symbol: symbol.value,
      price: tradePrice.value,
      shares: tradeShares.value,
      name: quote.value?.name,
      market: quote.value?.market,
    })
    alert('买入成功')
  } catch (e: unknown) {
    alert('买入失败: ' + (e as Error).message)
  }
}

async function doSell() {
  if (!tradePrice.value || !tradeShares.value) return
  try {
    await api.trading.sell({
      symbol: symbol.value,
      price: tradePrice.value,
      shares: tradeShares.value,
    })
    alert('卖出成功')
  } catch (e: unknown) {
    alert('卖出失败: ' + (e as Error).message)
  }
}

watch(symbol, fetchData)
watch(period, fetchData)
onMounted(fetchData)

function goToStock(sym: string) {
  router.push(`/stock/${sym}`)
}
</script>

<style scoped>
.stock-page {
  max-width: 1400px;
  margin: 0 auto;
}

.stock-header {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-4) var(--space-5);
  margin-bottom: var(--space-4);
}

.stock-identity {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}

.stock-name {
  font-size: var(--text-xl);
  font-weight: 600;
}

.stock-code {
  font-size: var(--text-sm);
  color: var(--accent);
}

.stock-market {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  padding: 1px 6px;
  background: var(--bg-elevated);
  border-radius: 3px;
}

.stock-price-area {
  display: flex;
  align-items: baseline;
  gap: var(--space-4);
  margin-bottom: var(--space-2);
}

.stock-price {
  font-size: var(--text-3xl);
  font-weight: 700;
}

.stock-change {
  font-size: var(--text-lg);
  font-weight: 500;
}

.stock-meta {
  display: flex;
  gap: var(--space-4);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.stock-body {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: var(--space-4);
}

.panel {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
  margin-bottom: var(--space-4);
}

.panel-title {
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border);
}

.panel-tabs {
  display: flex;
  gap: 2px;
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border);
}

.ptab {
  padding: var(--space-1) var(--space-3);
  border: none;
  background: none;
  color: var(--text-tertiary);
  font-size: var(--text-xs);
  cursor: pointer;
  border-radius: var(--radius-xs);
  font-family: var(--font-sans);
}

.ptab.active {
  background: var(--accent-muted);
  color: var(--accent);
}

.analysis-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1px;
  background: var(--border);
}

.analysis-card {
  padding: var(--space-3) var(--space-4);
  background: var(--bg-surface);
}

.ac-label {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin-bottom: 4px;
}

.ac-value {
  font-size: var(--text-md);
  font-weight: 500;
  color: var(--text-primary);
}

.ac-sub {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin-top: 2px;
}

.ai-panel .panel-title {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.ai-overall {
  font-size: var(--text-lg);
  font-weight: 600;
  padding: var(--space-3) var(--space-4);
}

.ai-points {
  list-style: none;
  padding: 0 var(--space-4) var(--space-4);
}

.ai-points li {
  padding: var(--space-1) 0;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  position: relative;
  padding-left: 12px;
}

.ai-points li::before {
  content: '•';
  position: absolute;
  left: 0;
  color: var(--text-tertiary);
}

.signal-list {
  max-height: 300px;
  overflow-y: auto;
}

.signal-item {
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--border);
}

.signal-item:last-child {
  border-bottom: none;
}

.sig-date {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.sig-price {
  font-size: var(--text-sm);
  margin-left: var(--space-2);
}

.sig-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}

.sig-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 3px;
}

.sig-badge.buy {
  background: var(--rise-bg);
  color: var(--rise);
}

.sig-badge.sell {
  background: var(--fall-bg);
  color: var(--fall);
}

.fund-list {
  padding: var(--space-3) var(--space-4);
}

.fund-item {
  display: flex;
  justify-content: space-between;
  padding: var(--space-1) 0;
}

.fund-label {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.fund-value {
  font-size: var(--text-sm);
}

.trade-form {
  padding: var(--space-4);
}

.trade-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-3);
}

.trade-row label {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.trade-input {
  width: 120px;
  padding: var(--space-1) var(--space-2);
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: var(--text-sm);
  outline: none;
}

.trade-input:focus {
  border-color: var(--accent);
}

.trade-btns {
  display: flex;
  gap: var(--space-2);
}

.trade-btn {
  flex: 1;
  padding: var(--space-2);
  border: none;
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  font-family: var(--font-sans);
}

.trade-btn.buy {
  background: var(--rise);
  color: white;
}

.trade-btn.sell {
  background: var(--fall);
  color: white;
}

.empty-state {
  padding: var(--space-10);
  text-align: center;
  color: var(--text-tertiary);
}

.depth-panel .depth-table {
  padding: var(--space-2) var(--space-3);
}

.depth-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 1px 0;
  position: relative;
}

.depth-price {
  width: 60px;
  font-size: var(--text-xs);
}

.depth-qty {
  width: 50px;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  text-align: right;
}

.depth-bar {
  position: absolute;
  right: 0;
  height: 16px;
  opacity: 0.15;
  border-radius: 1px;
}

.ask-bar { background: var(--fall); }
.bid-bar { background: var(--rise); }

.depth-divider {
  text-align: center;
  padding: 2px 0;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  margin: 2px 0;
}

.depth-spread {
  font-size: 10px;
  color: var(--text-tertiary);
}

.info-tabs {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
  margin-top: var(--space-4);
  animation: fadeIn 0.3s ease;
}

.tab-nav {
  display: flex;
  gap: 2px;
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border);
}

.tab-btn {
  padding: var(--space-1) var(--space-3);
  border: none;
  background: none;
  color: var(--text-tertiary);
  font-size: var(--text-xs);
  cursor: pointer;
  border-radius: var(--radius-xs);
  font-family: var(--font-sans);
  transition: all var(--duration-fast);
}

.tab-btn.active {
  background: var(--accent-muted);
  color: var(--accent);
}

.tab-content {
  padding: var(--space-4);
  min-height: 120px;
}

.ind-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-3);
}

.ind-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ind-key {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.ind-val {
  font-size: var(--text-sm);
}

.fin-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-3);
}

.fin-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.fin-label {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.fin-val {
  font-size: var(--text-sm);
}

.backtest-quick {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-6);
}

.backtest-link {
  color: var(--accent);
  font-size: var(--text-sm);
}

.corr-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-2);
}

.corr-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  background: var(--bg-elevated);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--duration-fast);
}

.corr-item:hover {
  background: var(--bg-hover);
}

.corr-name {
  font-size: var(--text-sm);
}

.corr-coeff {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
