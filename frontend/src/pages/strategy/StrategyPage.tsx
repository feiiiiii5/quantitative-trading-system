import { useEffect, useState, useRef, useCallback, memo } from 'react';
import { useStrategyStore } from '@/stores/strategy';
import { useCanvas } from '@/hooks/useCanvas';
import { formatRatio, formatPrice } from '@/utils/format';
import { apiGet } from '@/api/client';
import type { BacktestResult } from '@/types';

type Difficulty = 'BASIC' | 'PRO' | 'EXPERT';

interface FactorInfo {
  name: string;
  category: string;
  description: string;
}

interface ParamSpec {
  type: string;
  min: number;
  max: number;
  step: number;
  default: number;
}

interface AlphaFactor {
  name: string;
  expression: string;
  category: string;
  description: string;
}

interface BacktestHistoryEntry {
  id: string;
  strategy_name: string;
  symbol: string;
  start_date: string;
  end_date: string;
  created_at: string;
  sharpe_ratio: number;
  total_return: number;
  max_drawdown: number;
  result?: {
    total_return: number;
    annual_return: number;
    max_drawdown: number;
    sharpe_ratio: number;
    win_rate: number;
    profit_factor: number;
    total_trades: number;
  };
}

const CATEGORY_LABELS: Record<string, string> = {
  value: '价值',
  momentum: '动量',
  quality: '质量',
  volatility: '波动率',
  growth: '成长',
  technical: '技术',
};

function getDifficulty(name: string): Difficulty {
  const lower = name.toLowerCase();
  const expert = ['ml_', 'deep_', 'lstm', 'transformer', 'gan', 'reinforcement', 'alpha', 'multi_factor', 'pair'];
  const pro = ['dual_ma', 'macd', 'kdj', 'bollinger', 'rsi', 'turtle', 'momentum', 'mean_reversion', 'breakout'];
  if (expert.some(e => lower.includes(e))) return 'EXPERT';
  if (pro.some(e => lower.includes(e))) return 'PRO';
  return 'BASIC';
}

const STRATEGY_DETAILS: Record<string, {
  summary: string;
  principle: string;
  suitable: string;
  risk: string;
  params: string;
}> = {
  'dual_ma': {
    summary: '双均线交叉策略',
    principle: '基于短期均线与长期均线的交叉信号进行买卖。当短期均线上穿长期均线（金叉）时买入，下穿（死叉）时卖出。核心逻辑是捕捉趋势的方向性变化。',
    suitable: '适合趋势明显的市场环境，震荡市中容易产生频繁的虚假信号。推荐用于日线级别以上的周期。',
    risk: '均线滞后性导致入场偏晚、出场偏晚；震荡市中频繁交易产生较多手续费磨损。',
    params: '短期均线周期(默认5/10)、长期均线周期(默认20/60)、均线类型(SMA/EMA)',
  },
  'macd': {
    summary: 'MACD指标策略',
    principle: '利用MACD的DIF线与DEA线的交叉、柱状图变化来判断买卖时机。DIF上穿DEA为买入信号，下穿为卖出信号。零轴上方的金叉信号更强。',
    suitable: '适合中长线趋势交易，对波段操作有较好效果。日线和周线级别效果最佳。',
    risk: '与所有趋势指标一样存在滞后性；横盘整理期间信号频繁且不可靠。',
    params: '快线周期(默认12)、慢线周期(默认26)、信号线周期(默认9)',
  },
  'rsi': {
    summary: 'RSI相对强弱指标策略',
    principle: 'RSI衡量价格变动的速度和幅度，取值0-100。RSI>70为超买区（考虑卖出），RSI<30为超卖区（考虑买入）。策略在超卖区买入、超买区卖出。',
    suitable: '适合震荡市和区间交易，对趋势市场的顶底判断有参考价值。',
    risk: '强趋势中RSI可长期停留在超买/超卖区导致过早入场；参数敏感度较高。',
    params: 'RSI周期(默认14)、超买阈值(默认70)、超卖阈值(默认30)',
  },
  'kdj': {
    summary: 'KDJ随机指标策略',
    principle: 'KDJ通过计算最高价、最低价与收盘价的关系来判断超买超卖。K线上穿D线且J值<20为买入信号，K线下穿D线且J值>80为卖出信号。',
    suitable: '适合短线交易和震荡市，对价格拐点较为敏感。',
    risk: 'KDJ敏感度高，容易产生虚假信号；趋势市中可能过早反转。',
    params: 'K周期(默认9)、D周期(默认3)、J平滑系数(默认3)',
  },
  'bollinger': {
    summary: '布林带策略',
    principle: '基于移动平均线±N倍标准差构建上下轨。价格触及下轨时买入（超卖），触及上轨时卖出（超买）。带宽收窄预示大行情即将到来。',
    suitable: '适合震荡市和区间交易，对波动率变化敏感。',
    risk: '趋势市中价格可能沿轨道运行导致持续亏损；参数调整对结果影响大。',
    params: '均线周期(默认20)、标准差倍数(默认2)',
  },
  'turtle': {
    summary: '海龟交易法',
    principle: '基于唐奇安通道突破的趋势跟踪系统。价格突破N日最高价时买入，跌破N日最低价时卖出。配合ATR进行仓位管理和止损，是经典的系统化交易方法。',
    suitable: '适合趋势明显的市场，中长线持仓。需要较大的资金量以承受回撤。',
    risk: '胜率较低（约30-40%），依赖少数大趋势弥补多次小亏损；回撤可能较大。',
    params: '突破周期(默认20/55)、退出周期(默认10/20)、ATR周期(默认20)、风险比例(默认1%)',
  },
  'momentum': {
    summary: '动量策略',
    principle: '买入过去N日涨幅最大的股票，卖出跌幅最大的股票。基于"强者恒强、弱者恒弱"的市场现象，利用价格动量延续性获利。',
    suitable: '适合中期（1-12个月）投资，牛市中表现优异。',
    risk: '动量反转风险：前期涨幅大的股票可能突然回调；换仓频率较高导致交易成本增加。',
    params: '回望周期(默认3-12个月)、持仓周期(默认1个月)、持仓数量(默认10)',
  },
  'mean_reversion': {
    summary: '均值回归策略',
    principle: '基于价格偏离均值后终将回归的统计规律。当价格显著低于均值时买入（低估），高于均值时卖出（高估）。与动量策略逻辑相反。',
    suitable: '适合震荡市和区间波动市场，对个股的估值回归有效。',
    risk: '趋势市中价格可能长期偏离均值导致持续亏损；"这次不一样"风险。',
    params: '均值计算周期(默认20)、入场偏离阈值(默认2倍标准差)、出场阈值(默认0.5倍标准差)',
  },
  'breakout': {
    summary: '突破策略',
    principle: '在价格突破关键支撑/阻力位时入场。包括水平突破、通道突破、形态突破等。突破确认后跟随趋势方向交易。',
    suitable: '适合波动率扩张阶段，盘整后的突破效果最佳。',
    risk: '假突破导致止损；突破后回踩确认可能错过部分利润。',
    params: '突破判定周期(默认20)、确认方式(收盘价/成交量)、止损幅度(默认ATR*2)',
  },
  'ml_random_forest': {
    summary: '随机森林机器学习策略',
    principle: '使用随机森林算法对历史特征数据进行训练，预测未来涨跌方向。特征包括技术指标、价量关系、市场情绪等多维数据。',
    suitable: '适合有充足历史数据的场景，需要定期重新训练模型以适应市场变化。',
    risk: '过拟合风险高；模型对训练数据敏感；市场结构变化时模型失效。',
    params: '树数量(默认100)、最大深度(默认10)、特征数量、训练窗口期',
  },
  'lstm': {
    summary: 'LSTM深度学习策略',
    principle: '使用长短期记忆网络(LSTM)学习价格时序数据中的长期依赖关系。通过多层LSTM单元捕捉价格走势中的复杂模式和转折信号。',
    suitable: '适合捕捉非线性价格模式，对复杂市场结构有较强拟合能力。',
    risk: '深度学习模型黑箱特性强，可解释性差；训练成本高；过拟合风险极高。',
    params: 'LSTM层数(默认2)、隐藏单元数(默认64)、学习率(默认0.001)、序列长度(默认60)',
  },
};

