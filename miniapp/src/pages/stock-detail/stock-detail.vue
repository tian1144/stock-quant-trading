<template>
  <view class="container">
    <!-- 头部：股票信息 -->
    <view class="header">
      <view class="header-top">
        <text class="stock-name">{{ stockName }}</text>
        <text class="stock-code">{{ code }}</text>
      </view>
      <view class="price-row">
        <text class="current-price" :class="priceClass">{{ formatPrice(realtime.price) }}</text>
        <view class="change-info">
          <text class="change-value" :class="priceClass">{{ formatChange(realtime.pct_change) }}</text>
          <text class="change-amount" :class="priceClass">{{ formatChangeAmount(realtime.change) }}</text>
        </view>
      </view>
      <view class="metrics-row">
        <view class="metric">
          <text class="metric-label">成交量</text>
          <text class="metric-value">{{ formatVolume(realtime.volume) }}</text>
        </view>
        <view class="metric">
          <text class="metric-label">成交额</text>
          <text class="metric-value">{{ formatAmount(realtime.amount) }}</text>
        </view>
        <view class="metric">
          <text class="metric-label">换手率</text>
          <text class="metric-value">{{ realtime.turnover_rate || '--' }}%</text>
        </view>
        <view class="metric">
          <text class="metric-label">量比</text>
          <text class="metric-value">{{ realtime.volume_ratio || '--' }}</text>
        </view>
      </view>
    </view>

    <!-- Tab栏 -->
    <view class="tab-bar">
      <view
        class="tab-item"
        v-for="tab in tabs"
        :key="tab.key"
        :class="{ active: activeTab === tab.key }"
        @click="switchTab(tab.key)"
      >
        <text>{{ tab.label }}</text>
      </view>
    </view>

    <!-- 图表区域 -->
    <view class="chart-area">
      <!-- 分时图 -->
      <view v-show="activeTab === 'minute'">
        <view class="chart-loading" v-if="loading.minute"><text>分时数据加载中...</text></view>
        <view class="chart-empty" v-else-if="minuteEmpty" @click="retryActiveTab"><text>暂无分时数据，点击重试</text></view>
        <stock-chart v-else chart-id="minute-chart" :option="minuteOption" :height="500" />
      </view>

      <!-- K线图 -->
      <view v-show="activeTab === 'kline'">
        <view class="period-bar">
          <view
            class="period-btn"
            v-for="p in periods"
            :key="p.value"
            :class="{ active: activePeriod === p.value }"
            @click="switchPeriod(p.value)"
          >
            <text>{{ p.label }}</text>
          </view>
        </view>
        <view class="chart-loading" v-if="loading.kline"><text>K线数据加载中...</text></view>
        <view class="chart-empty" v-else-if="klineEmpty" @click="retryActiveTab"><text>暂无K线数据，点击重试</text></view>
        <stock-chart v-else chart-id="kline-chart" :option="klineOption" :height="500" />
      </view>

      <!-- 筹码分布 -->
      <view v-show="activeTab === 'chip'">
        <view class="chart-loading" v-if="loading.chip"><text>筹码数据加载中...</text></view>
        <view class="chart-empty" v-else-if="chipEmpty" @click="retryActiveTab"><text>暂无筹码数据，点击重试</text></view>
        <stock-chart v-else chart-id="chip-chart" :option="chipOption" :height="500" />
      </view>

      <!-- 资金流向 -->
      <view v-show="activeTab === 'money'">
        <view class="flow-summary" v-if="moneyFlow">
          <view class="flow-item">
            <text class="flow-label">主力净流入</text>
            <text class="flow-value" :class="moneyFlow.main_net_inflow >= 0 ? 'price-up' : 'price-down'">
              {{ formatFlowAmount(moneyFlow.main_net_inflow) }}
            </text>
          </view>
          <view class="flow-item">
            <text class="flow-label">超大单</text>
            <text class="flow-value" :class="moneyFlow.super_large_net_inflow >= 0 ? 'price-up' : 'price-down'">
              {{ formatFlowAmount(moneyFlow.super_large_net_inflow) }}
            </text>
          </view>
          <view class="flow-item">
            <text class="flow-label">大单</text>
            <text class="flow-value" :class="moneyFlow.large_net_inflow >= 0 ? 'price-up' : 'price-down'">
              {{ formatFlowAmount(moneyFlow.large_net_inflow) }}
            </text>
          </view>
          <view class="flow-item">
            <text class="flow-label">中单</text>
            <text class="flow-value" :class="moneyFlow.medium_net_inflow >= 0 ? 'price-up' : 'price-down'">
              {{ formatFlowAmount(moneyFlow.medium_net_inflow) }}
            </text>
          </view>
          <view class="flow-item">
            <text class="flow-label">小单</text>
            <text class="flow-value" :class="moneyFlow.small_net_inflow >= 0 ? 'price-up' : 'price-down'">
              {{ formatFlowAmount(moneyFlow.small_net_inflow) }}
            </text>
          </view>
        </view>
        <stock-chart chart-id="money-chart" :option="moneyOption" :height="400" />
      </view>

      <!-- 资讯 -->
      <view v-show="activeTab === 'news'" class="news-list">
        <view v-if="stockNews.length === 0" class="empty">
          <text>暂无相关新闻</text>
        </view>
        <view class="news-item" v-for="item in stockNews" :key="item.id">
          <text class="news-time">{{ item.time }}</text>
          <text class="news-title">{{ item.title }}</text>
        </view>
      </view>
    </view>

    <!-- 技术指标摘要 -->
    <view class="tech-summary" v-if="technical && activeTab !== 'news'">
      <view class="tech-row">
        <text class="tech-label">MA5</text>
        <text class="tech-value">{{ technical.ma5 }}</text>
        <text class="tech-label">MA10</text>
        <text class="tech-value">{{ technical.ma10 }}</text>
        <text class="tech-label">MA20</text>
        <text class="tech-value">{{ technical.ma20 }}</text>
      </view>
      <view class="tech-row">
        <text class="tech-label">MACD</text>
        <text class="tech-value" :class="technical.dif > technical.dea ? 'price-up' : 'price-down'">
          {{ technical.dif }}/{{ technical.dea }}
        </text>
        <text class="tech-label">RSI</text>
        <text class="tech-value">{{ technical.rsi_6 }}</text>
        <text class="tech-label">KDJ-J</text>
        <text class="tech-value">{{ technical.kdj_j }}</text>
      </view>
    </view>

    <!-- AI量化评分卡 -->
    <view class="quant-panel">
      <view class="panel-header">
        <text class="panel-title">AI量化评分</text>
        <text class="panel-subtitle">score_card.json</text>
      </view>
      <view class="score-head">
        <view class="score-ring" :class="scoreLevelClass">
          <text class="score-num">{{ scoreCard.final_score || '--' }}</text>
          <text class="score-label">{{ decisionLabel(scoreCard.decision) }}</text>
        </view>
        <view class="score-meta">
          <text>置信度 {{ formatConfidence(scoreCard.confidence) }}</text>
          <text>{{ scoreCard.need_human_confirm ? '需要人工确认' : '可进入执行前检查' }}</text>
          <text v-if="scoreCard.risk_pause" class="danger-text">S级事件暂停交易</text>
        </view>
      </view>
      <view class="score-grid" v-if="scoreCard.scores">
        <view class="score-cell" v-for="item in scoreItems" :key="item.key">
          <text class="cell-label">{{ item.label }}</text>
          <text class="cell-value" :class="item.key === 'risk_deduction' ? 'price-down' : 'price-up'">
            {{ scoreCard.scores[item.key] }}
          </text>
        </view>
      </view>
      <view class="empty-lite" v-else>
        <text>评分加载中...</text>
      </view>
    </view>

    <!-- 结构化交易建议 -->
    <view class="quant-panel">
      <view class="panel-header">
        <text class="panel-title">结构化交易建议</text>
        <text class="panel-subtitle">decision.json</text>
      </view>
      <view class="decision-row">
        <text class="decision-tag" :class="'direction-' + (decision.direction || 'wait')">
          {{ directionText(decision.direction) }}
        </text>
        <text class="market-state">{{ marketStateText(decision.market_state) }}</text>
      </view>
      <view class="rule-list">
        <view class="rule-item">
          <text class="rule-label">入场条件</text>
          <text class="rule-value">{{ decision.entry_condition || '等待评分、资金和技术结构确认' }}</text>
        </view>
        <view class="rule-item">
          <text class="rule-label">失效条件</text>
          <text class="rule-value">{{ decision.invalid_condition || '暂无' }}</text>
        </view>
        <view class="rule-item">
          <text class="rule-label">止损/止盈</text>
          <text class="rule-value">{{ formatPrice(decision.stop_loss) }} / {{ formatPrice(decision.take_profit) }}</text>
        </view>
        <view class="rule-item">
          <text class="rule-label">仓位建议</text>
          <text class="rule-value">{{ decision.position_suggestion || '不建议交易' }}</text>
        </view>
      </view>
      <view class="reason-tags" v-if="decision.reason_summary && decision.reason_summary.length">
        <text class="reason-tag" v-for="item in decision.reason_summary" :key="item">{{ item }}</text>
      </view>
      <view class="conflict-box" v-if="decision.conflict_signals && decision.conflict_signals.length">
        <text class="conflict-title">冲突信号</text>
        <text class="conflict-item" v-for="item in decision.conflict_signals" :key="item">{{ item }}</text>
      </view>
    </view>

    <!-- 风控复核 -->
    <view class="quant-panel risk-panel">
      <view class="panel-header">
        <text class="panel-title">风控复核</text>
        <text class="panel-subtitle">risk_report.json</text>
      </view>
      <view class="risk-verdict" :class="riskReport.approved ? 'approved' : 'rejected'">
        <text>{{ riskReport.approved ? '通过风控' : '暂不执行' }}</text>
        <text>{{ riskLevelText(riskReport.risk_level) }}</text>
      </view>
      <view class="rule-list">
        <view class="rule-item">
          <text class="rule-label">仓位上限</text>
          <text class="rule-value">{{ riskReport.position_limit || '0%' }}</text>
        </view>
        <view class="rule-item" v-if="riskReport.veto_reason">
          <text class="rule-label">否决原因</text>
          <text class="rule-value danger-text">{{ riskReport.veto_reason }}</text>
        </view>
      </view>
      <view class="reason-tags" v-if="riskReport.required_checks && riskReport.required_checks.length">
        <text class="reason-tag warn" v-for="item in riskReport.required_checks" :key="item">{{ item }}</text>
      </view>
    </view>

    <!-- 底部操作栏 -->
    <view class="action-bar">
      <view class="buy-btn" @click="onBuy">
        <text>买入</text>
      </view>
      <view class="sell-btn" @click="onSell">
        <text>卖出</text>
      </view>
    </view>
  </view>
