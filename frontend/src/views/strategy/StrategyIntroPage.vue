<template>
  <div class="strategy-intro-page">
    <div class="page-header">
      <h1 class="page-title">量化策略百科</h1>
      <p class="page-desc">从入门到精通，了解每种策略的原理、适用场景和风险</p>
    </div>

    <div class="category-tabs">
      <button
        v-for="cat in categories"
        :key="cat.key"
        class="cat-btn"
        :class="{ active: activeCategory === cat.key }"
        @click="activeCategory = cat.key"
      >
        <span class="cat-icon" v-html="cat.icon" />
        {{ cat.label }}
      </button>
    </div>

    <div class="strategy-grid">
      <div
        v-for="s in filteredStrategies"
        :key="s.name"
        class="strategy-card"
        @click="selectedStrategy = s"
      >
        <div class="sc-header">
          <span class="sc-name">{{ strategyDisplayName(s.name) }}</span>
          <span class="sc-difficulty" :class="s.difficulty">{{ difficultyLabel(s.difficulty) }}</span>
        </div>
        <p class="sc-desc">{{ s.description }}</p>
        <div class="sc-footer">
          <div class="sc-tags">
            <span class="sc-tag">{{ s.category }}</span>
            <span v-if="s.paramCount" class="sc-tag">{{ s.paramCount }}个参数</span>
          </div>
          <router-link
            :to="`/strategy/run?strategy=${s.name}`"
            class="sc-backtest-btn"
            @click.stop
          >
            回测
          </router-link>
        </div>
      </div>
    </div>

    <transition name="fade">
      <div v-if="selectedStrategy" class="detail-overlay" @click.self="selectedStrategy = null">
        <div class="detail-modal">
          <button class="close-btn" @click="selectedStrategy = null">✕</button>
          <div class="detail-header">
            <h2 class="detail-name">{{ strategyDisplayName(selectedStrategy.name) }}</h2>
            <span class="detail-difficulty" :class="selectedStrategy.difficulty">
              {{ difficultyLabel(selectedStrategy.difficulty) }}
            </span>
          </div>

          <div class="detail-body">
            <section class="detail-section">
              <h3>策略简介</h3>
              <p>{{ selectedStrategy.description }}</p>
            </section>

            <section class="detail-section">
              <h3>核心原理</h3>
              <p>{{ selectedStrategy.principle }}</p>
            </section>

            <section class="detail-section">
              <h3>适用场景</h3>
              <p>{{ selectedStrategy.scenario }}</p>
            </section>

            <section class="detail-section">
              <h3>风险提示</h3>
              <p>{{ selectedStrategy.risk }}</p>
            </section>

            <section class="detail-section" v-if="selectedStrategy.params.length">
              <h3>参数说明</h3>
              <div class="param-list">
                <div v-for="p in selectedStrategy.params" :key="p.name" class="param-item">
                  <div class="param-header">
                    <span class="param-name">{{ p.label }}</span>
                    <span class="param-range mono">{{ p.min }} ~ {{ p.max }} (步长{{ p.step }})</span>
                  </div>
                  <p class="param-desc">{{ p.desc }}</p>
                </div>
              </div>
            </section>

            <div class="detail-actions">
              <router-link :to="`/strategy/run?strategy=${selectedStrategy.name}`" class="run-btn">
                运行回测
              </router-link>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api } from '@/api'
import { strategyDisplayName } from '@/utils/format'
import type { StrategyInfo, ParamRange } from '@/types'

interface StrategyDetail {
  name: string
  displayName: string
  description: string
  principle: string
  scenario: string
  risk: string
  difficulty: string
  category: string
  paramCount: number
  params: { name: string; label: string; desc: string; min: number; max: number; step: number }[]
}

const activeCategory = ref('all')
const selectedStrategy = ref<StrategyDetail | null>(null)
const rawStrategies = ref<Record<string, StrategyInfo>>({})

