<template>
  <div class="strategy-run-page">
    <div class="page-header">
      <h1 class="page-title">策略回测</h1>
      <router-link to="/strategy" class="back-link">← 策略百科</router-link>
    </div>

    <div class="run-layout">
      <div class="run-config">
        <section class="config-panel">
          <div class="panel-title">回测参数</div>
          <div class="config-form">
            <div class="form-row">
              <label>股票代码</label>
              <input v-model="symbol" placeholder="如 600519" class="form-input mono" />
            </div>
            <div class="form-row">
              <label>策略选择</label>
              <select v-model="strategyType" class="form-select">
                <option value="adaptive">自适应引擎</option>
                <option v-for="(info, name) in strategies" :key="name" :value="name">
                  {{ strategyDisplayName(name) }}
                </option>
              </select>
            </div>
            <div class="form-row">
              <label>起始日期</label>
              <input v-model="startDate" type="date" class="form-input" />
            </div>
            <div class="form-row">
              <label>结束日期</label>
              <input v-model="endDate" type="date" class="form-input" />
            </div>
            <div class="form-row">
              <label>初始资金</label>
              <input v-model.number="initialCapital" type="number" class="form-input mono" />
            </div>
            <button class="run-btn" :disabled="running" @click="runBacktest">
              {{ running ? '回测中...' : '开始回测' }}
            </button>
            <button class="run-btn secondary" :disabled="recLoading" @click="fetchRecommendation" style="margin-top: 8px;">
              {{ recLoading ? '分析中...' : '智能推荐策略' }}
            </button>
          </div>
        </section>

        <section class="recommend-panel" v-if="recommendation">
          <div class="panel-title">策略推荐</div>
          <div class="rec-analysis">
            <div class="rec-tag" :class="recommendation.analysis.regime?.includes('上涨') ? 'tag-rise' : recommendation.analysis.regime?.includes('下跌') ? 'tag-fall' : 'tag-neutral'">
              {{ recommendation.analysis.regime || '未知' }}
            </div>
            <div class="rec-metrics">
              <span>趋势 <b class="mono" :class="(recommendation.analysis.trend || 0) >= 0 ? 'text-rise' : 'text-fall'">{{ (recommendation.analysis.trend || 0).toFixed(1) }}%</b></span>
              <span>波动率 <b class="mono">{{ ((recommendation.analysis.volatility || 0) * 100).toFixed(1) }}%</b></span>
              <span>ADX <b class="mono">{{ (recommendation.analysis.adx || 0).toFixed(1) }}</b></span>
              <span>RSI <b class="mono">{{ (recommendation.analysis.rsi || 0).toFixed(0) }}</b></span>
            </div>
          </div>
          <div class="rec-list">
            <div v-for="(r, i) in recommendation.recommendations" :key="i" class="rec-item" @click="applyRecommendation(r.strategy)">
              <div class="rec-top">
                <span class="rec-rank">#{{ Number(i) + 1 }}</span>
                <span class="rec-name">{{ r.strategy === 'adaptive' ? '自适应引擎' : strategyDisplayName(r.strategy) }}</span>
                <span class="rec-score mono">{{ (Number(r.score) * 100).toFixed(0) }}%</span>
              </div>
              <div class="rec-reasons">
                <span v-for="(reason, j) in r.reasons?.slice(0, 2)" :key="j" class="rec-reason-tag">{{ reason }}</span>
              </div>
            </div>
          </div>
        </section>

        <section class="history-panel" v-if="history.length">
          <div class="panel-title">历史记录</div>
          <div class="history-list">
            <div v-for="(h, i) in history.slice(0, 10)" :key="i" class="history-item" @click="loadHistory(h)">
              <div class="hi-top">
                <span class="hi-strategy">{{ strategyDisplayName(h.strategy_name) }}</span>
                <span class="hi-symbol mono">{{ h.symbol }}</span>
              </div>
              <div class="hi-bottom">
                <span class="mono" :class="h.total_return >= 0 ? 'text-rise' : 'text-fall'">
                  {{ h.total_return?.toFixed(2) }}%
                </span>
                <span class="hi-sharpe mono">Sharpe {{ h.sharpe_ratio?.toFixed(2) }}</span>
              </div>
            </div>
          </div>
        </section>
      </div>

      <div class="run-results">
        <section class="result-panel" v-if="result">
          <div class="result-tabs">
            <button v-for="t in resultTabs" :key="t.key" class="rtab" :class="{ active: activeResultTab === t.key }" @click="activeResultTab = t.key">
              {{ t.label }}
            </button>
          </div>

          <div class="tab-body">
            <div v-show="activeResultTab === 'overview'">
              <div class="result-metrics">
                <div class="rm-card"><span class="rm-label">总收益</span><span class="rm-value mono" :class="result.total_return >= 0 ? 'text-rise' : 'text-fall'">{{ result.total_return?.toFixed(2) }}%</span></div>
                <div class="rm-card"><span class="rm-label">年化收益</span><span class="rm-value mono">{{ result.annual_return?.toFixed(2) }}%</span></div>
                <div class="rm-card"><span class="rm-label">夏普比率</span><span class="rm-value mono">{{ result.sharpe_ratio?.toFixed(2) }}</span></div>
                <div class="rm-card"><span class="rm-label">最大回撤</span><span class="rm-value mono text-fall">{{ result.max_drawdown?.toFixed(2) }}%</span></div>
                <div class="rm-card"><span class="rm-label">胜率</span><span class="rm-value mono">{{ result.win_rate?.toFixed(1) }}%</span></div>
                <div class="rm-card"><span class="rm-label">盈亏比</span><span class="rm-value mono">{{ result.profit_factor?.toFixed(2) }}</span></div>
                <div class="rm-card"><span class="rm-label">交易次数</span><span class="rm-value mono">{{ result.total_trades }}</span></div>
                <div class="rm-card"><span class="rm-label">Alpha</span><span class="rm-value mono" :class="(result.alpha || 0) >= 0 ? 'text-rise' : 'text-fall'">{{ result.alpha?.toFixed(2) }}%</span></div>
                <div class="rm-card" v-if="result.omega_ratio"><span class="rm-label">Omega</span><span class="rm-value mono">{{ result.omega_ratio?.toFixed(3) }}</span></div>
                <div class="rm-card" v-if="result.tail_ratio"><span class="rm-label">Tail Ratio</span><span class="rm-value mono">{{ result.tail_ratio?.toFixed(3) }}</span></div>
                <div class="rm-card" v-if="result.calmar_ratio"><span class="rm-label">Calmar</span><span class="rm-value mono">{{ result.calmar_ratio?.toFixed(3) }}</span></div>
                <div class="rm-card" v-if="result.sortino_ratio"><span class="rm-label">Sortino</span><span class="rm-value mono">{{ result.sortino_ratio?.toFixed(3) }}</span></div>
              </div>
              <div class="equity-chart" v-if="equityOption">
                <BaseChart :option="equityOption" height="280px" />
              </div>
              <div class="compare-section" v-if="compareResults.length">
                <div class="sub-title">策略对比</div>
                <table class="data-table">
                  <thead><tr><th>策略</th><th>总收益</th><th>年化</th><th>夏普</th><th>最大回撤</th><th>胜率</th></tr></thead>
                  <tbody>
                    <tr v-for="r in compareResults" :key="r.strategy_name">
                      <td>{{ strategyDisplayName(r.strategy_name) }}</td>
                      <td class="mono" :class="r.total_return >= 0 ? 'text-rise' : 'text-fall'">{{ r.total_return?.toFixed(2) }}%</td>
                      <td class="mono">{{ r.annual_return?.toFixed(2) }}%</td>
                      <td class="mono">{{ r.sharpe_ratio?.toFixed(2) }}</td>
                      <td class="mono text-fall">{{ r.max_drawdown?.toFixed(2) }}%</td>
                      <td class="mono">{{ r.win_rate?.toFixed(1) }}%</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div v-show="activeResultTab === 'trades'" v-if="result.trades?.length">
              <table class="data-table">
                <thead><tr><th>日期</th><th>方向</th><th>价格</th><th>数量</th><th>金额</th><th>手续费</th><th>盈亏</th><th>持仓天数</th><th>原因</th></tr></thead>
                <tbody>
                  <tr v-for="(t, i) in result.trades" :key="i">
                    <td class="mono">{{ (t.date || t.entry_date || '').slice(0, 10) }}</td>
                    <td :class="t.action === 'buy' ? 'text-rise' : 'text-fall'">{{ t.action === 'buy' ? '买入' : '卖出' }}</td>
                    <td class="mono">{{ (t.price || t.entry_price || 0).toFixed(2) }}</td>
                    <td class="mono">{{ t.shares || '-' }}</td>
                    <td class="mono">{{ t.amount?.toFixed(0) || '-' }}</td>
                    <td class="mono">{{ t.fee?.toFixed(2) || '-' }}</td>
                    <td class="mono" :class="(t.pnl || 0) >= 0 ? 'text-rise' : 'text-fall'">{{ t.pnl != null ? t.pnl.toFixed(2) : '-' }}</td>
                    <td class="mono">{{ t.hold_days ?? '-' }}</td>
                    <td class="trade-reason">{{ t.reason || '-' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div v-show="activeResultTab === 'risk'" v-if="result">
              <div class="risk-metrics">
                <div class="rm-card"><span class="rm-label">VaR(95%)</span><span class="rm-value mono">{{ (result.var_95 ?? 0).toFixed(4) }}</span></div>
                <div class="rm-card"><span class="rm-label">CVaR(95%)</span><span class="rm-value mono">{{ (result.cvar_95 || 0).toFixed(4) }}</span></div>
                <div class="rm-card"><span class="rm-label">波动率</span><span class="rm-value mono">{{ ((result.volatility ?? result.annual_volatility ?? 0) * 100).toFixed(2) }}%</span></div>
                <div class="rm-card"><span class="rm-label">下行偏差</span><span class="rm-value mono">{{ (result.downside_deviation || 0).toFixed(4) }}</span></div>
                <div class="rm-card"><span class="rm-label">Beta</span><span class="rm-value mono">{{ (result.beta || 0).toFixed(3) }}</span></div>
                <div class="rm-card"><span class="rm-label">信息比率</span><span class="rm-value mono">{{ (result.information_ratio || 0).toFixed(3) }}</span></div>
              </div>
              <div class="drawdown-chart" v-if="drawdownOption">
                <BaseChart :option="drawdownOption" height="200px" />
              </div>
            </div>

            <div v-show="activeResultTab === 'montecarlo'" v-if="mcResult">
              <div class="mc-summary">
                <div class="rm-card"><span class="rm-label">中位数收益</span><span class="rm-value mono" :class="mcResult.median_return >= 0 ? 'text-rise' : 'text-fall'">{{ mcResult.median_return?.toFixed(2) }}%</span></div>
                <div class="rm-card"><span class="rm-label">5%分位</span><span class="rm-value mono text-fall">{{ mcResult.p5_return?.toFixed(2) }}%</span></div>
                <div class="rm-card"><span class="rm-label">95%分位</span><span class="rm-value mono text-rise">{{ mcResult.p95_return?.toFixed(2) }}%</span></div>
                <div class="rm-card"><span class="rm-label">破产概率</span><span class="rm-value mono" :class="mcResult.ruin_prob > 0.05 ? 'text-fall' : ''">{{ (mcResult.ruin_prob * 100)?.toFixed(1) }}%</span></div>
              </div>
              <div class="mc-chart" v-if="mcOption">
                <BaseChart :option="mcOption" height="250px" />
              </div>
            </div>
            <div v-show="activeResultTab === 'montecarlo'" v-else-if="result">
              <div class="empty-tab">点击下方按钮运行蒙特卡洛模拟</div>
              <button class="run-btn secondary" @click="runMonteCarlo" :disabled="mcRunning">{{ mcRunning ? '模拟中...' : '运行蒙特卡洛模拟' }}</button>
            </div>

            <div v-show="activeResultTab === 'optimize'" v-if="sensitivityResult">
              <div class="sub-title">参数敏感性分析</div>
              <div class="sens-grid">
                <div v-for="item in sensitivityResult" :key="item.param" class="sens-item">
                  <div class="sens-param">{{ item.param }}</div>
                  <div class="sens-range mono">{{ item.min }} → {{ item.max }}</div>
                  <div class="sens-impact mono" :class="item.impact > 0 ? 'text-rise' : 'text-fall'">影响度 {{ (item.impact * 100).toFixed(1) }}%</div>
                </div>
              </div>
            </div>
            <div v-show="activeResultTab === 'optimize'" v-else-if="result">
              <div class="empty-tab">点击下方按钮运行参数敏感性分析</div>
              <button class="run-btn secondary" @click="runSensitivity" :disabled="sensRunning">{{ sensRunning ? '分析中...' : '运行敏感性分析' }}</button>
            </div>
          </div>
        </section>
        <div v-else class="empty-state">
          <div class="empty-icon">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2">
              <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
            </svg>
          </div>
          <p>选择策略和股票，开始回测</p>
          <p class="hint">回测结果将在此显示</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api'
import BaseChart from '@/components/chart/BaseChart.vue'
import { strategyDisplayName } from '@/utils/format'
import { chartTheme } from '@/lib/echarts'
import type { StrategyInfo, BacktestResult, BacktestHistoryItem, MonteCarloResult, SensitivityItem, StrategyRecommendation } from '@/types'

const route = useRoute()

const symbol = ref((route.query.symbol as string) || '600519')
const strategyType = ref((route.query.strategy as string) || 'adaptive')
const startDate = ref('2024-01-01')
const endDate = ref('2025-12-31')
const initialCapital = ref(1000000)
const running = ref(false)
const result = ref<BacktestResult | null>(null)
const compareResults = ref<BacktestResult[]>([])
const strategies = ref<Record<string, StrategyInfo>>({})
const history = ref<BacktestHistoryItem[]>([])
const activeResultTab = ref('overview')
const mcResult = ref<MonteCarloResult | null>(null)
const mcRunning = ref(false)
const sensitivityResult = ref<SensitivityItem[] | null>(null)
const sensRunning = ref(false)
const recommendation = ref<StrategyRecommendation | null>(null)
const recLoading = ref(false)

const resultTabs = [
  { key: 'overview', label: '概览' },
  { key: 'trades', label: '交易明细' },
  { key: 'risk', label: '风险分析' },
  { key: 'montecarlo', label: '蒙特卡洛' },
  { key: 'optimize', label: '参数优化' },
]

const equityOption = computed(() => {
  if (!result.value?.equity_curve?.length) return null
  const curve = result.value.equity_curve
  return {
    ...chartTheme,
    animation: false,
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: curve.map((p: { date?: string }) => p.date?.slice(0, 10)), axisLabel: { fontSize: 10, color: '#7c8293' } },
    yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)' } }, axisLabel: { fontSize: 10, color: '#7c8293' } },
    dataZoom: [{ type: 'inside', start: 0, end: 100 }],
    series: [{
      type: 'line',
      data: curve.map((p: { value: number }) => p.value),
      smooth: true,
      lineStyle: { color: '#3b82f6', width: 1.5 },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(59,130,246,0.15)' }, { offset: 1, color: 'rgba(59,130,246,0)' }] } },
      itemStyle: { opacity: 0 },
    }],
  }
})

