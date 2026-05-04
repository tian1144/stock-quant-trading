<template>
  <view class="container">
    <view class="kill-strip" :class="{ active: killSwitch.active }">
      <text>{{ killSwitch.active ? '熔断中：交易执行暂停' : '交易执行正常' }}</text>
      <text v-if="killSwitch.active">{{ killSwitch.reason }}</text>
    </view>

    <!-- 资产概览 -->
    <view class="asset-card">
      <view class="asset-header">
        <text class="asset-title">模拟盘资产</text>
        <text class="initial-cash">初始资金: {{ formatMoney(portfolio.initial_cash) }}</text>
      </view>

      <view class="total-asset">
        <text class="asset-value">{{ formatMoney(portfolio.total_asset) }}</text>
        <text class="asset-label">总资产</text>
      </view>

      <view class="profit-row">
        <view class="profit-item">
          <text class="profit-value" :class="portfolio.total_profit >= 0 ? 'price-up' : 'price-down'">
            {{ portfolio.total_profit >= 0 ? '+' : '' }}{{ formatMoney(portfolio.total_profit) }}
          </text>
          <text class="profit-label">总盈亏</text>
        </view>
        <view class="profit-item">
          <text class="profit-value" :class="portfolio.total_profit_pct >= 0 ? 'price-up' : 'price-down'">
            {{ portfolio.total_profit_pct >= 0 ? '+' : '' }}{{ portfolio.total_profit_pct }}%
          </text>
          <text class="profit-label">收益率</text>
        </view>
        <view class="profit-item">
          <text class="profit-value" :class="portfolio.today_profit >= 0 ? 'price-up' : 'price-down'">
            {{ portfolio.today_profit >= 0 ? '+' : '' }}{{ formatMoney(portfolio.today_profit) }}
          </text>
          <text class="profit-label">今日盈亏</text>
        </view>
      </view>

      <view class="asset-detail">
        <view class="detail-item">
          <text class="detail-label">可用资金</text>
          <text class="detail-value">{{ formatMoney(portfolio.available_cash) }}</text>
        </view>
        <view class="detail-item">
          <text class="detail-label">持仓市值</text>
          <text class="detail-value">{{ formatMoney(portfolio.market_value) }}</text>
        </view>
        <view class="detail-item">
          <text class="detail-label">持仓数</text>
          <text class="detail-value">{{ portfolio.position_count }}只</text>
        </view>
        <view class="detail-item">
          <text class="detail-label">今日交易</text>
          <text class="detail-value">{{ portfolio.today_trade_count }}笔</text>
        </view>
      </view>
    </view>

    <!-- 操作按钮 -->
    <view class="action-row">
      <view class="action-btn" @click="onRefresh">
        <text>刷新</text>
      </view>
      <view class="action-btn reset-btn" @click="onReset">
        <text>重置组合</text>
      </view>
      <view class="action-btn history-btn" @click="goHistory">
        <text>交易历史</text>
      </view>
    </view>

    <!-- 持仓列表 -->
    <view class="section">
      <view class="section-header">
        <text class="section-title">持仓列表</text>
        <text class="section-count">{{ positions.length }}只</text>
      </view>

      <view v-if="positions.length === 0" class="empty-section">
        <text>暂无持仓</text>
      </view>

      <view
        class="position-card"
        v-for="pos in positions"
        :key="pos.code"
      >
        <view class="pos-header">
          <view class="pos-left">
            <text class="pos-name">{{ pos.name }}</text>
            <text class="pos-code">{{ pos.code }}</text>
          </view>
          <view class="pos-right">
            <text class="pos-profit" :class="pos.floating_profit >= 0 ? 'price-up' : 'price-down'">
              {{ pos.floating_profit >= 0 ? '+' : '' }}{{ pos.floating_profit_pct }}%
            </text>
          </view>
        </view>

        <view class="pos-body">
          <view class="pos-row">
            <view class="pos-cell">
              <text class="cell-label">持仓</text>
              <text class="cell-value">{{ pos.quantity }}股</text>
            </view>
            <view class="pos-cell">
              <text class="cell-label">可卖</text>
              <text class="cell-value">{{ pos.available_quantity }}股</text>
            </view>
            <view class="pos-cell">
              <text class="cell-label">成本</text>
              <text class="cell-value">{{ formatPrice(pos.avg_cost) }}</text>
            </view>
            <view class="pos-cell">
              <text class="cell-label">现价</text>
              <text class="cell-value" :class="pos.current_price >= pos.avg_cost ? 'price-up' : 'price-down'">
                {{ formatPrice(pos.current_price) }}
              </text>
            </view>
          </view>

          <view class="pos-row">
            <view class="pos-cell">
              <text class="cell-label">市值</text>
              <text class="cell-value">{{ formatMoney(pos.market_value) }}</text>
            </view>
            <view class="pos-cell">
              <text class="cell-label">盈亏</text>
              <text class="cell-value" :class="pos.floating_profit >= 0 ? 'price-up' : 'price-down'">
                {{ pos.floating_profit >= 0 ? '+' : '' }}{{ formatMoney(pos.floating_profit) }}
              </text>
            </view>
            <view class="pos-cell">
              <text class="cell-label">止损</text>
              <text class="cell-value text-red">{{ formatPrice(pos.stop_loss) }}</text>
            </view>
            <view class="pos-cell">
              <text class="cell-label">止盈</text>
              <text class="cell-value text-green">{{ formatPrice(pos.take_profit) }}</text>
            </view>
          </view>
        </view>

        <view class="pos-footer">
          <text class="pos-date">买入: {{ pos.buy_date }}</text>
          <view class="sell-btn" @click="onSell(pos)">
            <text>卖出</text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script>
