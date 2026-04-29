<template>
  <div class="watchlist-page">
    <div class="page-header">
      <h1 class="page-title">自选股</h1>
      <div class="header-actions">
        <div class="search-box">
          <input
            v-model="searchQuery"
            placeholder="搜索自选股..."
            class="search-input"
          />
        </div>
        <button class="btn btn-primary" @click="showAddModal = true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 5v14M5 12h14"/>
          </svg>
          添加
        </button>
      </div>
    </div>

    <div v-if="watchlistQuotes.length" class="watchlist-grid">
      <div
        v-for="quote in filteredQuotes"
        :key="quote.symbol"
        class="watchlist-card"
        :class="{ up: quote.change_pct >= 0, down: quote.change_pct < 0 }"
        @click="$router.push(`/stock/${quote.symbol}`)"
      >
        <div class="card-header">
          <span class="card-code">{{ quote.symbol }}</span>
          <button class="remove-btn" @click.stop="removeStock(quote.symbol)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
          </button>
        </div>
        <div class="card-name">{{ quote.name }}</div>
        <div class="card-price">{{ quote.price?.toFixed(2) || '-' }}</div>
        <div class="card-change">
          <span>{{ quote.change_pct >= 0 ? '+' : '' }}{{ quote.change_pct?.toFixed(2) || '-' }}%</span>
          <span class="change-value">{{ quote.change >= 0 ? '+' : '' }}{{ quote.change?.toFixed(2) || '-' }}</span>
        </div>
        <div class="card-info">
          <span>成交量: {{ formatVolume(quote.volume) }}</span>
        </div>
      </div>
    </div>

    <div v-else class="empty-state">
      <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
      </svg>
      <p>暂无自选股</p>
      <button class="btn btn-primary" @click="showAddModal = true">添加自选股</button>
    </div>

    <div v-if="showAddModal" class="modal-overlay" @click.self="showAddModal = false">
      <div class="modal-content">
        <div class="modal-header">
          <h3>添加自选股</h3>
          <button class="close-btn" @click="showAddModal = false">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
          </button>
        </div>
        <div class="modal-body">
          <input
            v-model="newSymbol"
            placeholder="输入股票代码（如 600519）"
            class="modal-input"
            @keydown.enter="addStock"
          />
        </div>
        <div class="modal-footer">
          <button class="btn btn-ghost" @click="showAddModal = false">取消</button>
          <button class="btn btn-primary" @click="addStock">添加</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'

const watchlist = ref<any>({ symbols: [], quotes: {} })
const searchQuery = ref('')
const showAddModal = ref(false)
const newSymbol = ref('')

const watchlistQuotes = computed(() => {
  return Object.values(watchlist.value.quotes || {})
})

const filteredQuotes = computed(() => {
  if (!searchQuery.value) return watchlistQuotes.value
  const q = searchQuery.value.toLowerCase()
  return watchlistQuotes.value.filter(
    (item: any) =>
      item.symbol.toLowerCase().includes(q) ||
      item.name.toLowerCase().includes(q)
  )
})

async function loadWatchlist() {
  const data = await api.getWatchlist()
  if (data) watchlist.value = data
}

async function addStock() {
  if (!newSymbol.value.trim()) return
  await api.addToWatchlist(newSymbol.value.trim())
  newSymbol.value = ''
  showAddModal.value = false
  await loadWatchlist()
}

async function removeStock(symbol: string) {
  await api.removeFromWatchlist(symbol)
  await loadWatchlist()
}

function formatVolume(v: number): string {
  if (v >= 10000) {
    return (v / 10000).toFixed(1) + '万'
  }
  return String(v)
}

onMounted(() => {
  loadWatchlist()
})
</script>

<style scoped>
.watchlist-page {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
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

.header-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.search-box {
  position: relative;
}

.search-input {
  width: 200px;
  height: 34px;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 0 12px;
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
  transition: all var(--transition);
}

.search-input:focus {
  border-color: rgba(59,139,255,0.4);
}

.watchlist-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 16px;
}

.watchlist-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 16px;
  cursor: pointer;
  transition: all var(--transition);
}

.watchlist-card:hover {
  border-color: rgba(255,255,255,0.1);
  transform: translateY(-2px);
}

.watchlist-card.up {
  border-color: rgba(244,63,94,0.15);
}

.watchlist-card.down {
  border-color: rgba(52,211,153,0.15);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.card-code {
  font-family: var(--font-mono);
  font-size: 14px;
  font-weight: 600;
  color: var(--accent-cyan);
}

.remove-btn {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255,255,255,0.05);
  border: none;
  border-radius: 50%;
  color: var(--text-tertiary);
  cursor: pointer;
  opacity: 0;
  transition: all 0.15s;
}

.watchlist-card:hover .remove-btn {
  opacity: 1;
}

.remove-btn:hover {
  background: rgba(244,63,94,0.15);
  color: var(--accent-red);
}

.card-name {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.card-price {
  font-size: 24px;
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--text-primary);
  margin-bottom: 4px;
}

.card-change {
  display: flex;
  gap: 8px;
  align-items: center;
  font-family: var(--font-mono);
  font-size: 13px;
  margin-bottom: 12px;
}

.card-change.up {
  color: var(--accent-red);
}

.card-change.down {
  color: var(--accent-green);
}

.change-value {
  color: var(--text-secondary);
  font-size: 12px;
}

.card-info {
  font-size: 11px;
  color: var(--text-tertiary);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 64px;
  color: var(--text-tertiary);
}

.empty-state svg {
  margin-bottom: 16px;
  opacity: 0.5;
}

.empty-state p {
  font-size: 14px;
  margin-bottom: 16px;
}

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.7);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  width: 400px;
  max-width: 90%;
  overflow: hidden;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
}

.modal-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.close-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  border-radius: 50%;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
}

.close-btn:hover {
  background: rgba(255,255,255,0.05);
}

.modal-body {
  padding: 20px;
}

.modal-input {
  width: 100%;
  height: 40px;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 0 12px;
  color: var(--text-primary);
  font-size: 14px;
  outline: none;
  transition: all var(--transition);
}

.modal-input:focus {
  border-color: var(--accent-blue);
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid var(--border-color);
}
</style>