<template>
  <div class="strategy-intro-page">
    <div class="page-header">
      <h1 class="page-title">策略介绍</h1>
    </div>

    <div class="strategy-cards">
      <div class="strategy-card">
        <div class="card-icon momentum">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/>
          </svg>
        </div>
        <h3>动量策略</h3>
        <p>基于价格趋势和成交量变化，捕捉强势上涨股票。</p>
        <div class="card-stats">
          <span>胜率: 62%</span>
          <span>年化收益: 28%</span>
        </div>
      </div>

      <div class="strategy-card">
        <div class="card-icon mean-reversion">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="12" cy="12" r="10"/>
            <path d="M12 8v4M12 16v.01"/>
          </svg>
        </div>
        <h3>均值回归</h3>
        <p>利用股票价格偏离均值后的回归特性进行交易。</p>
        <div class="card-stats">
          <span>胜率: 58%</span>
          <span>年化收益: 22%</span>
        </div>
      </div>

      <div class="strategy-card">
        <div class="card-icon breakout">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M3 7v6h6M21 17a2 2 0 002-2V5a2 2 0 00-2-2H9"/>
            <path d="M17 7l-5 5-4-4-3 3"/>
          </svg>
        </div>
        <h3>突破策略</h3>
        <p>识别价格突破关键支撑/阻力位后的趋势机会。</p>
        <div class="card-stats">
          <span>胜率: 55%</span>
          <span>年化收益: 35%</span>
        </div>
      </div>

      <div class="strategy-card">
        <div class="card-icon multi-factor">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M12 3v18M3 12h18"/>
            <circle cx="12" cy="12" r="3"/>
          </svg>
        </div>
        <h3>多因子策略</h3>
        <p>综合价值、成长、质量等多维度因子筛选优质股票。</p>
        <div class="card-stats">
          <span>胜率: 65%</span>
          <span>年化收益: 24%</span>
        </div>
      </div>
    </div>

    <div class="backtest-info">
      <h2>策略回测</h2>
      <p>点击左侧导航栏的「策略回测」，选择策略和股票进行历史回测分析。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
</script>

<style scoped>
.strategy-intro-page {
  padding: 24px;
  max-width: 1000px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 32px;
}

.page-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
}

.strategy-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 20px;
  margin-bottom: 32px;
}

.strategy-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 24px;
  transition: all var(--transition);
}

.strategy-card:hover {
  border-color: rgba(255,255,255,0.1);
  transform: translateY(-4px);
}

.card-icon {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
  font-size: 20px;
}

.card-icon.momentum {
  background: linear-gradient(135deg, rgba(244,63,94,0.15), rgba(244,63,94,0.05));
  color: var(--accent-red);
}

.card-icon.mean-reversion {
  background: linear-gradient(135deg, rgba(52,211,153,0.15), rgba(52,211,153,0.05));
  color: var(--accent-green);
}

.card-icon.breakout {
  background: linear-gradient(135deg, rgba(77,159,255,0.15), rgba(77,159,255,0.05));
  color: var(--accent-blue);
}

.card-icon.multi-factor {
  background: linear-gradient(135deg, rgba(167,139,250,0.15), rgba(167,139,250,0.05));
  color: var(--accent-purple);
}

.strategy-card h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.strategy-card p {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 16px;
}

.card-stats {
  display: flex;
  gap: 16px;
}

.card-stats span {
  font-size: 12px;
  color: var(--text-tertiary);
  background: rgba(255,255,255,0.03);
  padding: 4px 10px;
  border-radius: 4px;
}

.backtest-info {
  background: rgba(77,159,255,0.05);
  border: 1px solid rgba(77,159,255,0.1);
  border-radius: var(--radius-lg);
  padding: 24px;
}

.backtest-info h2 {
  font-size: 16px;
  font-weight: 600;
  color: var(--accent-blue);
  margin-bottom: 8px;
}

.backtest-info p {
  font-size: 14px;
  color: var(--text-secondary);
}
</style>