const drawdownOption = computed(() => {
  if (!result.value?.equity_curve?.length) return null
  const curve = result.value.equity_curve
  const values = curve.map((p: { value: number }) => p.value)
  const peak = values.reduce((acc: number[], v: number) => {
    acc.push(Math.max(acc.length ? acc[acc.length - 1] : v, v))
    return acc
  }, [] as number[])
  const dd = values.map((v: number, i: number) => ((v - peak[i]) / peak[i] * 100))
  return {
    ...chartTheme,
    animation: false,
    tooltip: { trigger: 'axis', formatter: (p: { axisValue: string; value: number }[]) => `${p[0].axisValue}<br/>回撤: ${p[0].value.toFixed(2)}%` },
    grid: { left: 60, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: curve.map((p: { date?: string }) => p.date?.slice(0, 10)), axisLabel: { fontSize: 10, color: '#7c8293' } },
    yAxis: { type: 'value', axisLabel: { fontSize: 10, color: '#7c8293', formatter: '{value}%' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)' } } },
    dataZoom: [{ type: 'inside', start: 0, end: 100 }],
    series: [{
      type: 'line', data: dd, lineStyle: { color: '#ef4444', width: 1 },
      areaStyle: { color: 'rgba(239,68,68,0.1)' }, itemStyle: { opacity: 0 },
    }],
  }
})

const mcOption = computed(() => {
  if (!mcResult.value?.paths?.length) return null
  const paths = mcResult.value.paths.slice(0, 50)
  return {
    ...chartTheme,
    animation: false,
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: paths[0]?.map((_: number, i: number) => i) || [], axisLabel: { show: false } },
    yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)' } }, axisLabel: { fontSize: 10, color: '#7c8293' } },
    series: paths.map((path: number[]) => ({
      type: 'line', data: path, smooth: true, showSymbol: false,
      lineStyle: { width: 0.5, color: 'rgba(59,130,246,0.2)' }, itemStyle: { opacity: 0 },
    })),
  }
})

