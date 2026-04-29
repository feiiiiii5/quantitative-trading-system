<template>
  <div class="dashboard">
    <div class="dashboard-header">
      <h1 class="page-title">市场总览</h1>
      <div class="header-actions">
        <span class="update-time">最后更新: {{ lastUpdate }}</span>
      </div>
    </div>

    <div class="grid grid-2">
      <div class="indices-section">
        <h2 class="section-title">主要指数</h2>
        <div class="indices-grid">
          <div
            v-for="(item, key) in cnIndices"
            :key="key"
            class="index-card"
            :class="{ up: item.change_pct >= 0, down: item.change_pct < 0 }"
          >
            <div class="index-header">
              <span class="index-name">{{ item.name }}</span>
            </div>
            <div class="index-price">{{ item.price.toFixed(2) }}</div>
            <div class="index-change">
              <span :class="item.change_pct >= 0 ? 'up' : 'down'">
                {{ item.change_pct >= 0 ? '+' : '' }}{{ item.change_pct.toFixed(2) }}%
              </span>
              <span class="change-value">{{ item.change >= 0 ? '+' : '' }}{{ item.change.toFixed(2) }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="hk-us-section">
        <h2 class="section-title">港股 / 美股</h2>
        <div class="hk-us-grid">
          <div
            v-for="(item, key) in hkIndices"
            :key="key"
            class="index-card"
            :class="{ up: item.change_pct >= 0, down: item.change_pct < 0 }"
          >
            <div class="index-header">
              <span class="index-name">{{ item.name }}</span>
            </div>
            <div class="index-price">{{ item.price.toFixed(2) }}</div>
            <div class="index-change">
              <span :class="item.change_pct >= 0 ? 'up' : 'down'">
                {{ item.change_pct >= 0 ? '+' : '' }}{{ item.change_pct.toFixed(2) }}%
              </span>
            </div>
          </div>
          <div
            v-for="(item, key) in usIndices"
            :key="key"
            class="index-card"
            :class="{ up: item.change_pct >= 0, down: item.change_pct < 0 }"
          >
            <div class="index-header">
              <span class="index-name">{{ item.name }}</span>
            </div>
            <div class="index-price">{{ item.price.toFixed(2) }}</div>
            <div class="index-change">
              <span :class="item.change_pct >= 0 ? 'up' : 'down'">
                {{ item.change_pct >= 0 ? '+' : '' }}{{ item.change_pct.toFixed(2) }}%
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="grid grid-3">
      <div class="temperature-card">
        <h2 class="section-title">市场温度</h2>
        <div class="temp-display">
          <div class="temp-circle" :style="{ '--temp': temperature }">
            <span class="temp-value">{{ temperature.toFixed(1) }}%</span>
          </div>
          <div class="temp-label">{{ tempLabel }}</div>
        </div>
      </div>

      <div class="watchlist-preview">
        <h2 class="section-title">自选股</h2>
        <div v-if="watchlistQuotes.length" class="quotes-list">
          <div
            v-for="quote in watchlistQuotes"
            :key="quote.symbol"
            class="quote-item"
            :class="{ up: quote.change_pct >= 0, down: quote.change_pct < 0 }"
          >
            <div class="quote-left">
              <span class="quote-code">{{ quote.symbol }}</span>
              <span class="quote-name">{{ quote.name }}</span>
            </div>
            <div class="quote-right">
              <span class="quote-price">{{ quote.price.toFixed(2) }}</span>
              <span :class="quote.change_pct >= 0 ? 'up' : 'down'">
                {{ quote.change_pct >= 0 ? '+' : '' }}{{ quote.change_pct.toFixed(2) }}%
              </span>
            </div>
          </div>
        </div>
        <div v-else class="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
          </svg>
          <p>暂无自选股</p>
          <button class="btn btn-ghost" @click="$router.push('/watchlist')">添加自选</button>
        </div>
      </div>

      <div class="account-summary">
        <h2 class="section-title">账户概览</h2>
        <div class="account-stats">
          <div class="stat-item">
            <span class="stat-label">总资产</span>
            <span class="stat-value">¥{{ formatNumber(account.total_assets || 100000) }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">持仓市值</span>
            <span class="stat-value">¥{{ formatNumber(account.position_value || 50000) }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">可用资金</span>
            <span class="stat-value">¥{{ formatNumber(account.available_cash || 50000) }}</span>
          </div>
          <div class="stat-item" :class="{ up: account.total_pnl >= 0, down: account.total_pnl < 0 }">
            <span class="stat-label">总盈亏</span>
            <span class="stat-value">
              {{ account.total_pnl >= 0 ? '+' : '' }}¥{{ formatNumber(account.total_pnl || 0) }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from '../api'

const overview = ref<any>({
  cn_indices: {},
  hk_indices: {},
  us_indices: {},
  temperature: 50,
})
const watchlist = ref<any>({ symbols: [], quotes: {} })
const account = ref<any>({})
const lastUpdate = ref('')
let updateTimer: any = null

const cnIndices = computed(() => overview.value.cn_indices || {})
const hkIndices = computed(() => overview.value.hk_indices || {})
const usIndices = computed(() => overview.value.us_indices || {})
const temperature = computed(() => overview.value.temperature || 50)

const tempLabel = computed(() => {
  const t = temperature.value
  if (t >= 80) return '过热'
  if (t >= 60) return '偏热'
  if (t >= 40) return '正常'
  if (t >= 20) return '偏冷'
  return '冰冷'
})

const watchlistQuotes = computed(() => {
  return Object.values(watchlist.value.quotes || {}).slice(0, 5)
})

function formatNumber(num: number): string {
  return num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

async function loadData() {
  try {
    const [ov, wl, acc] = await Promise.all([
      api.getMarketOverview(),
      api.getWatchlist(),
      api.getAccount(),
    ])
    if (ov) overview.value = ov
    if (wl) watchlist.value = wl
    if (acc) account.value = acc
    lastUpdate.value = new Date().toLocaleTimeString('zh-CN')
  } catch (e) {
    console.error('Load data error:', e)
  }
}

onMounted(() => {
  loadData()
  updateTimer = setInterval(loadData, 10000)
})

onUnmounted(() => {
  if (updateTimer) clearInterval(updateTimer)
})
</script>

<style scoped>
.dashboard {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}

.dashboard-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.page-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
}

.update-time {
  font-size: 12px;
  color: var(--text-tertiary);
}

.grid {
  display: grid;
  gap: 20px;
  margin-bottom: 20px;
}

.grid-2 {
  grid-template-columns: repeat(2, 1fr);
}

.grid-3 {
  grid-template-columns: repeat(3, 1fr);
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 16px;
}

.indices-grid, .hk-us-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(2, 1fr);
}

.index-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 16px;
  transition: all var(--transition);
}

.index-card:hover {
  border-color: rgba(255,255,255,0.1);
  transform: translateY(-2px);
}

.index-card.up {
  border-color: rgba(244,63,94,0.15);
}

.index-card.down {
  border-color: rgba(52,211,153,0.15);
}

.index-header {
  margin-bottom: 8px;
}

.index-name {
  font-size: 12px;
  color: var(--text-secondary);
}

.index-price {
  font-size: 24px;
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--text-primary);
  margin-bottom: 4px;
}

.index-change {
  display: flex;
  gap: 8px;
  align-items: center;
}

.index-change .up {
  color: var(--accent-red);
}

.index-change .down {
  color: var(--accent-green);
}

.change-value {
  font-size: 12px;
  color: var(--text-secondary);
}

.temperature-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 20px;
}

