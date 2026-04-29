<template>
  <div class="stock-detail-page">
    <div class="page-header">
      <button class="back-btn" @click="$router.back()">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M15 19l-7-7 7-7"/>
        </svg>
      </button>
      <div class="header-info">
        <h1 class="page-title">{{ stockInfo.symbol }}</h1>
        <span class="stock-name">{{ stockInfo.name }}</span>
      </div>
    </div>

    <div class="stock-content">
      <div class="price-section">
        <div class="price-display" :class="{ up: stockInfo.change_pct >= 0, down: stockInfo.change_pct < 0 }">
          <span class="price">{{ stockInfo.price?.toFixed(2) || '-' }}</span>
          <div class="price-change">
            <span>{{ stockInfo.change_pct >= 0 ? '+' : '' }}{{ stockInfo.change_pct?.toFixed(2) || '0' }}%</span>
            <span class="change-value">{{ stockInfo.change >= 0 ? '+' : '' }}{{ stockInfo.change?.toFixed(2) || '0' }}</span>
          </div>
        </div>
        <div class="price-meta">
          <span>开盘: {{ stockInfo.open?.toFixed(2) || '-' }}</span>
          <span>最高: {{ stockInfo.high?.toFixed(2) || '-' }}</span>
          <span>最低: {{ stockInfo.low?.toFixed(2) || '-' }}</span>
          <span>成交量: {{ formatVolume(stockInfo.volume) }}</span>
        </div>
      </div>

      <div class="detail-grid">
        <div class="detail-card">
          <h3>K线图</h3>
          <div class="chart-placeholder">
            <svg viewBox="0 0 400 200" class="kline-svg">
              <defs>
                <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
                  <path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(255,255,255,0.03)" stroke-width="1"/>
                </pattern>
              </defs>
              <rect width="400" height="200" fill="url(#grid)"/>
              <path :d="klinePath" fill="none" stroke="#4d9fff" stroke-width="2"/>
            </svg>
          </div>
        </div>

        <div class="detail-card">
          <h3>基本信息</h3>
          <div class="info-list">
            <div class="info-item">
              <span class="info-label">昨收</span>
              <span class="info-value">{{ stockInfo.last_close?.toFixed(2) || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">换手率</span>
              <span class="info-value">{{ stockInfo.turnover_rate?.toFixed(2) || '0' }}%</span>
            </div>
            <div class="info-item">
              <span class="info-label">成交额</span>
              <span class="info-value">¥{{ formatAmount(stockInfo.amount) }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">市场</span>
              <span class="info-value">{{ marketNames[stockInfo.market] || stockInfo.market }}</span>
            </div>
          </div>
        </div>

        <div class="detail-card">
          <h3>技术指标</h3>
          <div class="indicators-grid">
            <div class="indicator-item">
              <span class="indicator-label">MACD</span>
              <span class="indicator-value" :class="indicators.macd >= 0 ? 'up' : 'down'">
                {{ indicators.macd?.toFixed(2) || '0' }}
              </span>
            </div>
            <div class="indicator-item">
              <span class="indicator-label">RSI</span>
              <span class="indicator-value">{{ indicators.rsi?.toFixed(1) || '50' }}</span>
            </div>
            <div class="indicator-item">
              <span class="indicator-label">KDJ-K</span>
              <span class="indicator-value">{{ indicators.kdj_k?.toFixed(1) || '50' }}</span>
            </div>
            <div class="indicator-item">
              <span class="indicator-label">KDJ-D</span>
              <span class="indicator-value">{{ indicators.kdj_d?.toFixed(1) || '50' }}</span>
            </div>
          </div>
        </div>

        <div class="detail-card trading-card">
          <h3>交易操作</h3>
          <div class="trading-inputs">
            <div class="input-row">
              <input
                v-model.number="orderPrice"
                type="number"
                :placeholder="stockInfo.price?.toFixed(2)"
                class="trade-input"
              />
              <input
                v-model.number="orderShares"
                type="number"
                placeholder="数量（股）"
                class="trade-input"
              />
            </div>
            <div class="trade-buttons">
              <button class="btn btn-success" @click="submitOrder('buy')">买入</button>
              <button class="btn btn-danger" @click="submitOrder('sell')">卖出</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'

const route = useRoute()
const stockInfo = ref<any>({})
const indicators = ref<any>({})
const orderPrice = ref(0)
const orderShares = ref(0)

const marketNames: Record<string, string> = {
  A: 'A股',
  HK: '港股',
  US: '美股',
}

const klinePath = computed(() => {
  const points = Array.from({ length: 50 }, (_, i) => {
    const base = 100 + Math.sin(i * 0.3) * 10
    const noise = (Math.random() - 0.5) * 4
    return base + noise
  })
  const min = Math.min(...points)
  const max = Math.max(...points)
  const range = max - min || 1
  return points.map((v, i) => {
    const x = i * 8
    const y = 200 - ((v - min) / range) * 180 - 10
    return i === 0 ? `M ${x} ${y}` : `L ${x} ${y}`
  }).join(' ')
})

function formatVolume(v: number): string {
  if (!v) return '-'
  if (v >= 10000) {
    return (v / 10000).toFixed(1) + '万手'
  }
  return String(v) + '手'
}

function formatAmount(a: number): string {
  if (!a) return '-'
  if (a >= 10000) {
    return (a / 10000).toFixed(1) + '万'
  }
  return String(a)
}

async function loadStockData() {
  const symbol = route.params.code as string
  const [info, ind] = await Promise.all([
    api.getRealtime(symbol),
    api.getIndicators(symbol),
  ])
  if (info) stockInfo.value = info
  if (ind) indicators.value = ind
  orderPrice.value = stockInfo.value.price || 0
}

function submitOrder(type: string) {
  if (!orderPrice.value || !orderShares.value) return
  if (type === 'buy') {
    api.buy(route.params.code as string, orderPrice.value, orderShares.value)
  } else {
    api.sell(route.params.code as string, orderPrice.value, orderShares.value)
  }
}

let updateTimer: any = null

onMounted(() => {
  loadStockData()
  updateTimer = setInterval(loadStockData, 10000)
})

onUnmounted(() => {
  if (updateTimer) clearInterval(updateTimer)
})
</script>

<style scoped>
.stock-detail-page {
  padding: 24px;
  max-width: 1000px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
}

.back-btn {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255,255,255,0.05);
  border: 1px solid var(--border-color);
  border-radius: 50%;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition);
}

.back-btn:hover {
  background: rgba(255,255,255,0.08);
  color: var(--text-primary);
}

.header-info {
  display: flex;
  flex-direction: column;
}

.page-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
}