function getStrategyDetail(name: string) {
  const lower = name.toLowerCase();
  if (STRATEGY_DETAILS[lower]) return STRATEGY_DETAILS[lower];
  for (const [key, detail] of Object.entries(STRATEGY_DETAILS)) {
    if (lower.includes(key)) return detail;
  }
  for (const [key, detail] of Object.entries(STRATEGY_DETAILS)) {
    if (key.includes(lower) && lower.length >= 3) return detail;
  }
  return null;
}

const ALPHA_CATEGORY_LABELS: Record<string, string> = {
  momentum: '动量',
  mean_reversion: '均值回归',
  breakout: '突破',
  residual: '残差',
  volume_price: '量价',
  volatility: '波动率',
  trend: '趋势',
  efficiency: '效率',
};

const AlphaFactorPanel = memo(function AlphaFactorPanel() {
  const [alphas, setAlphas] = useState<AlphaFactor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [search, setSearch] = useState('');
  const [activeCategory, setActiveCategory] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    apiGet<AlphaFactor[]>('/alpha/list').then(data => {
      if (!cancelled) { setAlphas(data); setLoading(false); }
    }).catch(() => { if (!cancelled) { setError(true); setLoading(false); } });
    return () => { cancelled = true; };
  }, []);

  const grouped = alphas.reduce<Record<string, AlphaFactor[]>>((acc, a) => {
    (acc[a.category] ??= []).push(a);
    return acc;
  }, {});

  const filtered = alphas.filter(a => {
    const matchSearch = !search || a.name.toLowerCase().includes(search.toLowerCase()) || a.expression.toLowerCase().includes(search.toLowerCase()) || a.description.includes(search);
    const matchCat = !activeCategory || a.category === activeCategory;
    return matchSearch && matchCat;
  });

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em' }}>LOADING...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em' }}>Alpha 因子数据暂无</span>
      </div>
    );
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="搜索因子名称、表达式或描述..."
          style={{
            flex: 1, height: 32, background: 'var(--bg-overlay)',
            border: '1px solid var(--separator)', borderRadius: 'var(--r-sm)',
            padding: '0 10px', color: 'var(--label-primary)', fontFamily: 'var(--font-mono)',
            fontSize: 11, outline: 'none',
          }}
        />
        <button
          onClick={() => setActiveCategory(null)}
          style={{
            height: 32, padding: '0 12px', borderRadius: 'var(--r-sm)',
            border: `1px solid ${!activeCategory ? 'rgba(10,132,255,0.4)' : 'var(--separator)'}`,
            background: !activeCategory ? 'var(--accent-soft)' : 'transparent',
            color: !activeCategory ? 'var(--accent)' : 'var(--label-tertiary)',
            fontFamily: 'var(--font-mono)', fontSize: 10, cursor: 'pointer',
          }}
        >
          全部
        </button>
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {Object.keys(grouped).map(cat => (
          <button
            key={cat}
            onClick={() => setActiveCategory(cat === activeCategory ? null : cat)}
            style={{
              height: 26, padding: '0 10px', borderRadius: 'var(--r-xs)',
              border: `1px solid ${activeCategory === cat ? 'rgba(10,132,255,0.4)' : 'var(--separator)'}`,
              background: activeCategory === cat ? 'var(--accent-soft)' : 'transparent',
              color: activeCategory === cat ? 'var(--accent)' : 'var(--label-tertiary)',
              fontFamily: 'var(--font-mono)', fontSize: 9, cursor: 'pointer',
              letterSpacing: '0.04em',
            }}
          >
            {ALPHA_CATEGORY_LABELS[cat] ?? cat} ({grouped[cat]!.length})
          </button>
        ))}
      </div>

      <div style={{ flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
        {filtered.length === 0 && (
          <div style={{ textAlign: 'center', padding: '40px 0' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'rgba(255,255,255,0.35)' }}>无匹配因子</span>
          </div>
        )}
        {filtered.map(alpha => (
          <div
            key={alpha.name}
            style={{
              background: 'var(--bg-elevated)', borderRadius: 'var(--r-md)',
              border: '1px solid var(--separator)', padding: '14px 16px',
              transition: 'border-color var(--dur-fast)',
            }}
            onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.borderColor = 'rgba(10,132,255,0.3)'; }}
            onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--separator)'; }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 500,
                color: 'var(--accent)',
              }}>
                {alpha.name}
              </span>
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: 9, padding: '2px 6px',
                borderRadius: 'var(--r-xs)', background: 'rgba(10,132,255,0.1)',
                color: 'var(--accent)',
              }}>
                {ALPHA_CATEGORY_LABELS[alpha.category] ?? alpha.category}
              </span>
            </div>
            <div style={{
              fontFamily: 'var(--font-mono)', fontSize: 10,
              color: 'rgba(255,255,255,0.5)',
              background: 'rgba(0,0,0,0.3)', borderRadius: 'var(--r-xs)',
              padding: '6px 8px', marginBottom: 6,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {alpha.expression}
            </div>
            <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', lineHeight: 1.5 }}>
              {alpha.description}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
});