</template>

<script>
import StockChart from '@/components/stock-chart.vue'
import {
  getStockDetail,
  getStockMinutes,
  getStockKline,
  getStockChips,
  buyStock,
  sellStock,
  getScoreCard,
  getDecision,
  runRiskReview
} from '@/utils/api.js'
import { buildMinuteChartOption, buildKlineChartOption, buildChipChartOption, buildMoneyFlowChartOption } from '@/utils/chart-options.js'

export default {
  components: { StockChart },
  data() {
    return {
      code: '',
      stockName: '',
      realtime: {},
      moneyFlow: null,
      technical: {},
      stockNews: [],
      activeTab: 'minute',
      activePeriod: 101,
      minuteOption: {},
      klineOption: {},
      chipOption: {},
      moneyOption: {},
      tabs: [
        { key: 'minute', label: '分时' },
        { key: 'kline', label: 'K线' },
        { key: 'chip', label: '筹码' },
        { key: 'money', label: '资金' },
        { key: 'news', label: '资讯' },
      ],
      periods: [
        { value: 1, label: '1分' },
        { value: 5, label: '5分' },
        { value: 15, label: '15分' },
        { value: 30, label: '30分' },
        { value: 60, label: '60分' },
        { value: 101, label: '日K' },
        { value: 102, label: '周K' },
      ],
      loadedTabs: {},
      loading: {
        minute: false,
        kline: false,
        chip: false,
      },
      minuteEmpty: false,
      klineEmpty: false,
      chipEmpty: false,
      scoreCard: {},
      decision: {},
      riskReport: {},
      scoreItems: [
        { key: 'event_score', label: '事件' },
        { key: 'sentiment_score', label: '情绪' },
        { key: 'kline_score', label: 'K线' },
        { key: 'technical_score', label: '技术' },
        { key: 'fund_flow_score', label: '资金' },
        { key: 'backtest_score', label: '回测' },
        { key: 'risk_deduction', label: '风险扣分' },
      ],
    }
  },

  computed: {
    priceClass() {
      const pct = this.realtime.pct_change || 0
      if (pct > 0) return 'price-up'
      if (pct < 0) return 'price-down'
      return 'price-flat'
    },
    scoreLevelClass() {
      const score = Number(this.scoreCard.final_score || 0)
      if (score >= 80) return 'score-strong'
      if (score >= 70) return 'score-good'
      if (score >= 60) return 'score-watch'
      return 'score-avoid'
    }
  },

  onLoad(options) {
    this.code = options.code || '600519'
    this.loadDetail()
    this.loadMinuteData()
    this.loadQuantAnalysis()
  },

  methods: {
    async loadDetail() {
      try {
        const res = await getStockDetail(this.code)
        if (res) {
          this.stockName = res.name || ''
          this.realtime = res.realtime || {}
          this.moneyFlow = res.money_flow || null
          this.technical = res.technical || {}
          this.stockNews = res.news || []
        }
      } catch (e) {
        console.error('加载详情失败:', e)
      }
    },

    async loadQuantAnalysis() {
      try {
        const [score, decision, risk] = await Promise.all([
          getScoreCard(this.code, 'short'),
          getDecision(this.code, 'short'),
          runRiskReview(this.code, 'short')
        ])
        this.scoreCard = score || {}
        this.decision = decision || {}
        this.riskReport = (risk && risk.risk_report) || {}
      } catch (e) {
        console.error('加载量化分析失败:', e)
      }
    },

    async loadMinuteData() {
      if (this.loadedTabs.minute) return
      this.loading.minute = true
      this.minuteEmpty = false
      try {
        const res = await getStockMinutes(this.code)
        const minutes = res && res.minutes ? res.minutes : []
        if (minutes.length) {
          this.minuteOption = buildMinuteChartOption(minutes)
          this.loadedTabs.minute = true
        } else {
          this.minuteEmpty = true
        }
      } catch (e) {
        this.minuteEmpty = true
        console.error('加载分时数据失败:', e)
      } finally {
        this.loading.minute = false
      }
    },

    async loadKlineData() {
      const cacheKey = 'kline_' + this.activePeriod
      if (this.loadedTabs[cacheKey]) return
      this.loading.kline = true
      this.klineEmpty = false
      try {
        const res = await getStockKline(this.code, this.activePeriod, 120)
        const klines = res && res.klines ? res.klines : []
        if (klines.length) {
          this.klineOption = buildKlineChartOption(klines)
          this.loadedTabs[cacheKey] = true
        } else {
          this.klineEmpty = true
        }
      } catch (e) {
        this.klineEmpty = true
        console.error('加载K线数据失败:', e)
      } finally {
        this.loading.kline = false
      }
    },

    async loadChipData() {
      if (this.loadedTabs.chip) return
      this.loading.chip = true
      this.chipEmpty = false
      try {
        const res = await getStockChips(this.code)
        const chips = res && res.chips ? res.chips : null
        if (chips && chips.bins && chips.bins.length) {
          this.chipOption = buildChipChartOption(chips)
          this.loadedTabs.chip = true
        } else {
          this.chipEmpty = true
        }
      } catch (e) {
        this.chipEmpty = true
        console.error('加载筹码数据失败:', e)
      } finally {
        this.loading.chip = false
      }
    },

    loadMoneyData() {
      if (this.loadedTabs.money) return
      if (this.moneyFlow && this.moneyFlow.flows) {
        this.moneyOption = buildMoneyFlowChartOption(this.moneyFlow.flows)
      }
      this.loadedTabs.money = true
    },

    retryActiveTab() {
      if (this.activeTab === 'minute') {
        this.loadedTabs.minute = false
        this.loadMinuteData()
      } else if (this.activeTab === 'kline') {
        this.loadedTabs['kline_' + this.activePeriod] = false
        this.loadKlineData()
      } else if (this.activeTab === 'chip') {
        this.loadedTabs.chip = false
        this.loadChipData()
      }
    },

    switchTab(key) {
      this.activeTab = key
      if (key === 'minute') this.loadMinuteData()
      else if (key === 'kline') this.loadKlineData()
      else if (key === 'chip') this.loadChipData()
      else if (key === 'money') this.loadMoneyData()
    },

    switchPeriod(period) {
      this.activePeriod = period
      this.loadedTabs['kline_' + period] = false
      this.loadKlineData()
    },

    onBuy() {
      uni.showModal({
        title: '买入 ' + this.stockName,
        content: `当前价: ${this.realtime.price}\n请输入买入数量（100的整数倍）`,
        editable: true,
        placeholderText: '100',
        success: async (res) => {
          if (res.confirm) {
            const qty = parseInt(res.content)
            if (!qty || qty <= 0 || qty % 100 !== 0) {
              uni.showToast({ title: '请输入100的整数倍', icon: 'none' })
              return
            }
            try {
              const result = await buyStock(this.code, this.realtime.price, qty, '手动买入')
              if (result && result.order) {
                uni.showToast({ title: '买入成功', icon: 'success' })
              } else {
                uni.showToast({ title: result.error || '买入失败', icon: 'none' })
              }
            } catch (e) {
              uni.showToast({ title: '买入失败', icon: 'none' })
            }
          }
        }
      })
    },

    onSell() {
      uni.showToast({ title: '请在持仓页卖出', icon: 'none' })
    },

    formatPrice(p) { return p ? Number(p).toFixed(2) : '--' },
    formatConfidence(v) {
      if (v === null || v === undefined) return '--'
      return Math.round(Number(v) * 100) + '%'
    },
    decisionLabel(v) {
      const map = { strong_candidate: '强候选', candidate: '候选', watch: '观察', avoid: '规避' }
      return map[v] || '待评估'
    },
    directionText(v) {
      const map = { long: '做多计划', short: '减仓/规避', wait: '等待' }
      return map[v] || '等待'
    },
    marketStateText(v) {
      const map = { trend: '趋势', range: '震荡', panic: '恐慌', fomo: '过热' }
      return map[v] || '未知市场'
    },
    riskLevelText(v) {
      const map = { low: '低风险', medium: '中风险', high: '高风险' }
      return map[v] || '风险待评估'
    },
    formatChange(pct) {
      if (!pct && pct !== 0) return '--'
      return (pct > 0 ? '+' : '') + Number(pct).toFixed(2) + '%'
    },
    formatChangeAmount(v) {
      if (!v && v !== 0) return '--'
      return (v > 0 ? '+' : '') + Number(v).toFixed(2)
    },
    formatVolume(v) {
      if (!v) return '--'
      if (v >= 10000) return (v / 10000).toFixed(1) + '万手'
      return v + '手'
    },
    formatAmount(v) {
      if (!v) return '--'
      if (v >= 100000000) return (v / 100000000).toFixed(2) + '亿'
      if (v >= 10000) return (v / 10000).toFixed(0) + '万'
      return v.toFixed(0)
    },
    formatFlowAmount(v) {
      if (!v && v !== 0) return '--'
      if (Math.abs(v) >= 100000000) return (v / 100000000).toFixed(2) + '亿'
      if (Math.abs(v) >= 10000) return (v / 10000).toFixed(0) + '万'
      return v.toFixed(0)
    }
  }
}
</script>