const categories = [
  { key: 'all', label: '全部', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>' },
  { key: 'trend', label: '趋势跟踪', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 3v18h18"/><path d="M7 16l4-8 4 4 6-10"/></svg>' },
  { key: 'reversal', label: '均值回归', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 12h4l3-9 4 18 3-9h4"/></svg>' },
  { key: 'breakout', label: '突破策略', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>' },
  { key: 'advanced', label: '高级策略', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/></svg>' },
  { key: 'classic', label: '经典策略', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87L18.18 22 12 18.27 5.82 22 7 14.14l-5-4.87 6.91-1.01L12 2z"/></svg>' },
]

const strategyDetails: Record<string, Omit<StrategyDetail, 'name' | 'paramCount' | 'params'>> = {
  DualMAStrategy: {
    displayName: '双均线策略',
    description: '利用短期均线和长期均线的交叉来判断趋势方向。当短期均线上穿长期均线时产生买入信号（金叉），下穿时产生卖出信号（死叉）。这是最经典、最易懂的趋势跟踪策略之一。',
    principle: '移动平均线（MA）是将一段时间内的收盘价取平均值连成的线。短期均线反应灵敏，长期均线反应迟缓。当短期均线从下方穿越长期均线时，说明短期价格动能增强，趋势可能向上；反之则趋势可能向下。核心逻辑是"顺势而为"——在趋势确立后跟随，在趋势结束前退出。',
    scenario: '适合有明显趋势的行情（单边上涨或下跌），在震荡市中容易产生频繁的假信号（来回打脸）。建议在日线级别以上周期使用，配合成交量确认效果更好。',
    risk: '最大的风险是"均线滞后"——当均线发出信号时，价格往往已经走了一段，可能买在高位、卖在低位。在横盘震荡行情中，均线反复交叉会产生大量亏损交易。建议配合趋势强度指标（如ADX）过滤弱趋势。',
    difficulty: 'beginner',
    category: 'trend',
  },
  MACDStrategy: {
    displayName: 'MACD策略',
    description: '基于MACD指标（移动平均收敛/发散）的交易策略。通过DIF线和DEA线的交叉、零轴位置以及柱状图的变化来判断买卖时机。MACD是技术分析中使用最广泛的指标之一。',
    principle: 'MACD由三部分组成：DIF线（快线，短期EMA与长期EMA的差值）、DEA线（慢线，DIF的EMA）、MACD柱（DIF与DEA的差值）。当DIF上穿DEA且在零轴上方时为强势买入信号；DIF下穿DEA且在零轴下方时为强势卖出信号。柱状图由绿转红代表多头力量增强，由红转绿代表空头力量增强。',
    scenario: '适合中长线趋势行情，尤其在趋势启动初期信号较为可靠。在窄幅震荡市中MACD信号频繁且不可靠。建议在周线或日线级别使用，配合支撑阻力位分析。',
    risk: 'MACD是滞后指标，信号出现时趋势可能已经走了一半以上。在震荡行情中容易频繁发出假信号。零轴附近的交叉信号可靠性较低。建议等待MACD柱状图确认后再入场，避免在信号初期就全仓操作。',
    difficulty: 'beginner',
    category: 'trend',
  },
  KDJStrategy: {
    displayName: 'KDJ策略',
    description: '基于KDJ随机指标的交易策略。KDJ指标通过计算一段时间内收盘价在最高价和最低价之间的位置来判断超买超卖状态，适合捕捉短线的转折点。',
    principle: 'KDJ指标由K线、D线和J线组成。K值和D值在0-100之间波动，J值可以超出这个范围。当K线上穿D线且处于超卖区（K<20）时为买入信号；当K线下穿D线且处于超买区（K>80）时为卖出信号。J值反应最灵敏，常用于提前预判拐点。',
    scenario: '适合短线交易和震荡行情中的高抛低吸。在趋势行情中KDJ容易在超买/超卖区持续停留，导致过早反向操作。建议在1小时或日线级别使用，配合趋势指标过滤。',
    risk: 'KDJ在强趋势行情中会"钝化"——持续停留在超买或超卖区，此时按照KDJ信号反向操作会造成严重亏损。J值过于灵敏，容易产生虚假信号。建议在趋势明确时不要逆KDJ信号操作，只在震荡行情中使用。',
    difficulty: 'beginner',
    category: 'reversal',
  },
  BollingerBreakoutStrategy: {
    displayName: '布林带突破策略',
    description: '利用布林带（Bollinger Bands）的收缩和扩张来判断价格突破方向。当布林带收窄后价格突破上轨为买入信号，突破下轨为卖出信号。布林带是衡量市场波动率的经典工具。',
    principle: '布林带由中轨（20日均线）和上下轨（中轨±2倍标准差）组成。当市场波动率降低时，布林带收窄（挤压），预示着即将出现大幅波动；当价格突破收窄后的上轨，说明多头力量爆发，可能开启上涨趋势。反之，突破下轨则可能开启下跌趋势。',
    scenario: '适合在市场长时间横盘整理后捕捉突破行情。布林带收窄得越久，突破后的行情往往越大。不适合在已经处于明显趋势中的行情使用，因为此时布林带已经扩张，突破信号不可靠。',
    risk: '假突破是最大的风险——价格短暂突破布林带后又回到带内，导致追涨杀跌。建议等待收盘价确认突破，并配合成交量放大来确认突破的有效性。可以设置布林带中轨作为止损参考。',
    difficulty: 'intermediate',
    category: 'breakout',
  },
  MomentumStrategy: {
    displayName: '动量策略',
    description: '基于价格动量的交易策略。动量衡量的是价格变化的速度和幅度，当动量为正且加速时买入，动量衰减时卖出。核心思想是"强者恒强，弱者恒弱"。',
    principle: '动量 = 当前价格 / N周期前价格 - 1。当动量大于0且持续上升时，说明价格上涨速度在加快，趋势在加强；当动量开始下降时，即使价格还在上涨，也说明上涨动力在减弱，可能即将反转。策略还会计算动量加速度（动量的变化率）来提前预判趋势转折。',
    scenario: '适合趋势初期和中期，在趋势加速阶段表现最好。在震荡行情中动量频繁正负切换，容易产生假信号。建议配合趋势方向过滤，只在趋势方向一致时使用动量信号。',
    risk: '动量策略在趋势末期容易"接最后一棒"——动量最高时往往就是趋势即将反转的时候。动量翻转信号滞后，可能错过最佳出场时机。建议设置严格的止损，并在动量开始衰减（而非完全翻转）时就开始减仓。',
    difficulty: 'intermediate',
    category: 'trend',
  },
  RSIMeanReversionStrategy: {
    displayName: 'RSI均值回归策略',
    description: '利用RSI（相对强弱指标）的超买超卖特性进行反向交易。当RSI进入超卖区后回升时买入，进入超买区后回落时卖出。核心思想是"物极必反"——极端的价格运动终将回归均值。',
    principle: 'RSI衡量一段时间内上涨幅度占总幅度的比例，范围0-100。RSI<30为超卖（跌过头了），RSI>70为超买（涨过头了）。策略在RSI从超卖区回升至30以上时买入（认为下跌过度将反弹），在RSI从超买区回落至70以下时卖出（认为上涨过度将回调）。',
    scenario: '适合震荡行情和区间交易，在支撑阻力位附近效果最好。在强趋势行情中RSI会持续停留在超买/超卖区，此时逆势操作会严重亏损。建议只在明确震荡区间内使用，配合支撑阻力位确认。',
    risk: '最大的风险是逆趋势操作——在强势上涨中RSI可能长期超买，此时卖出会踏空；在暴跌中RSI可能长期超卖，此时买入会深套。建议只在更大级别趋势方向一致时使用RSI信号，例如在上涨趋势中只做RSI超卖买入，不做超买卖出。',
    difficulty: 'intermediate',
    category: 'reversal',
  },
  SuperTrendStrategy: {
    displayName: '超级趋势策略',
    description: '基于ATR（平均真实波幅）的趋势跟踪策略。SuperTrend指标通过ATR动态调整支撑/阻力线，当价格突破该线时产生交易信号。简单直观，适合趋势跟踪。',
    principle: 'SuperTrend = (最高价+最低价)/2 ± N×ATR。当价格在SuperTrend线上方时为多头状态（绿色线），价格跌破该线时翻转为空头状态（红色线）。ATR使得支撑/阻力线随波动率自动调整——波动大时线远离价格，波动小时线靠近价格。',
    scenario: '适合中长线趋势跟踪，在波动率适中的行情中表现最好。在剧烈波动的行情中SuperTrend线会频繁翻转，产生大量假信号。建议在日线或周线级别使用。',
    risk: '在震荡行情中SuperTrend会频繁翻转，导致连续亏损。ATR参数设置不当会导致信号过于灵敏或过于迟钝。建议配合ADX等趋势强度指标，只在趋势明确时使用SuperTrend信号。',
    difficulty: 'beginner',
    category: 'trend',
  },
  IchimokuCloudStrategy: {
    displayName: '一目均衡策略',
    description: '源自日本的一套完整技术分析体系，通过转换线、基准线、云带和延迟线的综合判断来识别趋势方向、支撑阻力和买卖时机。"一目"意为"一眼看清"。',
    principle: '一目均衡图由5条线组成：转换线（9日最高最低中值）、基准线（26日最高最低中值）、先行带A（转换线与基准线的中值前移26日）、先行带B（52日最高最低中值前移26日）、延迟线（收盘价后移26日）。云带由先行带A和B围成。价格在云上方为多头市场，在云下方为空头市场，云本身构成支撑阻力。',
    scenario: '适合中长线趋势判断，云带的支撑阻力作用在日线和周线级别非常可靠。不适合短线交易，因为信号滞后较大。建议结合转换线和基准线的交叉作为入场确认。',
    risk: '一目均衡图参数固定（9/26/52），可能不适用于所有品种和周期。云带的滞后性使得信号出现较晚。在震荡行情中价格在云内来回穿越，信号不明确。建议不要单独使用，结合其他指标确认。',
    difficulty: 'advanced',
    category: 'trend',
  },
  TurtleTradingStrategy: {
    displayName: '海龟交易策略',
    description: '源自著名的"海龟交易实验"，由理查德·丹尼斯创立。核心是"突破入场+趋势跟踪+严格风控"，是趋势跟踪策略的教科书级实现。',
    principle: '当价格突破N日最高价时买入（突破入场），跌破N日最低价时卖出。仓位根据ATR计算（波动大时小仓位，波动小时大仓位），每次交易风险控制在账户的1-2%。盈利后加仓（金字塔加仓法），止损设在突破点下方2ATR处。这就是"截断亏损，让利润奔跑"的经典实现。',
    scenario: '适合流动性好、趋势性强的市场（如商品期货、外汇）。需要较大的资金量来承受连续亏损（可能连续亏损10次以上才抓住一次大趋势）。在震荡市中会持续亏损，但一次大趋势的盈利可以覆盖多次小亏损。',
    risk: '胜率极低（通常只有30-40%），需要极强的心理素质来承受连续亏损。回撤可能非常大（30-50%）。需要严格的资金管理和纪律执行。不适合心态不稳定的交易者。建议先用小资金模拟练习，确认能严格执行规则后再加大资金。',
    difficulty: 'intermediate',
    category: 'classic',
  },
  DualThrustStrategy: {
    displayName: 'Dual Thrust策略',
    description: '由Michael Chalek开发的经典日内突破策略，曾被评为最赚钱的日内策略之一。通过前N日的价格范围计算上下轨，突破上轨买入，突破下轨卖出。',
    principle: '计算前N日的HH（最高价的最大值）、HC（收盘价的最大值）、LC（收盘价的最小值）、LL（最低价的最小值）。Range = max(HH-LC, HC-LL)。上轨 = 开盘价 + K1×Range，下轨 = 开盘价 - K2×Range。K1和K2的取值决定了策略偏向做多还是做空。当K1<K2时，做多更容易触发，策略偏多；反之偏空。',
    scenario: '适合日内交易，在开盘后波动较大的品种上表现最好。需要选择流动性好、波动适中的品种。不适合低波动或长期横盘的品种。建议在期货市场使用，A股T+1制度限制了日内策略的效果。',
    risk: '日内策略对滑点和手续费非常敏感，实际交易成本可能显著降低收益。开盘跳空可能导致入场价格远偏离理论价格。参数K1、K2的选择对结果影响很大，过度优化可能导致过拟合。建议在模拟盘充分测试后再实盘。',
    difficulty: 'advanced',
    category: 'classic',
  },
  MeanReversionProStrategy: {
    displayName: '均值回归Pro策略',
    description: '进阶版均值回归策略，使用Z-score（标准分）来衡量价格偏离均值的程度。当Z-score超过阈值时认为价格过度偏离，大概率将回归均值。',
    principle: 'Z-score = (当前价格 - N日均值) / N日标准差。Z-score衡量当前价格偏离均值多少个标准差。当Z-score > 入场阈值（如2.0）时，认为价格过高，卖出做空；当Z-score < -入场阈值时，认为价格过低，买入做多。当Z-score回归到0附近时平仓。Pro版本增加了波动率过滤和趋势过滤，避免在强趋势中逆势操作。',
    scenario: '适合震荡行情和均值回归特征明显的品种（如配对交易、价差交易）。在强趋势行情中会持续亏损，因为价格可以长期偏离均值。建议只在统计检验确认均值回归特性的品种上使用。',
    risk: '"均值回归"不等于"必然回归"——价格可能长期偏离均值甚至更远（即"这次不一样"）。在结构性变化（如公司基本面改变）时，历史均值不再有效。建议设置严格止损，不要在亏损时加仓摊平。',
    difficulty: 'advanced',
    category: 'reversal',
  },
  VolatilitySqueezeBreakoutStrategy: {
    displayName: '波动率收缩突破策略',
    description: '结合布林带和肯特纳通道（Keltner Channel）来识别波动率收缩（挤压）状态，在波动率扩张时捕捉突破方向。当布林带收窄到肯特纳通道内部时为"挤压"状态。',
    principle: '布林带基于标准差，肯特纳通道基于ATR。当布林带收窄到肯特纳通道内部时，说明市场波动率极低，处于"蓄势"状态。当布林带重新扩张到肯特纳通道外部时，"挤压"释放，价格大概率将出现方向性突破。突破方向由动量指标确认。',
    scenario: '适合在市场长时间低波动后捕捉大行情。挤压时间越长，释放后的行情越大。适合日线级别使用。不适合已经处于高波动状态的品种。',
    risk: '并非所有挤压都会释放出大行情，有时只是短暂的波动后再次进入挤压。突破方向判断错误会导致亏损。建议等待挤压释放后的第一根大阳线/大阴线确认方向后再入场。',
    difficulty: 'intermediate',
    category: 'breakout',
  },
  DonchianChannelStrategy: {
    displayName: '唐奇安通道策略',
    description: '最经典的通道突破策略之一，也是海龟交易策略的原型。当价格突破N日最高价时买入，跌破N日最低价时卖出。简单直接，是趋势跟踪的入门策略。',
    principle: '唐奇安通道由上轨（N日最高价）、下轨（N日最低价）和中轨（上下轨均值）组成。价格突破上轨说明多头力量突破了近期的所有阻力，趋势可能延续；跌破下轨则相反。使用不同周期的通道（如20日入场、10日出场）可以优化效果。',
    scenario: '适合趋势性强的市场，在商品期货和外汇市场表现较好。在震荡行情中会频繁假突破。建议使用较长周期（如20日以上）来减少假信号。',
    risk: '与所有突破策略一样，假突破是主要风险。通道突破信号滞后，入场价格可能已经远离最佳位置。建议配合成交量确认突破有效性，并设置合理的止损。',
    difficulty: 'beginner',
    category: 'breakout',
  },
  ATRChannelBreakoutStrategy: {
    displayName: 'ATR通道突破策略',
    description: '以EMA为中线、ATR的倍数为带宽构建通道，价格突破通道上轨买入，跌破下轨卖出。ATR通道比布林带更关注真实波动幅度。',
    principle: '中轨 = EMA(N日)，上轨 = EMA + M×ATR，下轨 = EMA - M×ATR。ATR（平均真实波幅）衡量了包含跳空在内的真实波动大小，比标准差更贴近实际交易场景。当价格突破上轨时，说明价格已经超过了正常波动范围，可能开启新趋势。',
    scenario: '适合波动率变化较大的市场，ATR能自动适应波动率变化。在趋势行情中表现好，震荡行情中假信号多。建议配合趋势方向过滤使用。',
    risk: 'ATR通道宽度的参数M对结果影响较大，过小容易假突破，过大信号太迟。在低波动时期通道收窄，容易被正常波动触发。建议M值在1.5-3.0之间调整。',
    difficulty: 'intermediate',
    category: 'breakout',
  },
  FractalBreakoutStrategy: {
    displayName: '分形突破策略',
    description: '基于比尔·威廉姆斯的分形理论，识别价格的局部高点和低点（分形），当价格突破分形高点时买入，跌破分形低点时卖出。',
    principle: '上分形 = 中间K线的最高价高于左右各2根K线的最高价（5根K线组合）。下分形反之。分形代表了市场参与者的"犹豫点"——价格在这里遇到了阻力或支撑。当价格突破上分形，说明多头力量克服了之前的阻力，可能继续上涨。',
    scenario: '适合所有市场和时间周期，尤其在支撑阻力位明显的行情中效果好。分形突破确认了前高/前低被突破，比简单的N日高低点突破更有意义。',
    risk: '在震荡行情中会产生大量分形，频繁突破又回落。分形识别需要至少5根K线，信号有一定滞后。建议配合成交量和其他趋势指标过滤假突破。',
    difficulty: 'intermediate',
    category: 'breakout',
  },
  WyckoffAccumulationStrategy: {
    displayName: '威科夫吸筹策略',
    description: '基于理查德·威科夫的量价分析理论，识别主力资金吸筹（Accumulation）阶段。在吸筹完成后跟随主力方向操作，是机构级分析方法的简化实现。',
    principle: '威科夫吸筹模型分为4个阶段：A（下跌停止）、B（横盘吸筹）、C（假突破测试/弹簧）、D（上涨启动）、E（突破区间）。策略通过分析价格与成交量的关系来判断当前处于哪个阶段。关键信号包括：放量下跌后的缩量企稳（A阶段）、区间内量价背离（B阶段）、弹簧后快速收回（C阶段）、放量突破区间（D阶段）。',
    scenario: '适合在长期下跌后的底部区域使用，识别主力建仓完成后跟随操作。在已经处于上涨趋势中的品种上不适用。建议在周线级别识别吸筹区间，日线级别确认突破。',
    risk: '威科夫分析高度主观，不同交易者对同一走势可能判断不同。吸筹阶段可能持续数月甚至数年。"弹簧"信号可能不是弹簧而是真正的破位。建议结合基本面分析确认底部逻辑，不要仅凭量价形态就重仓入场。',
    difficulty: 'advanced',
    category: 'advanced',
  },
  GARCHVolatilityStrategy: {
    displayName: 'GARCH波动率策略',
    description: '使用GARCH（广义自回归条件异方差）模型预测未来波动率，在波动率飙升时减仓或对冲，在波动率回落时加仓。这是量化机构常用的风险管理策略。',
    principle: 'GARCH模型认为波动率具有"聚集性"——大波动之后往往跟着大波动，小波动之后跟着小波动。模型通过历史收益率的平方和前期波动率来预测下期波动率。当预测波动率超过阈值时，说明市场即将出现大幅波动，此时应降低仓位或购买期权对冲。',
    scenario: '适合需要精细风险管理的组合投资。在市场危机前后表现突出，能提前预警波动率上升。不适合追求高收益的投机交易。建议作为风控模块配合其他策略使用。',
    risk: 'GARCH模型假设波动率服从特定分布，实际市场可能出现"黑天鹅"事件超出模型预测范围。模型参数需要定期重新估计。建议不要完全依赖GARCH预测，结合其他风险指标（如VIX）综合判断。',
    difficulty: 'advanced',
    category: 'advanced',
  },
  AdaptiveEngine: {
    displayName: '自适应量化引擎',
    description: '系统自动根据当前市场状态（趋势/震荡/高波动/低波动）选择最合适的策略组合。无需手动选择策略，适合不想深入研究策略细节的用户。',
    principle: '引擎首先通过多种指标（ADX、ATR、波动率等）判断当前市场状态，然后从策略库中选择最适合该状态的策略。趋势市选择趋势跟踪策略，震荡市选择均值回归策略，高波动时降低仓位。引擎会持续监控市场状态变化，动态切换策略。',
    scenario: '适合所有市场环境，是"全天候"策略。特别适合不确定当前市场状态的交易者。但自适应切换本身有延迟，在快速变化的市场中可能来不及调整。',
    risk: '市场状态判断错误会导致选择不合适的策略。策略切换本身有成本（可能需要平仓再开仓）。建议在回测中验证引擎的状态判断准确率，并设置切换冷却期避免频繁切换。',
    difficulty: 'beginner',
    category: 'advanced',
  },
}

const allStrategies = computed<StrategyDetail[]>(() => {
  const result: StrategyDetail[] = []
  for (const [name, info] of Object.entries(rawStrategies.value)) {
    const detail = strategyDetails[name]
    if (!detail) continue
    const params = Object.entries(info.param_space || {}).map(([pName, range]) => ({
      name: pName,
      label: paramLabel(pName),
      desc: paramDesc(pName),
      min: range.min,
      max: range.max,
      step: range.step,
    }))
    result.push({
      name,
      ...detail,
      paramCount: params.length,
      params,
    })
  }
  return result
})

const filteredStrategies = computed(() => {
  if (activeCategory.value === 'all') return allStrategies.value
  return allStrategies.value.filter(s => s.category === activeCategory.value)
})

function difficultyLabel(d: string) {
  const map: Record<string, string> = { beginner: '入门', intermediate: '进阶', advanced: '高级' }
  return map[d] || d
}

function paramLabel(name: string) {
  const map: Record<string, string> = {
    period: '周期', accel_period: '加速周期', window: '窗口期',
    entry_z: '入场Z值', bb_period: '布林带周期', kc_mult: '肯特纳倍数',
    tenkan_period: '转换线周期', kijun_period: '基准线周期',
    vwap_window: 'VWAP窗口', sigma_mult: '标准差倍数',
    ofi_window: 'OFI窗口', lookback: '回溯期',
    min_bars: '最小K线数', illiq_window: '非流动性窗口',
    corr_window: '相关性窗口', entry_window: '入场窗口',
    exit_window: '出场窗口', k1: '上轨系数K1', k2: '下轨系数K2',
    ema_period: 'EMA周期', atr_mult: 'ATR倍数',
    upper_period: '上轨周期', lower_period: '下轨周期',
    atr_period: 'ATR周期', atr_mult_first: 'ATR首层倍数',
    vol_ma_window: '量均窗口', entry_sigma: '入场标准差',
    er_period: '效率比周期', er_threshold: '效率比阈值',
    vol_lookback: '波动率回溯', vol_surge_threshold: '波动率飙升阈值',
    short_period: '短周期', mid_period: '中周期',
  }
  return map[name] || name
}

function paramDesc(name: string) {
  const map: Record<string, string> = {
    period: '计算动量的回溯周期，周期越短信号越灵敏但噪音越大',
    accel_period: '计算动量加速度的周期，用于提前预判趋势转折',
    window: '统计计算的窗口期，影响均线和标准差的灵敏度',
    entry_z: 'Z-score入场阈值，值越大信号越少但越可靠',
    lookback: '回溯多少根K线来识别分形或计算指标',
    entry_window: '突破入场的回溯周期',
    exit_window: '突破出场的回溯周期',
    k1: '上轨系数，值越小越容易触发做多信号',
    k2: '下轨系数，值越小越容易触发做空信号',
    atr_mult: 'ATR的倍数，决定通道宽度',
    ema_period: 'EMA指数移动平均线的周期',
  }
  return map[name] || '调整该参数会影响策略的灵敏度和信号频率'
}

onMounted(async () => {
  try {
    rawStrategies.value = await api.backtest.strategies()
  } catch {
    // silent
  }
})
</script>

<style scoped>
.strategy-intro-page {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: var(--space-6);
}

.page-title {
  font-size: var(--text-2xl);
  font-weight: 600;
  margin-bottom: var(--space-2);
}

.page-desc {
  color: var(--text-secondary);
  font-size: var(--text-md);
}

.category-tabs {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-6);
  flex-wrap: wrap;
}

.cat-btn {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--duration-fast);
  font-family: var(--font-sans);
}

.cat-btn.active {
  background: var(--accent-muted);
  border-color: var(--border-accent);
  color: var(--accent);
}

.cat-btn:hover:not(.active) {
  border-color: var(--border-hover);
  color: var(--text-primary);
}

.cat-icon {
  display: flex;
  align-items: center;
}

.strategy-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: var(--space-4);
}

.strategy-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}

.strategy-card:hover {
  border-color: var(--border-hover);
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.sc-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
}

.sc-name {
  font-size: var(--text-md);
  font-weight: 500;
}

.sc-difficulty {
  font-size: var(--text-xs);
  padding: 2px 8px;
  border-radius: 10px;
}

.sc-difficulty.beginner {
  background: rgba(34, 197, 94, 0.1);
  color: var(--fall);
}

.sc-difficulty.intermediate {
  background: rgba(245, 158, 11, 0.1);
  color: var(--warn);
}

.sc-difficulty.advanced {
  background: rgba(239, 68, 68, 0.1);
  color: var(--rise);
}

.sc-desc {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: var(--leading-normal);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-bottom: var(--space-3);
}

.sc-tags {
  display: flex;
  gap: var(--space-2);
}

.sc-tag {
  font-size: 10px;
  padding: 1px 6px;
  background: var(--bg-elevated);
  border-radius: 3px;
  color: var(--text-tertiary);
}

.sc-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sc-backtest-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 12px;
  background: var(--accent);
  color: white;
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  font-weight: 500;
  text-decoration: none;
  transition: background var(--duration-fast);
  white-space: nowrap;
}

.sc-backtest-btn:hover {
  background: var(--accent-hover);
}

.detail-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(4px);
}