const BacktestHistoryPanel = memo(function BacktestHistoryPanel() {
  const [history, setHistory] = useState<BacktestHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [sortKey, setSortKey] = useState<'sharpe_ratio' | 'total_return' | 'created_at'>('created_at');
  const [sortAsc, setSortAsc] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    apiGet<BacktestHistoryEntry[]>('/backtest/history').then(data => {
      if (!cancelled) { setHistory(Array.isArray(data) ? data : []); setLoading(false); }
    }).catch(() => { if (!cancelled) { setError(true); setLoading(false); } });
    return () => { cancelled = true; };
  }, []);

  const sorted = [...history].sort((a, b) => {
    let aVal: number, bVal: number;
    if (sortKey === 'created_at') {
      aVal = new Date(a.created_at).getTime();
      bVal = new Date(b.created_at).getTime();
    } else {
      aVal = a[sortKey] as number;
      bVal = b[sortKey] as number;
    }
    return sortAsc ? aVal - bVal : bVal - aVal;
  });

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em' }}>LOADING...</span>
      </div>
    );
  }

  if (error || history.length === 0) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '200px', gap: 8 }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'rgba(255,255,255,0.35)', letterSpacing: '0.06em' }}>回测历史暂无</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'rgba(255,255,255,0.2)' }}>运行策略回测后将显示历史记录</span>
      </div>
    );
  }

  const thStyle: React.CSSProperties = {
    padding: '8px 12px', textAlign: 'left',
    fontFamily: 'var(--font-mono)', fontSize: 9, textTransform: 'uppercase',
    letterSpacing: '0.06em', color: 'var(--label-tertiary)',
    background: 'var(--bg-elevated)', borderBottom: '1px solid var(--separator)',
    cursor: 'pointer', userSelect: 'none',
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--label-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          共 {history.length} 条记录
        </span>
      </div>
      <div style={{ flex: 1, overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={thStyle} onClick={() => { setSortKey('created_at'); setSortAsc(p => !p); }}>
                时间 {sortKey === 'created_at' ? (sortAsc ? '↑' : '↓') : ''}
              </th>
              <th style={thStyle}>策略</th>
              <th style={thStyle}>标的</th>
              <th style={{ ...thStyle, textAlign: 'right' }} onClick={() => { setSortKey('sharpe_ratio'); setSortAsc(p => !p); }}>
                夏普 {sortKey === 'sharpe_ratio' ? (sortAsc ? '↑' : '↓') : ''}
              </th>
              <th style={{ ...thStyle, textAlign: 'right' }} onClick={() => { setSortKey('total_return'); setSortAsc(p => !p); }}>
                总收益 {sortKey === 'total_return' ? (sortAsc ? '↑' : '↓') : ''}
              </th>
              <th style={{ ...thStyle, textAlign: 'right' }}>最大回撤</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>交易次数</th>
            </tr>
          </thead>
          <tbody>
            {sorted.slice(0, 100).map((entry) => {
              const result = entry.result;
              return (
                <tr key={entry.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-tertiary)' }}>
                    {entry.created_at.slice(0, 16)}
                  </td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent)' }}>
                    {entry.strategy_name}
                  </td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'rgba(255,255,255,0.6)' }}>
                    {entry.symbol}
                  </td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, textAlign: 'right', color: entry.sharpe_ratio >= 1 ? '#00C853' : entry.sharpe_ratio >= 0.5 ? '#FF9100' : '#FF1744', fontVariantNumeric: 'tabular-nums' }}>
                    {entry.sharpe_ratio.toFixed(2)}
                  </td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, textAlign: 'right', color: entry.total_return >= 0 ? '#FF1744' : '#00C853', fontVariantNumeric: 'tabular-nums' }}>
                    {entry.total_return >= 0 ? '+' : ''}{(entry.total_return * 100).toFixed(1)}%
                  </td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, textAlign: 'right', color: '#00C853', fontVariantNumeric: 'tabular-nums' }}>
                    {(entry.max_drawdown * 100).toFixed(1)}%
                  </td>
                  <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, textAlign: 'right', color: 'rgba(255,255,255,0.5)', fontVariantNumeric: 'tabular-nums' }}>
                    {result?.total_trades ?? '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
});