.stock-name {
  font-size: 13px;
  color: var(--text-secondary);
}

.price-section {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 24px;
  margin-bottom: 20px;
}

.price-display {
  display: flex;
  align-items: baseline;
  gap: 16px;
  margin-bottom: 16px;
}

.price {
  font-size: 48px;
  font-weight: 700;
  font-family: var(--font-mono);
}

.price-display.up .price {
  color: var(--accent-red);
}

.price-display.down .price {
  color: var(--accent-green);
}

.price-change {
  display: flex;
  flex-direction: column;
  font-family: var(--font-mono);
}

.price-change span:first-child {
  font-size: 20px;
  font-weight: 600;
}

.price-display.up .price-change span:first-child {
  color: var(--accent-red);
}

.price-display.down .price-change span:first-child {
  color: var(--accent-green);
}

.change-value {
  font-size: 14px;
  color: var(--text-secondary);
}

.price-meta {
  display: flex;
  gap: 24px;
  font-size: 13px;
  color: var(--text-secondary);
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.detail-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 20px;
}

.detail-card h3 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 16px;
}

.chart-placeholder {
  background: var(--bg-primary);
  border-radius: var(--radius-sm);
  padding: 8px;
}

.kline-svg {
  width: 100%;
  height: 180px;
}

.info-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.info-item {
  display: flex;
  justify-content: space-between;
  padding: 10px;
  background: rgba(255,255,255,0.03);
  border-radius: var(--radius-sm);
}

.info-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.info-value {
  font-size: 13px;
  font-family: var(--font-mono);
  color: var(--text-primary);
}

.indicators-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.indicator-item {
  background: rgba(255,255,255,0.03);
  border-radius: var(--radius-sm);
  padding: 12px;
  text-align: center;
}

.indicator-label {
  font-size: 11px;
  color: var(--text-tertiary);
  display: block;
  margin-bottom: 4px;
}

.indicator-value {
  font-size: 16px;
  font-weight: 600;
  font-family: var(--font-mono);
  color: var(--text-primary);
}

.indicator-value.up {
  color: var(--accent-red);
}

.indicator-value.down {
  color: var(--accent-green);
}

.trading-card {
  grid-column: span 2;
}

.trading-inputs {
  display: flex;
  gap: 12px;
  align-items: center;
}

.input-row {
  flex: 1;
  display: flex;
  gap: 12px;
}

.trade-input {
  flex: 1;
  height: 40px;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 0 12px;
  color: var(--text-primary);
  font-size: 14px;
  font-family: var(--font-mono);
  outline: none;
}

.trade-input:focus {
  border-color: var(--accent-blue);
}

.trade-buttons {
  display: flex;
  gap: 8px;
}
</style>