.detail-modal {
  width: 680px;
  max-height: 85vh;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow-y: auto;
  position: relative;
  animation: slideUp var(--duration-normal) var(--ease-out);
}

.close-btn {
  position: absolute;
  top: var(--space-3);
  right: var(--space-3);
  background: none;
  border: none;
  color: var(--text-tertiary);
  font-size: var(--text-lg);
  cursor: pointer;
  z-index: 1;
  padding: var(--space-1);
}

.close-btn:hover {
  color: var(--text-primary);
}

.detail-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-5) var(--space-6);
  border-bottom: 1px solid var(--border);
}

.detail-name {
  font-size: var(--text-xl);
  font-weight: 600;
}

.detail-difficulty {
  font-size: var(--text-xs);
  padding: 2px 8px;
  border-radius: 10px;
}

.detail-difficulty.beginner {
  background: rgba(34, 197, 94, 0.1);
  color: var(--fall);
}

.detail-difficulty.intermediate {
  background: rgba(245, 158, 11, 0.1);
  color: var(--warn);
}

.detail-difficulty.advanced {
  background: rgba(239, 68, 68, 0.1);
  color: var(--rise);
}

.detail-body {
  padding: var(--space-5) var(--space-6);
}

.detail-section {
  margin-bottom: var(--space-5);
}

.detail-section h3 {
  font-size: var(--text-md);
  font-weight: 500;
  margin-bottom: var(--space-2);
  padding-left: var(--space-3);
  border-left: 3px solid var(--accent);
  line-height: 1.4;
}

.detail-section p {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.7;
}

.param-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.param-item {
  background: var(--bg-elevated);
  padding: var(--space-3);
  border-radius: var(--radius-sm);
}

.param-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.param-name {
  font-size: var(--text-sm);
  font-weight: 500;
}

.param-range {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.param-desc {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  line-height: 1.5;
}

.detail-actions {
  padding-top: var(--space-4);
  border-top: 1px solid var(--border);
}

.run-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-5);
  background: var(--accent);
  color: white;
  border-radius: var(--radius-sm);
  font-size: var(--text-md);
  font-weight: 500;
  transition: background var(--duration-fast);
  text-decoration: none;
}

.run-btn:hover {
  background: var(--accent-hover);
}
</style>
