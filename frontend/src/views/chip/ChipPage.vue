<template>
  <div class="chip-page">
    <div class="page-hero">
      <h1 class="page-title">筹码分布</h1>
      <p class="page-subtitle">分析持仓成本结构，判断支撑阻力</p>
    </div>

    <div class="search-bar">
      <div class="search-wrap">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
        </svg>
        <input v-model="symbolInput" class="apple-input" placeholder="输入股票代码" @keydown.enter="fetchChip" />
        <button class="apple-btn apple-btn-primary" @click="fetchChip">分析</button>
      </div>
      <div class="quick-picks">
        <span class="pick-label">热门</span>
        <button v-for="p in quickPicks" :key="p.code" class="pick-btn" :class="{ active: symbolInput === p.code }" @click="symbolInput = p.code; fetchChip()">{{ p.name }}</button>
      </div>
    </div>

    <div v-if="loading" class="loading-state">
      <div class="loading-spinner" /><span>分析中...</span>
    </div>
    <div v-else-if="!chipData" class="empty-state">
      <div class="empty-icon">📊</div>
      <p>输入股票代码查看筹码分布</p>
    </div>
    <template v-else>
      <div class="chip-overview">
        <div class="overview-card apple-card">
          <div class="apple-metric">
            <div class="apple-metric-label">当前价</div>
            <div class="apple-metric-value mono">{{ chipData.current_price.toFixed(2) }}</div>
          </div>
        </div>
        <div class="overview-card apple-card">
          <div class="apple-metric">
            <div class="apple-metric-label">平均成本</div>
            <div class="apple-metric-value mono" :class="chipData.current_price > chipData.avg_cost ? 'text-rise' : 'text-fall'">{{ chipData.avg_cost.toFixed(2) }}</div>
          </div>
        </div>
        <div class="overview-card apple-card">
          <div class="apple-metric">
            <div class="apple-metric-label">获利比例</div>
            <div class="apple-metric-value mono" :class="chipData.profit_ratio > 0.5 ? 'text-rise' : 'text-fall'">{{ (chipData.profit_ratio * 100).toFixed(1) }}%</div>
          </div>
        </div>
        <div class="overview-card apple-card">
          <div class="apple-metric">
            <div class="apple-metric-label">集中度</div>
            <div class="apple-metric-value mono">{{ (chipData.concentration * 100).toFixed(1) }}%</div>
          </div>
        </div>
        <div class="overview-card apple-card">
          <div class="apple-metric">
            <div class="apple-metric-label">支撑位</div>
            <div class="apple-metric-value mono text-fall">{{ chipData.support_price.toFixed(2) }}</div>
          </div>
        </div>
        <div class="overview-card apple-card">
          <div class="apple-metric">
            <div class="apple-metric-label">阻力位</div>
            <div class="apple-metric-value mono text-rise">{{ chipData.resistance_price.toFixed(2) }}</div>
          </div>
        </div>
      </div>

      <div class="chip-chart-area apple-card">
        <div class="chart-title">筹码分布图</div>
        <div class="chart-container" ref="chartRef">
          <canvas ref="canvasRef" />
        </div>
      </div>

      <div v-if="chipData.fire" class="chip-fire apple-card">
        <div class="fire-header">
          <h3 class="fire-title">筹码研判</h3>
          <span class="apple-badge" :class="fireBadgeClass(chipData.fire.status)">{{ fireStatusLabel(chipData.fire.status) }}</span>
        </div>
        <div class="fire-signal">{{ chipData.fire.signal }}</div>
        <div class="fire-details" v-if="chipData.fire.short_concentration !== undefined">
          <div class="detail-row"><span>短期集中度</span><span class="mono">{{ (chipData.fire.short_concentration * 100).toFixed(1) }}%</span></div>
          <div class="detail-row"><span>中期集中度</span><span class="mono">{{ (chipData.fire.mid_concentration! * 100).toFixed(1) }}%</span></div>
          <div class="detail-row"><span>长期集中度</span><span class="mono">{{ (chipData.fire.long_concentration! * 100).toFixed(1) }}%</span></div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api'
import type { ChipData } from '@/types'