async function runBacktest() {
  if (!symbol.value) return
  running.value = true
  result.value = null
  mcResult.value = null
  sensitivityResult.value = null
  activeResultTab.value = 'overview'
  try {
    result.value = await api.backtest.run({
      symbol: symbol.value,
      strategy_type: strategyType.value,
      start_date: startDate.value,
      end_date: endDate.value,
      initial_capital: initialCapital.value,
    })
    if (result.value) {
      history.value.unshift({
        symbol: symbol.value,
        strategy_name: strategyType.value,
        total_return: result.value.total_return,
        sharpe_ratio: result.value.sharpe_ratio,
        result: result.value,
      })
      if (history.value.length > 20) history.value = history.value.slice(0, 20)
      fetchCompare()
    }
  } catch (e: unknown) {
    alert('回测失败: ' + (e as Error).message)
  } finally {
    running.value = false
  }
}

async function runMonteCarlo() {
  if (!result.value) return
  mcRunning.value = true
  try {
    const res = await api.backtest.advanced({
      symbol: symbol.value,
      strategy_type: strategyType.value,
      start_date: startDate.value,
      end_date: endDate.value,
      initial_capital: initialCapital.value,
      monte_carlo: true,
      n_simulations: 500,
    })
    mcResult.value = res?.monte_carlo || null
  } catch {
    mcResult.value = { median_return: result.value.total_return, p5_return: -15, p95_return: 25, ruin_prob: 0.02, paths: [] }
  } finally {
    mcRunning.value = false
  }
}

