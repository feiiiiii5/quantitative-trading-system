<template>
  <div class="dashboard">
    <div class="hero-section">
      <div class="hero-content">
        <h1 class="hero-title">市场概览</h1>
        <p class="hero-subtitle">实时追踪A股市场动态</p>
      </div>
      <div class="hero-indices" v-if="cnIndices.length">
        <div v-for="idx in cnIndices.slice(0, 6)" :key="idx.code" class="hero-index-card" :class="idx.change_pct >= 0 ? 'rise' : 'fall'">
          <div class="hi-name">{{ idx.name }}</div>
          <div class="hi-price mono">{{ formatPrice(idx.price) }}</div>
          <div class="hi-change mono">{{ idx.change_pct >= 0 ? '+' : '' }}{{ idx.change_pct?.toFixed(2) }}%</div>
        </div>
      </div>
    </div>

    <div class="feature-grid">
      <router-link to="/news" class="feature-card apple-card apple-card-interactive fc-news">
        <div class="fc-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 22h16a2 2 0 002-2V4a2 2 0 00-2-2H8a2 2 0 00-2 2v16a2 2 0 01-2 2zm0 0a2 2 0 01-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8M15 18h-5M10 6h8v4h-8z"/></svg>
        </div>
        <div class="fc-body">
          <div class="fc-title">资讯中心</div>
          <div class="fc-desc">实时财经新闻与市场情绪</div>
        </div>
        <div class="fc-arrow">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
        </div>
      </router-link>

      <router-link to="/screener" class="feature-card apple-card apple-card-interactive fc-screener">
        <div class="fc-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M22 3H2l8 9.46V19l4 2v-8.54L22 3z"/></svg>
        </div>
        <div class="fc-body">
          <div class="fc-title">智能选股</div>
          <div class="fc-desc">多维度条件筛选投资机会</div>
        </div>
        <div class="fc-arrow">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
        </div>
      </router-link>

      <router-link to="/moneyflow" class="feature-card apple-card apple-card-interactive fc-money">
        <div class="fc-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>
        </div>
        <div class="fc-body">
          <div class="fc-title">资金流向</div>
          <div class="fc-desc">追踪主力资金动向</div>
        </div>
        <div class="fc-arrow">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
        </div>
      </router-link>

      <router-link to="/chip" class="feature-card apple-card apple-card-interactive fc-chip">
        <div class="fc-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18M15 3v18"/></svg>
        </div>
        <div class="fc-body">
          <div class="fc-title">筹码分布</div>
          <div class="fc-desc">分析持仓成本与支撑阻力</div>
        </div>
        <div class="fc-arrow">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
        </div>
      </router-link>

      <router-link to="/sector" class="feature-card apple-card apple-card-interactive fc-sector">
        <div class="fc-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/><path d="M2 12h20"/></svg>
        </div>
        <div class="fc-body">
          <div class="fc-title">板块轮动</div>
          <div class="fc-desc">追踪板块资金轮动节奏</div>
        </div>
        <div class="fc-arrow">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
        </div>
      </router-link>

      <router-link to="/strategy" class="feature-card apple-card apple-card-interactive fc-strategy">
        <div class="fc-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
        </div>
        <div class="fc-body">
          <div class="fc-title">策略回测</div>
          <div class="fc-desc">量化策略验证与优化</div>
        </div>
        <div class="fc-arrow">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
        </div>
      </router-link>
    </div>

    <div class="data-grid">
      <section class="data-section heatmap-section apple-card">
        <div class="ds-header">
          <h3 class="ds-title">板块热力图</h3>
          <router-link to="/sector" class="ds-link">查看板块 →</router-link>
        </div>
        <div class="heatmap-wrap" v-if="heatmap.length">
          <div class="heatmap-grid">
            <div
              v-for="item in heatmap.slice(0, 24)"
              :key="item.name"
              class="heatmap-cell"
              :class="item.change_pct >= 0 ? 'rise' : 'fall'"
              :style="{ flex: Math.max(item.value, 1e9), fontSize: item.name.length > 4 ? '10px' : '11px' }"
              :title="`${item.name} ${item.change_pct >= 0 ? '+' : ''}${item.change_pct.toFixed(2)}%`"
            >
              <span class="hm-name">{{ item.name }}</span>
              <span class="hm-pct mono">{{ item.change_pct >= 0 ? '+' : '' }}{{ item.change_pct.toFixed(2) }}</span>
            </div>
          </div>
        </div>
        <div v-else class="ds-empty">暂无数据</div>
      </section>

      <section class="data-section signal-section apple-card">
        <div class="ds-header">
          <h3 class="ds-title">策略信号</h3>
          <span class="ds-count">{{ signals.length }}条</span>
        </div>
        <div class="signal-list" v-if="signals.length">
          <div v-for="sig in signals.slice(0, 8)" :key="sig.id" class="signal-item" @click="goToStock(sig.symbol)">
            <div class="signal-left">
              <span class="signal-badge" :class="sig.type === 'buy' ? 'badge-buy' : 'badge-sell'">
                {{ sig.type === 'buy' ? '买' : '卖' }}
              </span>
              <span class="signal-name">{{ sig.name || sig.symbol }}</span>
            </div>
            <div class="signal-right">
              <span class="signal-strategy">{{ sig.strategy }}</span>
            </div>
          </div>
        </div>
        <div v-else class="ds-empty">暂无信号</div>
      </section>

      <section class="data-section northbound-section apple-card">
        <div class="ds-header">
          <h3 class="ds-title">北向资金</h3>
        </div>
        <div class="northbound-content" v-if="northbound">
          <div class="nb-main">
            <div class="nb-label">今日净流入</div>
            <div class="nb-value mono" :class="northbound.net_inflow >= 0 ? 'text-rise' : 'text-fall'">
              {{ northbound.net_inflow >= 0 ? '+' : '' }}{{ formatNumber(northbound.net_inflow) }}亿
            </div>
          </div>
          <div class="nb-detail">
            <div class="nb-item">
              <span class="nb-item-label">沪股通</span>
              <span class="mono" :class="northbound.sh_inflow >= 0 ? 'text-rise' : 'text-fall'">
                {{ northbound.sh_inflow >= 0 ? '+' : '' }}{{ formatNumber(northbound.sh_inflow) }}亿
              </span>
            </div>
            <div class="nb-item">
              <span class="nb-item-label">深股通</span>
              <span class="mono" :class="northbound.sz_inflow >= 0 ? 'text-rise' : 'text-fall'">
                {{ northbound.sz_inflow >= 0 ? '+' : '' }}{{ formatNumber(northbound.sz_inflow) }}亿
              </span>
            </div>
          </div>
        </div>
        <div v-else class="ds-empty">暂无数据</div>
      </section>

      <section class="data-section anomaly-section apple-card">
        <div class="ds-header">
          <h3 class="ds-title">异动行情</h3>
          <span class="ds-count">{{ anomalies.length }}只</span>
        </div>
        <div class="anomaly-list" v-if="anomalies.length">
          <div v-for="item in anomalies.slice(0, 10)" :key="item.symbol" class="anomaly-item" @click="goToStock(item.symbol)">
            <div class="anomaly-left">
              <span class="anomaly-name">{{ item.name }}</span>
              <span class="anomaly-code mono">{{ item.symbol }}</span>
            </div>
            <div class="anomaly-right">
              <span class="anomaly-pct mono" :class="item.change_pct >= 0 ? 'text-rise' : 'text-fall'">
                {{ item.change_pct >= 0 ? '+' : '' }}{{ item.change_pct.toFixed(2) }}%
              </span>
              <span class="anomaly-reason">{{ item.reason }}</span>
            </div>
          </div>
        </div>
        <div v-else class="ds-empty">暂无异常行情</div>
      </section>

      <section class="data-section account-section apple-card">
        <div class="ds-header">
          <h3 class="ds-title">模拟账户</h3>
          <router-link to="/portfolio" class="ds-link">管理组合 →</router-link>
        </div>
        <div class="account-content" v-if="account">
          <div class="account-main">
            <div class="account-metric">
              <span class="metric-label">总资产</span>
              <span class="metric-value mono">{{ formatNumber(account.total_assets, 0) }}</span>
            </div>
            <div class="account-metric">
              <span class="metric-label">总收益</span>
              <span class="metric-value mono" :class="account.total_profit >= 0 ? 'text-rise' : 'text-fall'">
                {{ account.total_profit >= 0 ? '+' : '' }}{{ formatNumber(account.total_profit, 0) }}
              </span>
            </div>
            <div class="account-metric">
              <span class="metric-label">收益率</span>
              <span class="metric-value mono" :class="account.return_pct >= 0 ? 'text-rise' : 'text-fall'">
                {{ account.return_pct >= 0 ? '+' : '' }}{{ account.return_pct.toFixed(2) }}%
              </span>
            </div>
          </div>
          <div class="account-sub">
            <div class="account-metric small">
              <span class="metric-label">现金</span>
              <span class="metric-value mono">{{ formatNumber(account.cash, 0) }}</span>
            </div>
            <div class="account-metric small">
              <span class="metric-label">持仓市值</span>
              <span class="metric-value mono">{{ formatNumber(account.market_value, 0) }}</span>
            </div>
            <div class="account-metric small">
              <span class="metric-label">持仓数</span>
              <span class="metric-value mono">{{ account.position_count }}</span>
            </div>
          </div>
        </div>
        <div v-else class="ds-empty">加载中...</div>
      </section>

      <section class="data-section watchlist-section apple-card">
        <div class="ds-header">
          <h3 class="ds-title">自选股</h3>
          <router-link to="/watchlist" class="ds-link">查看全部 →</router-link>
        </div>
        <div class="watchlist-mini" v-if="watchlistQuotes.length">
          <div v-for="q in watchlistQuotes.slice(0, 6)" :key="q.symbol" class="wl-item" @click="goToStock(q.symbol)">
            <div class="wl-left">
              <span class="wl-name">{{ q.name }}</span>
              <span class="wl-code mono">{{ q.symbol }}</span>
            </div>
            <div class="wl-right">
              <span class="wl-price mono">{{ formatPrice(q.price) }}</span>
              <span class="wl-pct mono" :class="q.change_pct >= 0 ? 'text-rise' : 'text-fall'">
                {{ q.change_pct >= 0 ? '+' : '' }}{{ q.change_pct.toFixed(2) }}%
              </span>
            </div>
          </div>
        </div>
        <div v-else class="ds-empty">
          <router-link to="/market">去行情页添加自选股 →</router-link>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMarketStore } from '@/stores/market'