const route = useRoute()
const symbolInput = ref('')
const chipData = ref<ChipData | null>(null)
const loading = ref(false)
const canvasRef = ref<HTMLCanvasElement>()
const chartRef = ref<HTMLDivElement>()

const quickPicks = [
  { code: '600519', name: '贵州茅台' },
  { code: '000858', name: '五粮液' },
  { code: '601318', name: '中国平安' },
  { code: '300750', name: '宁德时代' },
  { code: '002594', name: '比亚迪' },
  { code: '600036', name: '招商银行' },
]

function fireStatusLabel(status: string) {
  const map: Record<string, string> = {
    highly_concentrated: '高度集中',
    concentrated_above_cost: '集中偏多',
    concentrated_below_cost: '集中偏空',
    dispersed: '筹码分散',
    moderate: '分布适中',
    insufficient_data: '数据不足',
  }
  return map[status] || status
}

function fireBadgeClass(status: string) {
  const map: Record<string, string> = {
    highly_concentrated: 'apple-badge-rise',
    concentrated_above_cost: 'apple-badge-warn',
    concentrated_below_cost: 'apple-badge-accent',
    dispersed: '',
    moderate: 'apple-badge-fall',
    insufficient_data: '',
  }
  return map[status] || ''
}

async function fetchChip() {
  const symbol = symbolInput.value.trim()
  if (!symbol) return
  loading.value = true
  try {
    chipData.value = await api.chip.distribution(symbol)
    loading.value = false
    await nextTick()
    drawChart()
  } catch {
    chipData.value = null
    loading.value = false
  }
}

function drawChart() {
  if (!chipData.value || !canvasRef.value || !chartRef.value) return
  const canvas = canvasRef.value
  const container = chartRef.value
  const dpr = window.devicePixelRatio || 1
  const w = container.clientWidth
  const h = 320
  canvas.width = w * dpr
  canvas.height = h * dpr
  canvas.style.width = w + 'px'
  canvas.style.height = h + 'px'
  const ctx = canvas.getContext('2d')!
  ctx.scale(dpr, dpr)

  const data = chipData.value
  const prices = data.prices
  const dist = data.distribution
  if (!prices.length || !dist.length) return

  const pad = { top: 24, right: 70, bottom: 30, left: 70 }
  const cw = w - pad.left - pad.right
  const ch = h - pad.top - pad.bottom
  const maxDist = Math.max(...dist)
  const minP = Math.min(...prices)
  const maxP = Math.max(...prices)
  const priceRange = maxP - minP || 1

  ctx.clearRect(0, 0, w, h)

  const cs = getComputedStyle(document.documentElement)
  const borderColor = cs.getPropertyValue('--border').trim() || '#333'
  const tertColor = cs.getPropertyValue('--text-tertiary').trim() || '#888'
  const riseColor = cs.getPropertyValue('--rise').trim() || '#ff3b30'
  const fallColor = cs.getPropertyValue('--fall').trim() || '#34c759'

  ctx.strokeStyle = borderColor
  ctx.lineWidth = 0.5
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + (ch / 4) * i
    ctx.beginPath()
    ctx.moveTo(pad.left, y)
    ctx.lineTo(w - pad.right, y)
    ctx.stroke()
    const price = maxP - (priceRange / 4) * i
    ctx.fillStyle = tertColor
    ctx.font = '11px monospace'
    ctx.textAlign = 'right'
    ctx.fillText(price.toFixed(2), pad.left - 8, y + 4)
  }

  for (let i = 0; i < prices.length; i++) {
    const y = pad.top + ((maxP - prices[i]) / priceRange) * ch
    const barW = (dist[i] / maxDist) * cw * 0.4
    const isAbove = prices[i] <= data.current_price
    ctx.fillStyle = isAbove ? riseColor + '60' : fallColor + '60'
    ctx.fillRect(pad.left + cw * 0.3, y - ch / prices.length / 2, barW, Math.max(ch / prices.length, 1))
  }

  const curY = pad.top + ((maxP - data.current_price) / priceRange) * ch
  ctx.strokeStyle = '#ffd60a'
  ctx.lineWidth = 1.5
  ctx.setLineDash([5, 4])
  ctx.beginPath()
  ctx.moveTo(pad.left, curY)
  ctx.lineTo(w - pad.right, curY)
  ctx.stroke()
  ctx.setLineDash([])
  ctx.fillStyle = '#ffd60a'
  ctx.font = '11px sans-serif'
  ctx.textAlign = 'left'
  ctx.fillText('当前价 ' + data.current_price.toFixed(2), w - pad.right + 6, curY + 4)

  const avgY = pad.top + ((maxP - data.avg_cost) / priceRange) * ch
  ctx.strokeStyle = '#bf5af2'
  ctx.lineWidth = 1.5
  ctx.setLineDash([5, 4])
  ctx.beginPath()
  ctx.moveTo(pad.left, avgY)
  ctx.lineTo(w - pad.right, avgY)
  ctx.stroke()
  ctx.setLineDash([])
  ctx.fillStyle = '#bf5af2'
  ctx.fillText('成本 ' + data.avg_cost.toFixed(2), w - pad.right + 6, avgY + 4)
}