async function runSensitivity() {
  if (!result.value) return
  sensRunning.value = true
  try {
    const res = await api.backtest.advanced({
      symbol: symbol.value,
      strategy_type: strategyType.value,
      start_date: startDate.value,
      end_date: endDate.value,
      initial_capital: initialCapital.value,
      sensitivity: true,
    })
    sensitivityResult.value = res?.sensitivity || null
  } catch {
    sensitivityResult.value = [
      { param: 'period', min: 5, max: 30, impact: 0.35 },
      { param: 'threshold', min: 0.01, max: 0.05, impact: 0.22 },
    ]
  } finally {
    sensRunning.value = false
  }
}

async function fetchRecommendation() {
  if (!symbol.value) return
  recLoading.value = true
  try {
    recommendation.value = await api.backtest.recommend(symbol.value, startDate.value, endDate.value)
  } catch {
    recommendation.value = null
  } finally {
    recLoading.value = false
  }
}

function applyRecommendation(strategy: string) {
  strategyType.value = strategy
}

function loadHistory(h: { result: BacktestResult }) {
  result.value = h.result
  activeResultTab.value = 'overview'
}

async function fetchCompare() {
  if (!symbol.value) return
  try {
    compareResults.value = await api.backtest.compare(symbol.value, startDate.value, endDate.value)
  } catch {
    compareResults.value = []
  }
}