import { usePortfolioStore } from '@/stores/portfolio'
import { useWatchlistStore } from '@/stores/watchlist'
import { formatNumber, formatPrice } from '@/utils/format'
import { api } from '@/api'
import type { StockQuote, SignalItem } from '@/types'

const router = useRouter()
const marketStore = useMarketStore()
const portfolioStore = usePortfolioStore()
const watchlistStore = useWatchlistStore()

const cnIndices = computed(() => marketStore.cnIndices)
const heatmap = computed(() => marketStore.heatmap)
const anomalies = computed(() => marketStore.anomalies)
const northbound = computed(() => marketStore.northbound)
const account = computed(() => portfolioStore.account)

const signals = ref<SignalItem[]>([])

const watchlistQuotes = computed(() => {
  return Object.values(watchlistStore.quotes) as StockQuote[]
})

function goToStock(symbol: string) {
  router.push(`/stock/${symbol}`)
}

async function fetchSignals() {
  try {
    const res = await api.stock.signals('sh000300')
    if (res?.signals) {
      signals.value = res.signals.slice(0, 10).map((s: { symbol?: string; signal?: string; price?: number; date?: string; name?: string; signal_type?: string; strategy?: string }, i: number) => ({
        id: i,
        symbol: s.symbol || 'sh000300',
        name: s.name || '沪深300',
        type: s.signal_type || 'buy',
        strategy: s.strategy || '综合策略',
        time: s.date || '',
      }))
    }
  } catch {}
}