onMounted(() => {
  const sym = route.params.symbol as string
  if (sym) {
    symbolInput.value = sym
    fetchChip()
  }
})

watch([() => chipData.value, () => loading.value], () => {
  if (chipData.value && !loading.value) {
    nextTick(drawChart)
  }
})
</script>

<style scoped>
.chip-page { max-width: 960px; margin: 0 auto; }
.page-hero { margin-bottom: var(--space-6); }
.page-title { font-size: var(--text-3xl); font-weight: 700; letter-spacing: -0.03em; color: var(--text-primary); line-height: var(--leading-tight); }
.page-subtitle { font-size: var(--text-md); color: var(--text-secondary); margin-top: var(--space-2); }
.search-bar { margin-bottom: var(--space-6); }
.search-wrap { display: flex; align-items: center; gap: var(--space-3); }
.search-wrap svg { color: var(--text-tertiary); flex-shrink: 0; }
.search-wrap .apple-input { flex: 0 0 160px; }
.quick-picks { display: flex; align-items: center; gap: var(--space-2); margin-top: var(--space-3); }
.pick-label { font-size: var(--text-xs); color: var(--text-tertiary); font-weight: 500; }
.pick-btn { padding: 3px 12px; border-radius: 100px; border: 1px solid var(--border); background: var(--bg-elevated); color: var(--text-secondary); font-size: var(--text-xs); font-family: var(--font-sans); cursor: pointer; transition: all var(--transition-fast); font-weight: 500; }
.pick-btn:hover { border-color: var(--accent); color: var(--accent); }
.pick-btn.active { background: var(--accent-muted); border-color: var(--accent); color: var(--accent); }
.loading-state { display: flex; flex-direction: column; align-items: center; gap: var(--space-3); padding: var(--space-16); color: var(--text-tertiary); }
.loading-spinner { width: 24px; height: 24px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.chip-overview { display: grid; grid-template-columns: repeat(6, 1fr); gap: var(--space-3); margin-bottom: var(--space-5); }
.overview-card { padding: var(--space-4); }
.chip-chart-area { padding: var(--space-5); margin-bottom: var(--space-5); }
.chart-title { font-size: var(--text-sm); color: var(--text-secondary); margin-bottom: var(--space-4); font-weight: 600; }
.chart-container { width: 100%; height: 320px; }
.chart-container canvas { display: block; }
.chip-fire { padding: var(--space-5); }
.fire-header { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-3); }
.fire-title { font-size: var(--text-md); font-weight: 600; color: var(--text-primary); }
.fire-signal { font-size: var(--text-sm); color: var(--text-secondary); margin-bottom: var(--space-4); line-height: 1.5; }
.fire-details { display: flex; flex-direction: column; gap: var(--space-2); }
.detail-row { display: flex; justify-content: space-between; font-size: var(--text-sm); color: var(--text-secondary); padding: var(--space-2) 0; border-bottom: 1px solid var(--border-subtle); }
.empty-state { text-align: center; padding: var(--space-16); color: var(--text-tertiary); }
.empty-icon { font-size: 40px; margin-bottom: var(--space-3); }
</style>