<style scoped>
.container {
  min-height: 100vh;
  background-color: #f6f7fb;
  padding-bottom: 120rpx;
}

.header {
  padding: 20rpx;
  background: #ffffff;
  box-shadow: 0 8rpx 24rpx rgba(15, 23, 42, 0.06);
}

.header-top {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-bottom: 10rpx;
}

.stock-name {
  font-size: 36rpx;
  color: #151922;
  font-weight: bold;
}

.stock-code {
  font-size: 24rpx;
  color: #7b8494;
}

.price-row {
  display: flex;
  align-items: baseline;
  gap: 20rpx;
  margin-bottom: 16rpx;
}

.current-price {
  font-size: 52rpx;
  font-weight: bold;
}

.change-info {
  display: flex;
  gap: 16rpx;
}

.change-value, .change-amount {
  font-size: 28rpx;
}

.metrics-row {
  display: flex;
  justify-content: space-between;
}

.metric {
  text-align: center;
}

.metric-label {
  font-size: 20rpx;
  color: #7b8494;
  display: block;
}

.metric-value {
  font-size: 24rpx;
  color: #151922;
  display: block;
  margin-top: 4rpx;
}

/* Tab栏 */
.tab-bar {
  display: flex;
  background-color: #ffffff;
  border-bottom: 1rpx solid #edf0f5;
}