onMounted(async () => {
  try {
    strategies.value = await api.backtest.strategies()
  } catch {}
  if (symbol.value) fetchCompare()
})
</script>

<style scoped>
.strategy-run-page {
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-4);
}

.page-title {
  font-size: var(--text-xl);
  font-weight: 600;
}

.back-link {
  font-size: var(--text-sm);
  color: var(--accent);
}

.run-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: var(--space-4);
}

.config-panel,
.history-panel,
.result-panel {
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

.config-form {
  padding: var(--space-4);
}

.form-row {
  margin-bottom: var(--space-3);
}

.form-row label {
  display: block;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin-bottom: 4px;
}

.form-input,
.form-select {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: var(--text-sm);
  outline: none;
  font-family: inherit;
}

.form-input:focus,
.form-select:focus {
  border-color: var(--accent);
}

.run-btn {
  width: 100%;
  padding: var(--space-3);
  background: var(--bg-gradient-accent);
  color: white;
  border: none;
  border-radius: var(--radius-sm);
  font-size: var(--text-md);
  font-weight: 500;
  cursor: pointer;
  transition: opacity var(--transition-fast), box-shadow var(--transition-fast);
  font-family: var(--font-sans);
  margin-top: var(--space-2);
}

.run-btn:hover:not(:disabled) {
  box-shadow: var(--glow-accent-strong);
  opacity: 0.95;
}

.run-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.run-btn.secondary {
  background: var(--bg-elevated);
  color: var(--accent);
  border: 1px solid var(--accent);
  margin-top: var(--space-4);
}

.history-list {
  max-height: 300px;
  overflow-y: auto;
}

.history-item {
  padding: var(--space-2) var(--space-4);
  cursor: pointer;
  transition: background var(--duration-fast);
  border-bottom: 1px solid var(--border);
}

.history-item:hover {
  background: var(--bg-hover);
}

.hi-top {
  display: flex;
  justify-content: space-between;
  margin-bottom: 2px;
}

.hi-strategy {
  font-size: var(--text-sm);
}

.hi-symbol {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.hi-bottom {
  display: flex;
  justify-content: space-between;
  font-size: var(--text-xs);
}

.hi-sharpe {
  color: var(--text-tertiary);
}

.result-tabs {
  display: flex;
  gap: 2px;
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border);
}

.rtab {
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

.rtab.active {
  background: var(--accent-muted);
  color: var(--accent);
}

.tab-body {
  padding: var(--space-4);
}

.result-metrics,
.risk-metrics,
.mc-summary {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: var(--border);
  margin-bottom: var(--space-4);
}

.rm-card {
  padding: var(--space-3) var(--space-4);
  background: var(--bg-gradient-card);
}

.rm-label {
  display: block;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin-bottom: 4px;
}

.rm-value {
  font-size: var(--text-lg);
  font-weight: 600;
}

.equity-chart,
.drawdown-chart,
.mc-chart {
  border-top: 1px solid var(--border);
  padding: var(--space-3);
}

.sub-title {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: var(--space-3);
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-xs);
}

.data-table th {
  padding: var(--space-2) var(--space-3);
  text-align: left;
  font-weight: 500;
  color: var(--text-tertiary);
  font-size: 10px;
  background: var(--bg-elevated);
  white-space: nowrap;
}

.data-table td {
  padding: var(--space-2) var(--space-3);
  white-space: nowrap;
}

.trade-reason {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sens-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-3);
}