import { getPortfolio, getPositions, resetPortfolio, sellStock, getKillSwitchStatus } from '@/utils/api.js'

export default {
  data() {
    return {
      portfolio: {
        initial_cash: 200000,
        available_cash: 200000,
        market_value: 0,
        total_asset: 200000,
        total_profit: 0,
        total_profit_pct: 0,
        today_profit: 0,
        position_count: 0,
        today_trade_count: 0
      },
      positions: [],
      killSwitch: {
        active: false,
        reason: ''
      }
    }
  },

  onLoad() {
    this.loadData()
  },

  onShow() {
    this.loadData()
  },

  onPullDownRefresh() {
    this.loadData().then(() => uni.stopPullDownRefresh())
  },

  methods: {
    async loadData() {
      try {
        const [portfolioRes, positionsRes, killRes] = await Promise.all([
          getPortfolio(),
          getPositions(),
          getKillSwitchStatus()
        ])
        if (portfolioRes) this.portfolio = portfolioRes
        if (positionsRes && positionsRes.positions) this.positions = positionsRes.positions
        if (killRes) this.killSwitch = killRes
      } catch (e) {
        console.error('加载组合数据失败:', e)
      }
    },

    onRefresh() {
      this.loadData()
      uni.showToast({ title: '已刷新', icon: 'none' })
    },

    onReset() {
      uni.showModal({
        title: '确认重置',
        content: '将重置组合为初始状态（20万资金），清空所有持仓和交易记录。确定？',
        success: async (res) => {
          if (res.confirm) {
            try {
              await resetPortfolio()
              await this.loadData()
              uni.showToast({ title: '已重置', icon: 'success' })
            } catch (e) {
              uni.showToast({ title: '重置失败', icon: 'none' })
            }
          }
        }
      })
    },

    goHistory() {
      uni.navigateTo({ url: '/pages/history/history' })
    },

    onSell(pos) {
      if (pos.available_quantity <= 0) {
        uni.showToast({ title: '无可卖数量（T+1）', icon: 'none' })
        return
      }
      uni.showModal({
        title: '卖出 ' + pos.name,
        content: `可卖: ${pos.available_quantity}股\n现价: ${pos.current_price}\n盈亏: ${pos.floating_profit_pct}%`,
        editable: true,
        placeholderText: '输入卖出数量',
        success: async (res) => {
          if (res.confirm) {
            const qty = parseInt(res.content)
            if (!qty || qty <= 0 || qty % 100 !== 0) {
              uni.showToast({ title: '请输入100的整数倍', icon: 'none' })
              return
            }
            try {
              const result = await sellStock(pos.code, pos.current_price, qty, '手动卖出')
              if (result && result.order) {
                uni.showToast({ title: '卖出成功', icon: 'success' })
                this.loadData()
              } else {
                uni.showToast({ title: result.error || '卖出失败', icon: 'none' })
              }
            } catch (e) {
              uni.showToast({ title: '卖出失败', icon: 'none' })
            }
          }
        }
      })
    },

    formatMoney(val) {
      if (val === null || val === undefined) return '--'
      return Number(val).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    },

    formatPrice(price) {
      if (!price || price === 0) return '--'
      return Number(price).toFixed(2)
    }
  }
}
</script>