.tab-item {
  flex: 1;
  text-align: center;
  padding: 20rpx 0;
  font-size: 26rpx;
  color: #7b8494;
  position: relative;
}

.tab-item.active {
  color: #d71920;
}

.tab-item.active::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 30%;
  right: 30%;
  height: 4rpx;
  background-color: #d71920;
  border-radius: 2rpx;
}

/* 图表状态 */
.chart-loading, .chart-empty {
  height: 500rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #7b8494;
  font-size: 26rpx;
  background-color: #ffffff;
}

.chart-empty {
  color: #d71920;
}

/* K线周期栏 */
.period-bar {
  display: flex;
  padding: 12rpx 20rpx;
  gap: 12rpx;
  background-color: #ffffff;
  border-bottom: 1rpx solid #edf0f5;
}

.period-btn {
  padding: 8rpx 20rpx;
  border-radius: 20rpx;
  font-size: 22rpx;
  color: #7b8494;
  background-color: #f2f4f8;
}

.period-btn.active {
  color: #d71920;
  background-color: #fff0f0;
}

/* 资金流向汇总 */
.flow-summary {
  display: flex;
  flex-wrap: wrap;
  padding: 16rpx 20rpx;
  gap: 16rpx;
}

.flow-item {
  width: 30%;
  text-align: center;
}