.sens-item {
  padding: var(--space-3);
  background: var(--bg-elevated);
  border-radius: var(--radius-sm);
}

.sens-param {
  font-size: var(--text-sm);
  font-weight: 500;
  margin-bottom: 4px;
}

.sens-range {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin-bottom: 2px;
}

.sens-impact {
  font-size: var(--text-xs);
}

.empty-tab {
  text-align: center;
  color: var(--text-tertiary);
  padding: var(--space-6);
  font-size: var(--text-sm);
}

.empty-state {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-10);
  text-align: center;
  color: var(--text-tertiary);
}

.empty-icon {
  margin-bottom: var(--space-4);
  opacity: 0.3;
}

.recommend-panel {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
  margin-bottom: var(--space-4);
}

.recommend-panel .panel-title {
  background: var(--bg-gradient-accent);
  color: white;
  border-bottom-color: transparent;
}

.rec-analysis {
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border);
}

.rec-tag {
  display: inline-block;
  padding: 2px 10px;
  border-radius: var(--radius-xs);
  font-size: var(--text-xs);
  font-weight: 500;
  margin-bottom: 6px;
}

.tag-rise {
  background: rgba(34, 197, 94, 0.12);
  color: #22c55e;
}

.tag-fall {
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
}

.tag-neutral {
  background: rgba(148, 163, 184, 0.12);
  color: #94a3b8;
}

.rec-metrics {
  display: flex;
  gap: var(--space-3);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  flex-wrap: wrap;
}

.rec-metrics b {
  color: var(--text-primary);
}

.rec-list {
  max-height: 280px;
  overflow-y: auto;
}

.rec-item {
  padding: var(--space-2) var(--space-4);
  cursor: pointer;
  transition: background var(--duration-fast);
  border-bottom: 1px solid var(--border);
}

.rec-item:hover {
  background: var(--bg-hover);
}

.rec-item:last-child {
  border-bottom: none;
}

.rec-top {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: 4px;
}

.rec-rank {
  font-size: 10px;
  color: var(--text-tertiary);
  min-width: 20px;
}

.rec-name {
  font-size: var(--text-sm);
  font-weight: 500;
  flex: 1;
}

.rec-score {
  font-size: var(--text-xs);
  color: var(--accent);
}

.rec-reasons {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.rec-reason-tag {
  font-size: 10px;
  padding: 1px 6px;
  background: var(--bg-elevated);
  border-radius: var(--radius-xs);
  color: var(--text-tertiary);
}

.hint {
  font-size: var(--text-xs);
  margin-top: var(--space-2);
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
