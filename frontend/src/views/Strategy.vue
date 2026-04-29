<template>
  <div class="strategy-page">
    <div class="page-header">
      <h1 class="page-title">策略回测</h1>
    </div>

    <div class="backtest-panel">
      <div class="panel-left">
        <div class="form-group">
          <label>选择策略</label>
          <select v-model="selectedStrategy" class="form-select">
            <option value="momentum">动量策略</option>
            <option value="mean_reversion">均值回归</option>
            <option value="breakout">突破策略</option>
            <option value="multi_factor">多因子策略</option>
          </select>
        </div>

        <div class="form-group">
          <label>股票代码</label>
          <input
            v-model="stockCode"
            placeholder="输入股票代码（如 600519）"
            class="form-input"
          />
        </div>

        <div class="form-group">
          <label>回测周期</label>
          <select v-model="backtestPeriod" class="form-select">
            <option value="1y">近1年</option>
            <option value="3y">近3年</option>
            <option value="5y">近5年</option>
          </select>
        </div>

        <button class="btn btn-primary" @click="runBacktest" :disabled="isRunning">
          {{ isRunning ? '回测中...' : '开始回测' }}
        </button>
      </div>

      <div class="panel-right">
        <div v-if="!backtestResult" class="empty-result">
          <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
          </svg>
          <p>选择策略和股票后开始回测</p>
        </div>

        <div v-else class="result-content">
          <div class="result-header">
            <h3>{{ strategyNames[selectedStrategy] }} - {{ stockCode }}</h3>
          </div>

          <div class="result-stats">
            <div class="stat-card">
              <span class="stat-label">年化收益率</span>
              <span class="stat-value" :class="backtestResult.annual_return >= 0 ? 'up' : 'down'">
                {{ backtestResult.annual_return >= 0 ? '+' : '' }}{{ backtestResult.annual_return.toFixed(2) }}%
              </span>
            </div>
            <div class="stat-card">
              <span class="stat-label">最大回撤</span>
              <span class="stat-value down">{{ backtestResult.max_drawdown.toFixed(2) }}%</span>
            </div>
            <div class="stat-card">
              <span class="stat-label">胜率</span>
              <span class="stat-value">{{ backtestResult.win_rate.toFixed(1) }}%</span>
            </div>
            <div class="stat-card">
              <span class="stat-label">交易次数</span>
              <span class="stat-value">{{ backtestResult.trades }}</span>
            </div>
          </div>

          <div class="equity-curve">
            <h4>收益曲线</h4>
            <div class="curve-placeholder">
              <svg viewBox="0 0 400 200" class="curve-svg">
                <defs>
                  <linearGradient id="curveGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" style="stop-color:#4d9fff;stop-opacity:0.3" />
                    <stop offset="100%" style="stop-color:#a78bfa;stop-opacity:0.3" />
                  </linearGradient>
                </defs>
                <path :d="equityPath" fill="none" stroke="#4d9fff" stroke-width="2"/>
                <path :d="equityAreaPath" fill="url(#curveGrad)"/>
              </svg>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const selectedStrategy = ref('momentum')
const stockCode = ref('600519')
const backtestPeriod = ref('1y')
const isRunning = ref(false)
const backtestResult = ref<any>(null)

const strategyNames: Record<string, string> = {
  momentum: '动量策略',
  mean_reversion: '均值回归',
  breakout: '突破策略',
  multi_factor: '多因子策略',
}

const equityPath = computed(() => {
  if (!backtestResult.value) return ''
  const points = backtestResult.value.equity_curve || []
  if (!points.length) return ''
  const min = Math.min(...points)
  const max = Math.max(...points)
  const range = max - min || 1
  return points.map((v: number, i: number) => {
    const x = (i / (points.length - 1)) * 400
    const y = 200 - ((v - min) / range) * 180 - 10
    return i === 0 ? `M ${x} ${y}` : `L ${x} ${y}`
  }).join(' ')
})

const equityAreaPath = computed(() => {
  if (!backtestResult.value) return ''
  const points = backtestResult.value.equity_curve || []
  if (!points.length) return ''
  const min = Math.min(...points)
  const max = Math.max(...points)
  const range = max - min || 1
  const path = points.map((v: number, i: number) => {
    const x = (i / (points.length - 1)) * 400
    const y = 200 - ((v - min) / range) * 180 - 10
    return i === 0 ? `M ${x} ${y}` : `L ${x} ${y}`
  }).join(' ')
  return path + ' L 400 190 L 0 190 Z'
})

async function runBacktest() {
  isRunning.value = true
  await new Promise(resolve => setTimeout(resolve, 1500))
  
  backtestResult.value = {
    annual_return: (Math.random() - 0.3) * 40,
    max_drawdown: Math.random() * 20 + 10,
    win_rate: Math.random() * 30 + 45,
    trades: Math.floor(Math.random() * 50) + 10,
    equity_curve: Array.from({ length: 100 }, (_, i) => {
      const base = 100
      const trend = i * 0.3
      const noise = (Math.random() - 0.5) * 10
      const season = Math.sin(i * 0.1) * 5
      return base + trend + noise + season
    }),
  }
  
  isRunning.value = false
}
</script>

<style scoped>
.strategy-page {
  padding: 24px;
  max-width: 1200px;
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

.backtest-panel {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 24px;
}

.panel-left {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 20px;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.form-input {
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

.form-input:focus {
  border-color: var(--accent-blue);
}

.form-select {
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

.form-select:focus {
  border-color: var(--accent-blue);
}

.panel-right {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 20px;
}

.empty-result {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 64px;
  color: var(--text-tertiary);
}

.empty-result svg {
  margin-bottom: 16px;
  opacity: 0.5;
}

.empty-result p {
  font-size: 14px;
}

.result-header {
  margin-bottom: 20px;
}

.result-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.result-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}

.stat-card {
  background: rgba(255,255,255,0.03);
  border-radius: var(--radius-md);
  padding: 16px;
  text-align: center;
}

.stat-label {
  font-size: 11px;
  color: var(--text-tertiary);
  display: block;
  margin-bottom: 8px;
}

.stat-value {
  font-size: 18px;
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--text-primary);
}

.stat-value.up {
  color: var(--accent-red);
}

.stat-value.down {
  color: var(--accent-green);
}

.equity-curve {
  background: rgba(255,255,255,0.03);
  border-radius: var(--radius-md);
  padding: 16px;
}

.equity-curve h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

.curve-placeholder {
  background: var(--bg-primary);
  border-radius: var(--radius-sm);
  padding: 16px;
}

.curve-svg {
  width: 100%;
  height: 200px;
}
</style>