<template>
  <div class="market-page">
    <div class="page-header">
      <h1 class="page-title">市场浏览</h1>
    </div>
    
    <div class="market-content">
      <div class="market-tabs">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="tab-btn"
          :class="{ active: activeTab === tab.key }"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
        </button>
      </div>

      <div class="market-data">
        <div class="data-table">
          <div class="table-header">
            <span>代码</span>
            <span>名称</span>
            <span class="text-right">最新价</span>
            <span class="text-right">涨跌幅</span>
            <span class="text-right">成交量</span>
            <span class="text-right">成交额</span>
          </div>
          <div
            v-for="stock in displayStocks"
            :key="stock.code"
            class="table-row"
            :class="{ up: stock.change_pct >= 0, down: stock.change_pct < 0 }"
            @click="$router.push(`/stock/${stock.code}`)"
          >
            <span class="code">{{ stock.code }}</span>
            <span class="name">{{ stock.name }}</span>
            <span class="text-right price">{{ stock.price?.toFixed(2) || '-' }}</span>
            <span class="text-right change">{{ stock.change_pct >= 0 ? '+' : '' }}{{ stock.change_pct?.toFixed(2) || '-' }}%</span>
            <span class="text-right">{{ formatVolume(stock.volume) }}</span>
            <span class="text-right">{{ formatAmount(stock.amount) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const activeTab = ref('sh')

const tabs = [
  { key: 'sh', label: '沪市' },
  { key: 'sz', label: '深市' },
  { key: 'hk', label: '港股' },
  { key: 'us', label: '美股' },
]

const mockStocks = [
  { code: '600519', name: '贵州茅台', price: 1402.9, change_pct: -0.15, volume: 9710, amount: 136436 },
  { code: '601318', name: '中国平安', price: 48.56, change_pct: 1.23, volume: 125600, amount: 610500 },
  { code: '000858', name: '五粮液', price: 98.0, change_pct: -2.2, volume: 199922, amount: 195505 },
  { code: '600036', name: '招商银行', price: 35.28, change_pct: 0.86, volume: 89300, amount: 315000 },
  { code: '000001', name: '平安银行', price: 12.35, change_pct: -0.40, volume: 234500, amount: 289700 },
]

const displayStocks = computed(() => mockStocks)

function formatVolume(v: number): string {
  if (v >= 10000) {
    return (v / 10000).toFixed(1) + '万'
  }
  return String(v)
}

function formatAmount(a: number): string {
  if (a >= 10000) {
    return (a / 10000).toFixed(1) + '万'
  }
  return String(a)
}
</script>

<style scoped>
.market-page {
  padding: 24px;
}

.page-header {
  margin-bottom: 24px;
}

.page-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
}

.market-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 20px;
}

.tab-btn {
  padding: 8px 20px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition);
}

.tab-btn:hover {
  border-color: rgba(255,255,255,0.1);
  color: var(--text-primary);
}

.tab-btn.active {
  background: rgba(77,159,255,0.1);
  border-color: var(--accent-blue);
  color: var(--accent-blue);
}

.data-table {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.table-header {
  display: grid;
  grid-template-columns: 80px 120px 100px 80px 100px 100px;
  padding: 14px 16px;
  background: rgba(255,255,255,0.03);
  border-bottom: 1px solid var(--border-color);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.table-row {
  display: grid;
  grid-template-columns: 80px 120px 100px 80px 100px 100px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  cursor: pointer;
  transition: all 0.15s;
}

.table-row:last-child {
  border-bottom: none;
}

.table-row:hover {
  background: rgba(255,255,255,0.03);
}

.table-row.up {
  color: var(--accent-red);
}

.table-row.down {
  color: var(--accent-green);
}

.text-right {
  text-align: right;
}

.code {
  font-family: var(--font-mono);
  color: var(--accent-cyan);
}

.name {
  color: var(--text-primary);
}

.price {
  font-family: var(--font-mono);
  font-weight: 600;
}

.change {
  font-family: var(--font-mono);
}
</style>