.flow-label {
  font-size: 20rpx;
  color: #7b8494;
  display: block;
}

.flow-value {
  font-size: 24rpx;
  font-weight: bold;
  display: block;
  margin-top: 4rpx;
}

/* 新闻列表 */
.news-list {
  padding: 16rpx 20rpx;
}

.news-item {
  padding: 16rpx 0;
  border-bottom: 1rpx solid #edf0f5;
}

.news-time {
  font-size: 20rpx;
  color: #9aa3b2;
  display: block;
}

.news-title {
  font-size: 26rpx;
  color: #151922;
  display: block;
  margin-top: 6rpx;
}

.empty {
  padding: 60rpx;
  text-align: center;
  color: #9aa3b2;
}

/* 技术指标 */
.tech-summary {
  padding: 16rpx 20rpx;
  background-color: #ffffff;
  margin: 0 20rpx;
  border-radius: 12rpx;
  box-shadow: 0 8rpx 24rpx rgba(15, 23, 42, 0.05);
}

.tech-row {
  display: flex;
  justify-content: space-around;
  padding: 6rpx 0;
}

.tech-label {
  font-size: 20rpx;
  color: #7b8494;
}

.tech-value {
  font-size: 22rpx;
  color: #151922;
}

/* 量化分析 */
.quant-panel {
  margin: 20rpx;
  padding: 24rpx;
  background-color: #ffffff;
  border-radius: 12rpx;
  box-shadow: 0 8rpx 24rpx rgba(15, 23, 42, 0.05);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 18rpx;
}