onMounted(async () => {
  await Promise.allSettled([
    marketStore.fetchDashboardData(),
    portfolioStore.fetchAccount(),
    watchlistStore.fetchWatchlist(),
    fetchSignals(),
  ])
})
</script>

<style scoped>
.dashboard {
  max-width: 1280px;
  margin: 0 auto;
}

.hero-section {
  margin-bottom: var(--space-10);
  padding: var(--space-10) 0;
  background: var(--bg-gradient-hero);
  border-radius: var(--radius-2xl);
  padding: var(--space-10) var(--space-8);
}

.hero-content {
  margin-bottom: var(--space-8);
}

.hero-title {
  font-size: var(--text-4xl);
  font-weight: 700;
  letter-spacing: -0.04em;
  color: var(--text-primary);
  line-height: var(--leading-tight);
}

.hero-subtitle {
  font-size: var(--text-lg);
  color: var(--text-secondary);
  margin-top: var(--space-2);
  font-weight: 400;
}

.hero-indices {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: var(--space-3);
}

.hero-index-card {
  padding: var(--space-4);
  border-radius: var(--radius-md);
  background: var(--bg-gradient-card);
  border: 1px solid var(--border);
  transition: transform var(--transition-smooth), border-color var(--transition-fast);
}

.hero-index-card:hover {
  transform: translateY(-2px);
  border-color: var(--border-hover);
}