<style scoped>
.container {
  min-height: 100vh;
  background-color: #f6f7fb;
  padding: 20rpx;
}

.kill-strip {
  display: flex;
  justify-content: space-between;
  gap: 16rpx;
  padding: 18rpx 22rpx;
  margin-bottom: 18rpx;
  border-radius: 10rpx;
  background-color: #eefaf2;
  color: #138a43;
  font-size: 24rpx;
}

.kill-strip.active {
  background-color: #fff0f0;
  color: #d71920;
}

/* 资产卡片 */
.asset-card {
  background: #ffffff;
  border-radius: 12rpx;
  padding: 30rpx;
  margin-bottom: 20rpx;
  box-shadow: 0 8rpx 24rpx rgba(15, 23, 42, 0.05);
}

.asset-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20rpx;
}

.asset-title {
  font-size: 28rpx;
  color: #151922;
  font-weight: bold;
}

.initial-cash {
  font-size: 22rpx;
  color: #7b8494;
}

.total-asset {
  text-align: center;
  margin-bottom: 24rpx;
}

.asset-value {
  font-size: 52rpx;
  color: #151922;
  font-weight: bold;
  display: block;
}

.asset-label {
  font-size: 22rpx;
  color: #7b8494;
  display: block;
  margin-top: 6rpx;
}

.profit-row {
  display: flex;
  justify-content: space-around;
  margin-bottom: 24rpx;
  padding-bottom: 24rpx;
  border-bottom: 1rpx solid #edf0f5;
}

.profit-item {
  text-align: center;
}

.profit-value {
  font-size: 30rpx;
  font-weight: bold;
  display: block;
}

.profit-label {
  font-size: 20rpx;
  color: #7b8494;
  display: block;
  margin-top: 6rpx;
}

.asset-detail {
  display: flex;
  flex-wrap: wrap;
}

.detail-item {
  width: 50%;
  display: flex;
  justify-content: space-between;
  padding: 8rpx 0;
}

.detail-label {
  font-size: 24rpx;
  color: #7b8494;
}

.detail-value {
  font-size: 24rpx;
  color: #151922;
}

/* 操作行 */
.action-row {
  display: flex;
  gap: 16rpx;
  margin-bottom: 24rpx;
}

.action-btn {
  flex: 1;
  padding: 18rpx 0;
  text-align: center;
  background-color: #ffffff;
  border-radius: 10rpx;
  color: #d71920;
  font-size: 26rpx;
  box-shadow: 0 6rpx 18rpx rgba(15, 23, 42, 0.04);
}

.reset-btn {
  color: #f39c12;
}

.history-btn {
  color: #138a43;
}

/* 区块 */
.section {
  margin-bottom: 24rpx;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16rpx;
}

.section-title {
  font-size: 30rpx;
  color: #151922;
  font-weight: bold;
}

.section-count {
  font-size: 24rpx;
  color: #7b8494;
}

.empty-section {
  padding: 60rpx;
  text-align: center;
  color: #666;
  font-size: 26rpx;
  background-color: #ffffff;
  border-radius: 12rpx;
}

/* 持仓卡片 */
.position-card {
  background-color: #ffffff;
  border-radius: 12rpx;
  padding: 24rpx;
  margin-bottom: 16rpx;
  box-shadow: 0 8rpx 24rpx rgba(15, 23, 42, 0.05);
}

.pos-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16rpx;
}

.pos-name {
  font-size: 30rpx;
  color: #151922;
  font-weight: bold;
}

.pos-code {
  font-size: 22rpx;
  color: #7b8494;
  margin-left: 12rpx;
}

.pos-profit {
  font-size: 32rpx;
  font-weight: bold;
}

.pos-row {
  display: flex;
  margin-bottom: 12rpx;
}

.pos-cell {
  flex: 1;
}

.cell-label {
  font-size: 20rpx;
  color: #7b8494;
  display: block;
}

.cell-value {
  font-size: 26rpx;
  color: #151922;
  display: block;
  margin-top: 4rpx;
}

.text-red { color: #d71920; }
.text-green { color: #138a43; }

.pos-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1rpx solid #edf0f5;
  padding-top: 16rpx;
  margin-top: 12rpx;
}

.pos-date {
  font-size: 20rpx;
  color: #666;
}

.sell-btn {
  padding: 10rpx 30rpx;
  background-color: #138a43;
  border-radius: 20rpx;
  color: #ffffff;
  font-size: 24rpx;
  font-weight: bold;
}

.price-up { color: #d71920; }
.price-down { color: #138a43; }
</style>