const EquityCanvas = memo(function EquityCanvas({ data, showDrawdown }: { data: Array<{ date: string; value: number }>; showDrawdown: boolean }) {
  const draw = useCallback((ctx: CanvasRenderingContext2D, w: number, h: number) => {
    if (data.length < 2) return;
    const pad = { top: 20, right: 20, bottom: 32, left: 20 };
    const values = data.map(d => d.value);
    const minVal = Math.min(...values);
    const maxVal = Math.max(...values);
    const range = maxVal - minVal || 1;
    ctx.clearRect(0, 0, w, h);

    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = pad.top + (i / 4) * (h - pad.top - pad.bottom);
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(w - pad.right, y);
      ctx.stroke();
    }

    const isPositive = values[values.length - 1]! >= values[0]!;
    const lineColor = isPositive ? '#FF1744' : '#00C853';
    const fillTop = isPositive ? 'rgba(255,23,68,0.10)' : 'rgba(0,200,83,0.10)';
    const fillBot = isPositive ? 'rgba(255,23,68,0)' : 'rgba(0,200,83,0)';

    const gradient = ctx.createLinearGradient(0, pad.top, 0, h - pad.bottom);
    gradient.addColorStop(0, fillTop);
    gradient.addColorStop(1, fillBot);
    ctx.beginPath();
    ctx.moveTo(pad.left, h - pad.bottom);
    for (let i = 0; i < values.length; i++) {
      const x = pad.left + (i / (values.length - 1)) * (w - pad.left - pad.right);
      const y = pad.top + (1 - (values[i]! - minVal) / range) * (h - pad.top - pad.bottom);
      ctx.lineTo(x, y);
    }
    ctx.lineTo(pad.left + (w - pad.left - pad.right), h - pad.bottom);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    ctx.beginPath();
    for (let i = 0; i < values.length; i++) {
      const x = pad.left + (i / (values.length - 1)) * (w - pad.left - pad.right);
      const y = pad.top + (1 - (values[i]! - minVal) / range) * (h - pad.top - pad.bottom);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 2;
    ctx.stroke();

    if (showDrawdown && values.length > 1) {
      let peak = values[0]!;
      const drawdowns = values.map(v => {
        if (v > peak) peak = v;
        return (v - peak) / peak;
      });
      const ddMin = Math.min(...drawdowns);
      const ddGradient = ctx.createLinearGradient(0, pad.top, 0, h - pad.bottom);
      ddGradient.addColorStop(0, 'rgba(0,200,83,0)');
      ddGradient.addColorStop(1, 'rgba(0,200,83,0.08)');
      ctx.beginPath();
      const baseline = pad.top + (1 - 0) * (h - pad.top - pad.bottom);
      ctx.moveTo(pad.left, baseline);
      for (let i = 0; i < drawdowns.length; i++) {
        const x = pad.left + (i / (drawdowns.length - 1)) * (w - pad.left - pad.right);
        const y = pad.top + (1 - drawdowns[i]! / ddMin) * (h - pad.top - pad.bottom) * 0.3 + baseline * 0.7;
        ctx.lineTo(x, y);
      }
      ctx.lineTo(pad.left + (w - pad.left - pad.right), baseline);
      ctx.closePath();
      ctx.fillStyle = ddGradient;
      ctx.fill();
    }

    const dateLabels = [0, Math.floor(values.length / 4), Math.floor(values.length / 2), Math.floor(values.length * 3 / 4), values.length - 1];
    ctx.font = '10px SF Mono, JetBrains Mono, monospace';
    ctx.textAlign = 'center';
    for (const idx of dateLabels) {
      const x = pad.left + (idx / (values.length - 1)) * (w - pad.left - pad.right);
      const dateStr = data[idx]?.date?.slice(0, 7) ?? '';
      ctx.fillStyle = 'rgba(255,255,255,0.20)';
      ctx.fillText(dateStr, x, h - 8);
    }
  }, [data, showDrawdown]);

  const { ref } = useCanvas(draw, [data, showDrawdown]);
  return <canvas ref={ref} style={{ width: '100%', height: 320 }} />;
});

