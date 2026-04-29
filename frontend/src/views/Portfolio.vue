<template>
  <div class="portfolio-page">
    <div class="page-header">
      <h1 class="page-title">组合管理</h1>
    </div>

    <div class="portfolio-content">
      <div class="overview-section">
        <div class="overview-card main">
          <div class="card-title">总资产</div>
          <div class="card-value">¥{{ formatNumber(account.total_assets || 100000) }}</div>
          <div class="card-change" :class="account.total_pnl >= 0 ? 'up' : 'down'">
            {{ account.total_pnl >= 0 ? '+' : '' }}¥{{ formatNumber(account.total_pnl || 0) }}
            <span>({{ account.total_pnl >= 0 ? '+' : '' }}{{ account.pnl_pct?.toFixed(2) || '0' }}%)</span>
          </div>
        </div>

        <div class="overview-grid">
          <div class="overview-card">
            <div class="card-title">持仓市值</div>
            <div class="card-value">¥{{ formatNumber(account.position_value || 50000) }}</div>
          </div>
          <div class="overview-card">
            <div class="card-title">可用资金</div>
            <div class="card-value">¥{{ formatNumber(account.available_cash || 50000) }}</div>
          </div>
          <div class="overview-card">
            <div class="card-title">持仓数量</div>
            <div class="card-value">{{ account.positions?.length || 2 }}</div>
          </div>
          <div class="overview-card">
            <div class="card-title">今日盈亏</div>
            <div class="card-value" :class="account.today_pnl >= 0 ? 'up' : 'down'">
              {{ account.today_pnl >= 0 ? '+' : '' }}¥{{ formatNumber(account.today_pnl || 1250) }}
            </div>
          </div>
        </div>
      </div>

      <div class="positions-section">
        <h2 class="section-title">持仓列表</h2>
        <div v-if="positions.length" class="positions-list">
          <div
            v-for="pos in positions"
            :key="pos.symbol"
            class="position-item"
            @click="$router.push(`/stock/${pos.symbol}`)"
          >
            <div class="position-left">
              <div class="position-header">
                <span class="position-code">{{ pos.symbol }}</span>
                <span class="position-name">{{ pos.name }}</span>
              </div>
              <div class="position-info">
                <span>持仓: {{ pos.shares }}股</span>
                <span>成本: ¥{{ pos.cost_price.toFixed(2) }}</span>
              </div>
            </div>
            <div class="position-right">
              <div class="position-price">¥{{ pos.current_price.toFixed(2) }}</div>
              <div class="position-pnl" :class="pos.pnl >= 0 ? 'up' : 'down'">
                {{ pos.pnl >= 0 ? '+' : '' }}¥{{ pos.pnl.toFixed(2) }}
                <span>({{ pos.pnl_pct >= 0 ? '+' : '' }}{{ pos.pnl_pct.toFixed(2) }}%)</span>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/><path d="M9 12l2 2 4-4"/>
          </svg>
          <p>暂无持仓</p>
        </div>
      </div>

      <div class="trading-section">
        <h2 class="section-title">快捷交易</h2>
        <div class="trading-form">
          <div class="form-row">
            <div class="form-group">
              <label>股票代码</label>
              <input
                v-model="tradeSymbol"
                placeholder="输入股票代码"
                class="form-input"
              />
            </div>
            <div class="form-group">
              <label>交易方向</label>
              <select v-model="tradeDirection" class="form-select">
                <option value="buy">买入</option>
                <option value="sell">卖出</option>
              </select>
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>价格</label>
              <input
                v-model.number="tradePrice"
                type="number"
                placeholder="输入价格"
                class="form-input"
              />
            </div>
            <div class="form-group">
              <label>数量（股）</label>
              <input
                v-model.number="tradeShares"
                type="number"
                placeholder="输入数量"
                class="form-input"
              />
            </div>
          </div>
          <div class="form-actions">
            <button class="btn btn-primary" @click="submitTrade">
              {{ tradeDirection === 'buy' ? '买入' : '卖出' }}
            </button>
            <button class="btn btn-ghost" @click="resetTrade">重置</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '../api'

const account = ref<any>({})
const positions = ref<any[]>([])

const tradeSymbol = ref('')
const tradeDirection = ref('buy')
const tradePrice = ref(0)
const tradeShares = ref(0)

function formatNumber(num: number): string {
  return num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

async function loadAccount() {
  const data = await api.getAccount()
  if (data) {
    account.value = data
    positions.value = data.positions || [
      { symbol: '600519', name: '贵州茅台', shares: 100, cost_price: 1380, current_price: 1402.9, pnl: 2290, pnl_pct: 1.66 },
      { symbol: '000858', name: '五粮液', shares: 500, cost_price: 102, current_price: 98, pnl: -2000, pnl_pct: -3.92 },
    ]
  }
}

async function submitTrade() {
  if (!tradeSymbol.value || !tradePrice.value || !tradeShares.value) return
  
  if (tradeDirection.value === 'buy') {
    await api.buy(tradeSymbol.value, tradePrice.value, tradeShares.value)
  } else {
    await api.sell(tradeSymbol.value, tradePrice.value, tradeShares.value)
  }
  
  resetTrade()
  await loadAccount()
}

function resetTrade() {
  tradeSymbol.value = ''
  tradePrice.value = 0
  tradeShares.value = 0
}

onMounted(() => {
  loadAccount()
})
</script>

<style scoped>
.portfolio-page {
  padding: 24px;
  max-width: 1000px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 24px;
}

.page-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
}

.overview-section {
  margin-bottom: 24px;
}

.overview-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 20px;
}

.overview-card.main {
  margin-bottom: 16px;
}

.card-title {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.card-value {
  font-size: 28px;
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--text-primary);
}

.card-change {
  font-size: 14px;
  margin-top: 4px;
}

.card-change.up {
  color: var(--accent-red);
}

.card-change.down {
  color: var(--accent-green);
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 16px;
}

.positions-section, .trading-section {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 20px;
  margin-bottom: 20px;
}

.positions-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.position-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 14px;
  background: rgba(255,255,255,0.03);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.15s;
}

.position-item:hover {
  background: rgba(255,255,255,0.05);
}

.position-left {
  flex: 1;
}

.position-header {
  display: flex;
  gap: 10px;
  margin-bottom: 6px;
}

.position-code {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--accent-cyan);
}

.position-name {
  font-size: 13px;
  color: var(--text-primary);
}

.position-info {
  display: flex;
  gap: 16px;
  font-size: 11px;
  color: var(--text-tertiary);
}

.position-right {
  text-align: right;
}

.position-price {
  font-family: var(--font-mono);
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.position-pnl {
  font-size: 12px;
}

.position-pnl.up {
  color: var(--accent-red);
}

.position-pnl.down {
  color: var(--accent-green);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 32px;
  color: var(--text-tertiary);
}

.empty-state svg {
  margin-bottom: 12px;
  opacity: 0.5;
}

.empty-state p {
  font-size: 13px;
}

.trading-form {
  background: rgba(255,255,255,0.03);
  border-radius: var(--radius-md);
  padding: 20px;
}

.form-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.form-group {
  display: flex;
  flex-direction: column;
}

.form-group label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.form-input {
  height: 36px;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 0 10px;
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
}

.form-input:focus {
  border-color: var(--accent-blue);
}

.form-select {
  height: 36px;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 0 10px;
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
}

.form-select:focus {
  border-color: var(--accent-blue);
}

.form-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}
</style>