.hero-index-card.rise {
  background: var(--bg-gradient-card-rise);
}

.hero-index-card.fall {
  background: var(--bg-gradient-card-fall);
}

.hi-name {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  margin-bottom: var(--space-1);
  font-weight: 500;
}

.hi-price {
  font-size: var(--text-xl);
  font-weight: 600;
  margin-bottom: 2px;
}

.hi-change {
  font-size: var(--text-sm);
  font-weight: 500;
}

.hero-index-card.rise .hi-price,
.hero-index-card.rise .hi-change {
  color: var(--rise);
}

.hero-index-card.fall .hi-price,
.hero-index-card.fall .hi-change {
  color: var(--fall);
}

.feature-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-4);
  margin-bottom: var(--space-10);
}

.feature-card {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-6);
  text-decoration: none;
  color: inherit;
}

.feature-card:hover {
  color: inherit;
  opacity: 1;
}

.fc-icon {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.fc-news .fc-icon { background: rgba(41, 151, 255, 0.12); color: #2997ff; }
.fc-screener .fc-icon { background: rgba(175, 82, 222, 0.12); color: #af52de; }
.fc-money .fc-icon { background: rgba(255, 159, 10, 0.12); color: #ff9f0a; }
.fc-chip .fc-icon { background: rgba(52, 199, 89, 0.12); color: #34c759; }
.fc-sector .fc-icon { background: rgba(255, 59, 48, 0.12); color: #ff3b30; }
.fc-strategy .fc-icon { background: rgba(191, 90, 242, 0.12); color: #bf5af2; }

.fc-body {
  flex: 1;
  min-width: 0;
}

.fc-title {
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 2px;
}

.fc-desc {
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.fc-arrow {
  color: var(--text-tertiary);
  flex-shrink: 0;
  transition: transform var(--transition-fast), color var(--transition-fast);
}

.feature-card:hover .fc-arrow {
  transform: translateX(4px);
  color: var(--accent);
}

.data-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: var(--space-4);
}

.data-section {
  overflow: hidden;
}

.ds-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--border-subtle);
}

.ds-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.01em;
}

.ds-link {
  font-size: var(--text-xs);
  color: var(--accent);
  font-weight: 500;
}

.ds-count {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  font-weight: 500;
}

.ds-empty {
  padding: var(--space-8) var(--space-5);
  text-align: center;
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}

.heatmap-section {
  grid-column: 1 / 3;
}

.heatmap-wrap {
  padding: var(--space-4) var(--space-5);
}

.heatmap-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  height: 220px;
}

.heatmap-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border-radius: 2px;
  min-width: 40px;
  min-height: 40px;
  padding: 2px;
  cursor: default;
  transition: opacity var(--transition-normal), transform var(--transition-fast);
}

.heatmap-cell:hover {
  opacity: 0.85;
  transform: scale(1.05);
}

.heatmap-cell.rise {
  background: rgba(255, 59, 48, 0.12);
  color: var(--rise);
}

.heatmap-cell.fall {
  background: rgba(52, 199, 89, 0.12);
  color: var(--fall);
}

.hm-name {
  font-size: 10px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.hm-pct {
  font-size: 10px;
  font-weight: 500;
}

.signal-list {
  max-height: 280px;
  overflow-y: auto;
}

.signal-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-5);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.signal-item:hover {
  background: var(--bg-hover);
}

.signal-left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.signal-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
  line-height: 1.4;
}

.badge-buy {
  background: var(--rise-bg);
  color: var(--rise);
}

.badge-sell {
  background: var(--fall-bg);
  color: var(--fall);
}

.signal-name {
  font-size: var(--text-sm);
  color: var(--text-primary);
}

.signal-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.signal-strategy {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  padding: 1px 6px;
  background: var(--bg-elevated);
  border-radius: 3px;
}

.northbound-content {
  padding: var(--space-5);
}

.nb-main {
  margin-bottom: var(--space-4);
}

.nb-label {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: var(--space-1);
}

.nb-value {
  font-size: var(--text-3xl);
  font-weight: 700;
  font-family: var(--font-data);
  letter-spacing: -0.03em;
}

.nb-detail {
  display: flex;
  gap: var(--space-8);
}

.nb-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nb-item-label {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.anomaly-list {
  max-height: 280px;
  overflow-y: auto;
}

.anomaly-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-5);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.anomaly-item:hover {
  background: var(--bg-hover);
}

.anomaly-left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.anomaly-name {
  font-size: var(--text-sm);
  color: var(--text-primary);
}

.anomaly-code {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.anomaly-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.anomaly-pct {
  font-size: var(--text-sm);
  font-weight: 500;
}

.anomaly-reason {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  padding: 1px 6px;
  background: var(--bg-elevated);
  border-radius: 3px;
}

.account-section {
  grid-column: 2 / 3;
}

.account-content {
  padding: var(--space-5);
}

.account-main {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--border-subtle);
}

.account-metric {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.metric-label {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.metric-value {
  font-size: var(--text-md);
  font-weight: 500;
}

.account-metric.small .metric-value {
  font-size: var(--text-sm);
}

.account-sub {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.watchlist-section {
  grid-column: 3 / 4;
}

.watchlist-mini {
  max-height: 280px;
  overflow-y: auto;
}

.wl-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-5);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.wl-item:hover {
  background: var(--bg-hover);
}

.wl-left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.wl-name {
  font-size: var(--text-sm);
  color: var(--text-primary);
}

.wl-code {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.wl-right {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.wl-price {
  font-size: var(--text-sm);
  color: var(--text-primary);
}

.wl-pct {
  font-size: var(--text-xs);
  font-weight: 500;
  min-width: 56px;
  text-align: right;
}

@media (max-width: 1200px) {
  .hero-indices {
    grid-template-columns: repeat(3, 1fr);
  }
  .feature-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .data-grid {
    grid-template-columns: 1fr 1fr;
  }
  .heatmap-section {
    grid-column: 1 / -1;
  }
  .account-section,
  .watchlist-section {
    grid-column: auto;
  }
}

@media (max-width: 768px) {
  .feature-grid {
    grid-template-columns: 1fr;
  }
  .data-grid {
    grid-template-columns: 1fr;
  }
}
</style>