.temp-display {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.temp-circle {
  width: 100px;
  height: 100px;
  border-radius: 50%;
  background: conic-gradient(
    var(--accent-red) calc(var(--temp) * 1%),
    var(--accent-orange) calc(var(--temp) * 1%),
    var(--accent-green) calc(100%)
  );
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
  position: relative;
}

.temp-circle::before {
  content: '';
  position: absolute;
  inset: 8px;
  background: var(--bg-secondary);
  border-radius: 50%;
}

.temp-value {
  font-size: 20px;
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--text-primary);
  position: relative;
  z-index: 1;
}

.temp-label {
  font-size: 14px;
  color: var(--text-secondary);
}

.watchlist-preview {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 20px;
}

.quotes-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.quote-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  background: rgba(255,255,255,0.03);
  border-radius: var(--radius-sm);
  transition: all 0.15s;
}

.quote-item:hover {
  background: rgba(255,255,255,0.05);
}

.quote-left {
  display: flex;
  gap: 10px;
  align-items: center;
}

.quote-code {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--accent-cyan);
}

.quote-name {
  font-size: 13px;
  color: var(--text-primary);
}

.quote-right {
  display: flex;
  gap: 10px;
  align-items: center;
}

.quote-price {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.quote-right .up {
  color: var(--accent-red);
}

.quote-right .down {
  color: var(--accent-green);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px;
  color: var(--text-tertiary);
}

.empty-state svg {
  margin-bottom: 12px;
  opacity: 0.5;
}

.empty-state p {
  font-size: 13px;
  margin-bottom: 12px;
}

.account-summary {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 20px;
}

.account-stats {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.stat-item {
  background: rgba(255,255,255,0.03);
  border-radius: var(--radius-sm);
  padding: 12px;
}

.stat-label {
  font-size: 11px;
  color: var(--text-tertiary);
  display: block;
  margin-bottom: 4px;
}

.stat-value {
  font-size: 16px;
  font-weight: 600;
  font-family: var(--font-mono);
  color: var(--text-primary);
}

.stat-item.up .stat-value {
  color: var(--accent-red);
}

.stat-item.down .stat-value {
  color: var(--accent-green);
}
</style>