.panel-title {
  font-size: 30rpx;
  color: #151922;
  font-weight: bold;
}

.panel-subtitle {
  font-size: 20rpx;
  color: #9aa3b2;
}

.score-head {
  display: flex;
  align-items: center;
  gap: 24rpx;
}

.score-ring {
  width: 144rpx;
  height: 144rpx;
  border-radius: 72rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border: 8rpx solid #d71920;
  background-color: #fff7f7;
}

.score-strong, .score-good { border-color: #d71920; background-color: #fff7f7; }
.score-watch { border-color: #f59e0b; background-color: #fff8eb; }
.score-avoid { border-color: #7b8494; background-color: #f6f7fb; }

.score-num {
  font-size: 42rpx;
  color: #d71920;
  font-weight: bold;
  line-height: 1;
}

.score-label {
  margin-top: 8rpx;
  font-size: 20rpx;
  color: #666f7f;
}

.score-meta {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8rpx;
  font-size: 24rpx;
  color: #666f7f;
}

.score-grid {
  display: flex;
  flex-wrap: wrap;
  margin-top: 20rpx;
  border-top: 1rpx solid #edf0f5;
}

.score-cell {
  width: 25%;
  padding-top: 18rpx;
}

.cell-label {
  display: block;
  color: #7b8494;
  font-size: 22rpx;
}

.cell-value {
  display: block;
  margin-top: 4rpx;
  font-size: 30rpx;
  font-weight: bold;
}

.decision-row {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin-bottom: 16rpx;
}

.decision-tag {
  padding: 10rpx 22rpx;
  border-radius: 8rpx;
  font-size: 24rpx;
  font-weight: bold;
}

.direction-long { color: #d71920; background-color: #fff0f0; }
.direction-short { color: #138a43; background-color: #eefaf2; }
.direction-wait { color: #7b8494; background-color: #f2f4f8; }

.market-state {
  color: #666f7f;
  font-size: 24rpx;
}

.rule-list {
  border-top: 1rpx solid #edf0f5;
}

.rule-item {
  display: flex;
  gap: 20rpx;
  padding: 16rpx 0;
  border-bottom: 1rpx solid #edf0f5;
}

.rule-label {
  width: 140rpx;
  color: #7b8494;
  font-size: 24rpx;
}

.rule-value {
  flex: 1;
  color: #151922;
  font-size: 24rpx;
  line-height: 1.45;
}

.reason-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
  margin-top: 16rpx;
}

.reason-tag {
  padding: 8rpx 16rpx;
  border-radius: 8rpx;
  color: #d71920;
  background-color: #fff0f0;
  font-size: 22rpx;
}

.reason-tag.warn {
  color: #b45309;
  background-color: #fff8eb;
}

.conflict-box {
  margin-top: 16rpx;
  padding: 18rpx;
  border-radius: 10rpx;
  background-color: #fff8eb;
}

.conflict-title {
  display: block;
  color: #b45309;
  font-size: 24rpx;
  font-weight: bold;
}

.conflict-item {
  display: block;
  color: #7c4a03;
  font-size: 22rpx;
  margin-top: 8rpx;
}

.risk-verdict {
  display: flex;
  justify-content: space-between;
  padding: 18rpx 20rpx;
  border-radius: 10rpx;
  margin-bottom: 12rpx;
  font-size: 26rpx;
  font-weight: bold;
}

.risk-verdict.approved {
  color: #138a43;
  background-color: #eefaf2;
}

.risk-verdict.rejected {
  color: #d71920;
  background-color: #fff0f0;
}

.danger-text {
  color: #d71920;
}

.empty-lite {
  padding: 30rpx 0;
  color: #9aa3b2;
  text-align: center;
}

/* 底部操作栏 */
.action-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  padding: 16rpx 20rpx;
  background-color: #ffffff;
  box-shadow: 0 -8rpx 24rpx rgba(15, 23, 42, 0.08);
  gap: 20rpx;
}

.buy-btn {
  flex: 1;
  padding: 24rpx 0;
  text-align: center;
  background-color: #d71920;
  border-radius: 12rpx;
  color: #fff;
  font-size: 30rpx;
  font-weight: bold;
}

.sell-btn {
  flex: 1;
  padding: 24rpx 0;
  text-align: center;
  background-color: #138a43;
  border-radius: 12rpx;
  color: #ffffff;
  font-size: 30rpx;
  font-weight: bold;
}

.action-bar {
  background-color: #ffffff;
  box-shadow: 0 -8rpx 24rpx rgba(15, 23, 42, 0.08);
}

.price-up { color: #d71920; }
.price-down { color: #138a43; }
.price-flat { color: #7b8494; }
</style>