const TradeTable = memo(function TradeTable({ trades }: { trades: Array<Record<string, unknown>> }) {
  if (!trades || trades.length === 0) return null;
  return (
    <div style={{ marginTop: 24 }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase',
        letterSpacing: '0.08em', color: 'var(--label-tertiary)', padding: '0 0 10px 0',
        borderBottom: '1px solid var(--separator)',
      }}>
        TRADE DETAILS ({trades.length})
      </div>
      <div style={{ maxHeight: 300, overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              {['DATE', 'TYPE', 'PRICE', 'QTY', 'P&L'].map(h => (
                <th key={h} style={{
                  padding: '8px 12px', textAlign: 'left',
                  fontFamily: 'var(--font-mono)', fontSize: 9, textTransform: 'uppercase',
                  letterSpacing: '0.08em', color: 'var(--label-tertiary)',
                  background: 'var(--bg-elevated)', borderBottom: '1px solid var(--separator)',
                  position: 'sticky' as const, top: 0, zIndex: 1,
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {trades.slice(0, 50).map((t, i) => {
              const type = (t.type ?? t.action ?? '') as string;
              const isBuy = type.toLowerCase().includes('buy');
              return (
                <tr key={i} style={{ height: 32, borderBottom: '1px solid var(--separator)' }}>
                  <td style={{ padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-secondary)' }}>{String(t.date ?? t.entry_date ?? '')}</td>
                  <td style={{ padding: '0 12px' }}>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: 9, textTransform: 'uppercase',
                      letterSpacing: '0.06em', padding: '2px 8px', borderRadius: 'var(--r-xs)',
                      background: isBuy ? 'var(--rise-bg)' : 'var(--fall-bg)',
                      color: isBuy ? 'var(--signal-rise)' : 'var(--signal-fall)',
                    }}>
                      {isBuy ? 'BUY' : 'SELL'}
                    </span>
                  </td>
                  <td style={{ padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-primary)', fontVariantNumeric: 'tabular-nums' }}>{formatPrice(Number(t.price ?? t.entry_price ?? 0))}</td>
                  <td style={{ padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-secondary)', fontVariantNumeric: 'tabular-nums' }}>{String(t.quantity ?? t.shares ?? '')}</td>
                  <td style={{ padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: 11, fontVariantNumeric: 'tabular-nums', color: Number(t.pnl ?? t.profit ?? 0) >= 0 ? 'var(--signal-rise)' : 'var(--signal-fall)' }}>
                    {formatRatio(Number(t.pnl ?? t.profit ?? t.return ?? 0))}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
});

const BacktestResults = memo(function BacktestResults({ result, showDrawdown, onToggleDrawdown, onBack }: { result: BacktestResult; showDrawdown: boolean; onToggleDrawdown: () => void; onBack: () => void }) {
  const metrics: Array<[string, string, string]> = [
    ['TOTAL RETURN', formatRatio(result.total_return), result.total_return >= 0 ? '#FF1744' : '#00C853'],
    ['ANNUAL RETURN', formatRatio(result.annual_return), result.annual_return >= 0 ? '#FF1744' : '#00C853'],
    ['SHARPE RATIO', result.sharpe_ratio.toFixed(2), result.sharpe_ratio >= 1 ? '#FF1744' : '#FF9100'],
    ['MAX DRAWDOWN', formatRatio(result.max_drawdown), '#00C853'],
    ['WIN RATE', formatRatio(result.win_rate), result.win_rate >= 0.5 ? '#FF1744' : '#FF9100'],
    ['PROFIT FACTOR', result.profit_factor.toFixed(2), result.profit_factor >= 1 ? '#FF1744' : '#00C853'],
    ['TOTAL TRADES', result.total_trades.toString(), 'var(--label-primary)'],
    ['CALMAR RATIO', result.calmar_ratio.toFixed(2), result.calmar_ratio >= 1 ? '#FF1744' : '#FF9100'],
  ];

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <button
          onClick={onBack}
          style={{
            display: 'flex', alignItems: 'center', gap: 4,
            fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-tertiary)',
            background: 'transparent', border: '1px solid var(--separator)',
            borderRadius: 'var(--r-xs)', padding: '6px 12px', cursor: 'pointer',
            transition: 'all var(--dur-fast) var(--ease-apple)',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.color = 'var(--accent)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--separator)'; e.currentTarget.style.color = 'var(--label-tertiary)'; }}
        >
          ← 返回
        </button>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--label-tertiary)' }}>BACKTEST RESULTS</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1, background: 'var(--separator)', marginBottom: 24, borderRadius: 'var(--r-md)', overflow: 'hidden' }}>
        {metrics.map(([label, value, color]) => (
          <div key={label} style={{ background: 'var(--bg-elevated)', padding: '16px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--label-tertiary)' }}>{label}</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 20, fontWeight: 600, color, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
          </div>
        ))}
      </div>
      {result.equity_curve && result.equity_curve.length > 0 && (
        <div style={{ background: 'var(--bg-elevated)', borderRadius: 'var(--r-md)', overflow: 'hidden' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 20px', borderBottom: '1px solid var(--separator)' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--label-secondary)' }}>EQUITY CURVE</span>
            <button
              onClick={onToggleDrawdown}
              style={{
                fontFamily: 'var(--font-mono)', fontSize: 9, textTransform: 'uppercase',
                letterSpacing: '0.06em', padding: '4px 10px', borderRadius: 'var(--r-xs)',
                background: showDrawdown ? 'var(--rise-bg)' : 'transparent',
                color: showDrawdown ? 'var(--signal-rise)' : 'var(--label-tertiary)',
                border: `1px solid ${showDrawdown ? 'rgba(255,23,68,0.2)' : 'var(--separator)'}`,
                cursor: 'pointer',
                transition: 'all var(--dur-fast) var(--ease-apple)',
              }}
            >
              DRAWDOWN
            </button>
          </div>
          <div style={{ padding: '8px 4px 4px' }}>
            <EquityCanvas data={result.equity_curve} showDrawdown={showDrawdown} />
          </div>
        </div>
      )}
      {result.trades && result.trades.length > 0 && (
        <TradeTable trades={result.trades} />
      )}
    </div>
  );
});

const StrategyDetailPanel = memo(function StrategyDetailPanel({ name, description }: { name: string; description: string }) {
  const detail = getStrategyDetail(name);

  const sectionLabel: React.CSSProperties = {
    fontFamily: 'var(--font-mono)', fontSize: 9, textTransform: 'uppercase',
    letterSpacing: '0.08em', color: 'var(--label-tertiary)', marginBottom: 4, marginTop: 12,
  };

  const sectionContent: React.CSSProperties = {
    fontSize: 12, color: 'var(--label-secondary)', lineHeight: 1.7,
  };

  if (!detail) {
    return (
      <div style={{ marginBottom: 20, paddingBottom: 16, borderBottom: '1px solid var(--separator)' }}>
        <div style={{ fontSize: 17, fontWeight: 600, color: 'var(--label-primary)', marginBottom: 4 }}>{name}</div>
        <div style={sectionContent}>{description}</div>
      </div>
    );
  }

  return (
    <div style={{ marginBottom: 20, paddingBottom: 16, borderBottom: '1px solid var(--separator)' }}>
      <div style={{ fontSize: 17, fontWeight: 600, color: 'var(--label-primary)', marginBottom: 2 }}>{name}</div>
      <div style={{ fontSize: 13, color: 'var(--accent)', marginBottom: 8 }}>{detail.summary}</div>
      <div style={sectionLabel}>策略原理</div>
      <div style={sectionContent}>{detail.principle}</div>
      <div style={sectionLabel}>适用场景</div>
      <div style={sectionContent}>{detail.suitable}</div>
      <div style={sectionLabel}>风险提示</div>
      <div style={sectionContent}>{detail.risk}</div>
      <div style={sectionLabel}>关键参数</div>
      <div style={sectionContent}>{detail.params}</div>
    </div>
  );
});

const FactorRegistryPanel = memo(function FactorRegistryPanel({ factors }: { factors: FactorInfo[] }) {
  const grouped = factors.reduce<Record<string, FactorInfo[]>>((acc, f) => {
    (acc[f.category] ??= []).push(f);
    return acc;
  }, {});

  const categoryOrder = ['value', 'momentum', 'quality', 'volatility', 'growth', 'technical'];
  const sortedCategories = categoryOrder.filter(c => grouped[c]);

  return (
    <div style={{ height: '100%', overflow: 'auto' }}>
      <div style={{
        fontFamily: 'var(--font-sans)', fontSize: 17, fontWeight: 600,
        color: 'var(--label-primary)', letterSpacing: '-0.01em', marginBottom: 20,
      }}>
        因子库
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
        {sortedCategories.map(category => (
          <div key={category}>
            <div style={{
              fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase',
              letterSpacing: '0.08em', color: 'var(--accent)', marginBottom: 10,
              paddingBottom: 6, borderBottom: '1px solid var(--separator)',
            }}>
              {CATEGORY_LABELS[category] ?? category}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 8 }}>
              {grouped[category]!.map(factor => (
                <div key={factor.name} style={{
                  background: 'var(--bg-elevated)', borderRadius: 'var(--r-md)',
                  padding: '12px 16px', border: '1px solid var(--separator)',
                  transition: 'border-color var(--dur-fast) var(--ease-apple)',
                }}
                  onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'rgba(10,132,255,0.3)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--separator)'; }}
                >
                  <div style={{
                    fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 500,
                    color: 'var(--accent)', marginBottom: 4,
                  }}>
                    {factor.name}
                  </div>
                  <div style={{
                    fontSize: 11, color: 'var(--label-secondary)', lineHeight: 1.5,
                  }}>
                    {factor.description}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
});

export function StrategyPage() {
  const { strategies, selectedStrategy, backtestResult, backtestRunning, backtestLogs, fetchStrategies, selectStrategy, runBacktest, clearResult } = useStrategyStore();
  const [symbol, setSymbol] = useState('000001.SZ');
  const [startDate, setStartDate] = useState('2022-12-31');
  const [endDate, setEndDate] = useState('2025-12-31');
  const [capital, setCapital] = useState('1000000');
  const [showDrawdown, setShowDrawdown] = useState(false);
  const [timeRange, setTimeRange] = useState('3Y');
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [commissionRate, setCommissionRate] = useState('0.0003');
  const [slippage, setSlippage] = useState('0.001');
  const [leverage, setLeverage] = useState('1');
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({ BASIC: true, PRO: true, EXPERT: true });
  const [factorData, setFactorData] = useState<FactorInfo[] | null>(null);
  const [paramSpecs, setParamSpecs] = useState<Record<string, ParamSpec> | null>(null);
  const [factorTab, setFactorTab] = useState<'registry' | 'alpha' | 'history'>('registry');
  const logRef = useRef<HTMLDivElement>(null);
  const [cursorVisible, setCursorVisible] = useState(true);

  useEffect(() => { fetchStrategies(); }, [fetchStrategies]);

  useEffect(() => {
    let cancelled = false;
    apiGet<FactorInfo[]>('/factor/registry').then(data => {
      if (!cancelled) setFactorData(data);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!selectedStrategy) {
      setParamSpecs(null);
      return;
    }
    let cancelled = false;
    apiGet<{ strategies: Record<string, Record<string, ParamSpec>> }>('/strategy/param-specs', { strategy: selectedStrategy })
      .then(data => {
        if (cancelled) return;
        const specs = data?.strategies;
        if (specs) {
          const firstKey = Object.keys(specs)[0];
          setParamSpecs(firstKey ? specs[firstKey]! : null);
        } else {
          setParamSpecs(null);
        }
      })
      .catch(() => {
        if (!cancelled) setParamSpecs(null);
      });
    return () => { cancelled = true; };
  }, [selectedStrategy]);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [backtestLogs]);

  useEffect(() => {
    if (!backtestRunning) return;
    const interval = setInterval(() => setCursorVisible(v => !v), 530);
    return () => clearInterval(interval);
  }, [backtestRunning]);

  const handleTimeRange = useCallback((range: string) => {
    setTimeRange(range);
    if (range !== 'CUSTOM') {
      const end = new Date(endDate);
      end.setFullYear(end.getFullYear() - parseInt(range));
      setStartDate(end.toISOString().split('T')[0] ?? startDate);
    }
  }, [endDate, startDate]);

  const handleRun = useCallback(() => {
    if (!selectedStrategy) return;
    runBacktest({ symbol, start_date: startDate, end_date: endDate, initial_capital: Number(capital) });
  }, [selectedStrategy, symbol, startDate, endDate, capital, runBacktest]);

  const toggleGroup = useCallback((group: string) => {
    setOpenGroups(prev => ({ ...prev, [group]: !prev[group] }));
  }, []);

  const handleSelectStrategy = useCallback((name: string) => {
    selectStrategy(name);
    clearResult();
  }, [selectStrategy, clearResult]);

  const toggleDrawdown = useCallback(() => setShowDrawdown(v => !v), []);

  const handleBackFromResults = useCallback(() => {
    clearResult();
  }, [clearResult]);

  const currentStrategy = strategies.find(s => s.name === selectedStrategy);

  const grouped: Record<Difficulty, typeof strategies> = { BASIC: [], PRO: [], EXPERT: [] };
  for (const s of strategies) {
    grouped[getDifficulty(s.name)].push(s);
  }

  const inputStyle: React.CSSProperties = {
    width: '100%', height: 40, background: 'var(--bg-overlay)',
    border: '1px solid var(--separator)', borderRadius: 'var(--r-md)',
    padding: '0 12px', color: 'var(--label-primary)', fontFamily: 'var(--font-mono)',
    fontSize: 12, outline: 'none', boxSizing: 'border-box',
    transition: 'border-color var(--dur-fast) var(--ease-apple)',
  };

  const labelStyle: React.CSSProperties = {
    display: 'block', fontFamily: 'var(--font-mono)', fontSize: 9,
    textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--label-tertiary)',
    marginBottom: 4,
  };

  return (
    <div style={{ display: 'flex', height: '100%', background: 'var(--bg-base)', padding: 'var(--s6)', boxSizing: 'border-box' }}>
      <div style={{ width: 280, flexShrink: 0, background: 'var(--bg-elevated)', borderRight: '1px solid var(--separator)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--separator)' }}>
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: 17, fontWeight: 600, color: 'var(--label-primary)', letterSpacing: '-0.01em' }}>策略引擎</span>
        </div>
        <div style={{ flex: 1, overflow: 'auto' }}>
          {(['BASIC', 'PRO', 'EXPERT'] as Difficulty[]).map(group => (
            <div key={group}>
              <div
                onClick={() => toggleGroup(group)}
                style={{
                  padding: '10px 20px', cursor: 'pointer',
                  borderBottom: '1px solid var(--separator)',
                  display: 'flex', alignItems: 'center', gap: 6,
                  userSelect: 'none',
                }}
              >
                <span style={{
                  fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--label-tertiary)',
                  transition: 'transform var(--dur-fast) var(--ease-apple)',
                  display: 'inline-block',
                  transform: openGroups[group] ? 'rotate(0deg)' : 'rotate(-90deg)',
                }}>▼</span>
                <span style={{
                  fontFamily: 'var(--font-mono)', fontSize: 10, textTransform: 'uppercase',
                  letterSpacing: '0.08em', color: 'var(--label-tertiary)',
                }}>{group}</span>
                <span style={{
                  fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--label-quaternary)',
                }}>{grouped[group].length}</span>
              </div>
              {openGroups[group] && grouped[group].map(s => {
                const isActive = selectedStrategy === s.name;
                return (
                  <div
                    key={s.name}
                    onClick={() => handleSelectStrategy(s.name)}
                    style={{
                      padding: '10px 20px', cursor: 'pointer',
                      borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
                      background: isActive ? 'var(--accent-soft)' : 'transparent',
                      transition: 'all var(--dur-fast) var(--ease-apple)',
                    }}
                    onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = 'rgba(255,255,255,0.02)'; }}
                    onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
                  >
                    <div style={{
                      fontFamily: 'var(--font-mono)', fontSize: 12,
                      color: isActive ? 'var(--accent)' : 'var(--label-primary)',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>{s.name}</div>
                    <div style={{
                      fontFamily: 'var(--font-sans)', fontSize: 11, color: 'var(--label-tertiary)',
                      marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>{s.description}</div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      <div style={{ width: 280, flexShrink: 0, borderRight: '1px solid var(--separator)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ flex: 1, overflow: 'auto', padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
          {selectedStrategy && currentStrategy && (
            <StrategyDetailPanel name={currentStrategy.name} description={currentStrategy.description} />
          )}
          {paramSpecs && Object.keys(paramSpecs).length > 0 && (
            <div style={{ marginBottom: 4 }}>
              <div style={{
                fontFamily: 'var(--font-mono)', fontSize: 9, textTransform: 'uppercase',
                letterSpacing: '0.08em', color: 'var(--label-tertiary)', marginBottom: 8,
              }}>
                参数规格
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    {['参数', '类型', '范围', '步长', '默认值'].map(h => (
                      <th key={h} style={{
                        padding: '4px 6px', textAlign: 'left',
                        fontFamily: 'var(--font-mono)', fontSize: 9, textTransform: 'uppercase',
                        letterSpacing: '0.06em', color: 'var(--label-tertiary)',
                        borderBottom: '1px solid var(--separator)',
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(paramSpecs).map(([name, spec]) => (
                    <tr key={name} style={{ borderBottom: '1px solid var(--separator)' }}>
                      <td style={{ padding: '4px 6px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent)' }}>{name}</td>
                      <td style={{ padding: '4px 6px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-secondary)' }}>{spec.type}</td>
                      <td style={{ padding: '4px 6px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-secondary)', fontVariantNumeric: 'tabular-nums' }}>{spec.min}–{spec.max}</td>
                      <td style={{ padding: '4px 6px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-secondary)', fontVariantNumeric: 'tabular-nums' }}>{spec.step}</td>
                      <td style={{ padding: '4px 6px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--label-primary)', fontVariantNumeric: 'tabular-nums' }}>{spec.default}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: 17, fontWeight: 600, color: 'var(--label-primary)', letterSpacing: '-0.01em' }}>参数配置</span>

          <div>
            <label style={labelStyle}>SYMBOL</label>
            <input value={symbol} onChange={e => setSymbol(e.target.value)} style={inputStyle} />
          </div>

          <div>
            <label style={labelStyle}>TIME RANGE</label>
            <div style={{ display: 'flex', gap: 4 }}>
              {['1Y', '3Y', '5Y', 'CUSTOM'].map(r => (
                <button
                  key={r}
                  onClick={() => handleTimeRange(r)}
                  style={{
                    flex: 1, height: 32, border: '1px solid var(--separator)',
                    borderRadius: 'var(--r-xs)', cursor: 'pointer',
                    fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 500,
                    letterSpacing: '0.04em',
                    background: timeRange === r ? 'var(--accent-soft)' : 'transparent',
                    color: timeRange === r ? 'var(--accent)' : 'var(--label-tertiary)',
                    borderColor: timeRange === r ? 'rgba(10,132,255,0.3)' : 'var(--separator)',
                    transition: 'all var(--dur-fast) var(--ease-apple)',
                  }}
                >
                  {r}
                </button>
              ))}
            </div>
            {timeRange === 'CUSTOM' && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 8 }}>
                <div>
                  <label style={{ ...labelStyle, marginBottom: 2 }}>START</label>
                  <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} style={inputStyle} />
                </div>
                <div>
                  <label style={{ ...labelStyle, marginBottom: 2 }}>END</label>
                  <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} style={inputStyle} />
                </div>
              </div>
            )}
          </div>

          <div>
            <label style={labelStyle}>CAPITAL</label>
            <input value={capital} onChange={e => setCapital(e.target.value)} style={inputStyle} />
          </div>

          <div>
            <div
              onClick={() => setAdvancedOpen(v => !v)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
                padding: '8px 0', userSelect: 'none',
                borderBottom: '1px solid var(--separator)',
              }}
            >
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--label-tertiary)',
                display: 'inline-block',
                transition: 'transform var(--dur-fast) var(--ease-apple)',
                transform: advancedOpen ? 'rotate(0deg)' : 'rotate(-90deg)',
              }}>▼</span>
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: 9, textTransform: 'uppercase',
                letterSpacing: '0.08em', color: 'var(--label-tertiary)',
              }}>ADVANCED</span>
            </div>
            {advancedOpen && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12, paddingTop: 12 }}>
                <div>
                  <label style={labelStyle}>COMMISSION RATE</label>
                  <input value={commissionRate} onChange={e => setCommissionRate(e.target.value)} style={inputStyle} />
                </div>
                <div>
                  <label style={labelStyle}>SLIPPAGE</label>
                  <input value={slippage} onChange={e => setSlippage(e.target.value)} style={inputStyle} />
                </div>
                <div>
                  <label style={labelStyle}>LEVERAGE</label>
                  <input value={leverage} onChange={e => setLeverage(e.target.value)} style={inputStyle} />
                </div>
              </div>
            )}
          </div>
        </div>

        <div style={{ padding: '0 20px 20px' }}>
          <button
            onClick={handleRun}
            disabled={backtestRunning || !selectedStrategy}
            style={{
              width: '100%', height: 48,
              background: backtestRunning || !selectedStrategy ? 'var(--bg-overlay)' : 'var(--accent)',
              color: backtestRunning || !selectedStrategy ? 'var(--label-quaternary)' : '#FFFFFF',
              border: 'none', borderRadius: 'var(--r-md)',
              fontFamily: 'var(--font-sans)', fontSize: 13, fontWeight: 600,
              letterSpacing: '0.02em', cursor: backtestRunning || !selectedStrategy ? 'not-allowed' : 'pointer',
              transition: 'all var(--dur-fast) var(--ease-apple)',
            }}
          >
            {backtestRunning ? 'RUNNING...' : 'RUN BACKTEST'}
          </button>
        </div>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>
        {!backtestRunning && !backtestResult && factorData && (
          <div style={{ marginBottom: 16, display: 'flex', gap: 4 }}>
            <button
              onClick={() => setFactorTab('registry')}
              style={{
                height: 32, padding: '0 16px', borderRadius: 'var(--r-sm)',
                border: `1px solid ${factorTab === 'registry' ? 'rgba(10,132,255,0.4)' : 'var(--separator)'}`,
                background: factorTab === 'registry' ? 'var(--accent-soft)' : 'transparent',
                color: factorTab === 'registry' ? 'var(--accent)' : 'var(--label-tertiary)',
                fontFamily: 'var(--font-mono)', fontSize: 11, cursor: 'pointer',
              }}
            >
              因子库
            </button>
            <button
              onClick={() => setFactorTab('alpha')}
              style={{
                height: 32, padding: '0 16px', borderRadius: 'var(--r-sm)',
                border: `1px solid ${factorTab === 'alpha' ? 'rgba(10,132,255,0.4)' : 'var(--separator)'}`,
                background: factorTab === 'alpha' ? 'var(--accent-soft)' : 'transparent',
                color: factorTab === 'alpha' ? 'var(--accent)' : 'var(--label-tertiary)',
                fontFamily: 'var(--font-mono)', fontSize: 11, cursor: 'pointer',
              }}
            >
              Alpha 表达式库
            </button>
            <button
              onClick={() => setFactorTab('history')}
              style={{
                height: 32, padding: '0 16px', borderRadius: 'var(--r-sm)',
                border: `1px solid ${factorTab === 'history' ? 'rgba(10,132,255,0.4)' : 'var(--separator)'}`,
                background: factorTab === 'history' ? 'var(--accent-soft)' : 'transparent',
                color: factorTab === 'history' ? 'var(--accent)' : 'var(--label-tertiary)',
                fontFamily: 'var(--font-mono)', fontSize: 11, cursor: 'pointer',
              }}
            >
              回测历史
            </button>
          </div>
        )}

        {backtestRunning ? (
          <div
            ref={logRef}
            style={{
              fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--label-tertiary)',
              lineHeight: 1.8, height: '100%', overflow: 'auto',
            }}
          >
            {backtestLogs.map((log, i) => (
              <div key={i}>{log}</div>
            ))}
            <span style={{ opacity: cursorVisible ? 1 : 0, transition: 'opacity 100ms' }}>▌</span>
          </div>
        ) : backtestResult ? (
          <BacktestResults result={backtestResult} showDrawdown={showDrawdown} onToggleDrawdown={toggleDrawdown} onBack={handleBackFromResults} />
        ) : factorData ? (
          factorTab === 'registry' ? <FactorRegistryPanel factors={factorData} /> :
          factorTab === 'alpha' ? <AlphaFactorPanel /> :
          factorTab === 'history' ? <BacktestHistoryPanel /> : null
        ) : null}
      </div>
    </div>
  );
}
