<template>
  <view class="container">
    <!-- 交易统计 -->
    <view class="stats-card">
      <view class="stats-title">交易统计</view>
      <view class="stats-grid">
        <view class="stat-item">
          <text class="stat-value">{{ stats.total_trades }}</text>
          <text class="stat-label">总交易</text>
        </view>
        <view class="stat-item">
          <text class="stat-value">{{ stats.sell_count }}</text>
          <text class="stat-label">已平仓</text>
        </view>
        <view class="stat-item">
          <text class="stat-value" :class="stats.win_rate >= 50 ? 'price-up' : 'price-down'">
            {{ stats.win_rate }}%
          </text>
          <text class="stat-label">胜率</text>
        </view>
        <view class="stat-item">
          <text class="stat-value">{{ stats.win_count }}/{{ stats.loss_count }}</text>
          <text class="stat-label">盈/亏</text>
        </view>
      </view>

      <view class="stats-detail">
        <view class="detail-row">
          <text class="detail-label">总实现盈亏</text>
          <text class="detail-value" :class="stats.total_realized_pnl >= 0 ? 'price-up' : 'price-down'">
            {{ stats.total_realized_pnl >= 0 ? '+' : '' }}{{ formatMoney(stats.total_realized_pnl) }}
          </text>
        </view>
        <view class="detail-row">
          <text class="detail-label">平均盈亏</text>
          <text class="detail-value" :class="stats.avg_profit >= 0 ? 'price-up' : 'price-down'">
            {{ stats.avg_profit >= 0 ? '+' : '' }}{{ formatMoney(stats.avg_profit) }}
          </text>
        </view>
        <view class="detail-row">
          <text class="detail-label">最大单笔盈利</text>
          <text class="detail-value price-up">+{{ formatMoney(stats.max_single_profit) }}</text>
        </view>
        <view class="detail-row">
          <text class="detail-label">最大单笔亏损</text>
          <text class="detail-value price-down">{{ formatMoney(stats.max_single_loss) }}</text>
        </view>
        <view class="detail-row">
          <text class="detail-label">总佣金</text>
          <text class="detail-value">{{ formatMoney(stats.total_commission) }}</text>
        </view>
        <view class="detail-row">
          <text class="detail-label">总印花税</text>
          <text class="detail-value">{{ formatMoney(stats.total_stamp_tax) }}</text>
        </view>
      </view>
    </view>

    <!-- 订单列表 -->
    <view class="section">
      <view class="section-header">
        <text class="section-title">交易记录</text>
        <text class="section-count">{{ orders.length }}笔</text>
      </view>

      <view v-if="orders.length === 0" class="empty-section">
        <text>暂无交易记录</text>
      </view>

      <view
        class="order-card"
        v-for="order in orders"
        :key="order.order_id"
      >
        <view class="order-header">
          <view class="order-left">
            <view class="order-type" :class="order.type === 'buy' ? 'type-buy' : 'type-sell'">
              {{ order.type === 'buy' ? '买' : '卖' }}
            </view>
            <text class="order-name">{{ order.name }}</text>
            <text class="order-code">{{ order.code }}</text>
          </view>
          <view class="order-right">
            <text class="order-pnl" v-if="order.type === 'sell'" :class="order.realized_pnl >= 0 ? 'price-up' : 'price-down'">
              {{ order.realized_pnl >= 0 ? '+' : '' }}{{ formatMoney(order.realized_pnl) }}
            </text>
          </view>
        </view>

        <view class="order-body">
          <view class="order-row">
            <view class="order-cell">
              <text class="cell-label">价格</text>
              <text class="cell-value">{{ formatPrice(order.price) }}</text>
            </view>
            <view class="order-cell">
              <text class="cell-label">数量</text>
              <text class="cell-value">{{ order.quantity }}股</text>
            </view>
            <view class="order-cell">
              <text class="cell-label">金额</text>
              <text class="cell-value">{{ formatMoney(order.amount) }}</text>
            </view>
            <view class="order-cell">
              <text class="cell-label">费用</text>
              <text class="cell-value">{{ formatMoney(order.total_fee) }}</text>
            </view>
          </view>
        </view>

        <view class="order-footer">
          <text class="order-reason">{{ order.reason }}</text>
          <text class="order-time">{{ order.created_at }}</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script>
import { getTradeStatistics, getOrders } from '@/utils/api.js'

export default {
  data() {
    return {
      stats: {
        total_trades: 0,
        sell_count: 0,
        win_count: 0,
        loss_count: 0,
        win_rate: 0,
        avg_profit: 0,
        max_single_profit: 0,
        max_single_loss: 0,
        total_realized_pnl: 0,
        total_commission: 0,
        total_stamp_tax: 0
      },
      orders: []
    }
  },

  onLoad() {
    this.loadData()
  },

  onPullDownRefresh() {
    this.loadData().then(() => uni.stopPullDownRefresh())
  },

  methods: {
    async loadData() {
      try {
        const [statsRes, ordersRes] = await Promise.all([
          getTradeStatistics(),
          getOrders(100)
        ])
        if (statsRes) this.stats = statsRes
        if (ordersRes && ordersRes.orders) this.orders = ordersRes.orders
      } catch (e) {
        console.error('加载交易数据失败:', e)
      }
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
  background-color: #0f0f23;
  padding: 20rpx;
}

/* 统计卡片 */
.stats-card {
  background: linear-gradient(135deg, #1a1a2e, #16213e);
  border-radius: 20rpx;
  padding: 30rpx;
  margin-bottom: 24rpx;
}

.stats-title {
  font-size: 30rpx;
  color: #fff;
  font-weight: bold;
  margin-bottom: 20rpx;
}

.stats-grid {
  display: flex;
  justify-content: space-around;
  margin-bottom: 24rpx;
  padding-bottom: 24rpx;
  border-bottom: 1rpx solid rgba(255,255,255,0.05);
}

.stat-item {
  text-align: center;
}

.stat-value {
  font-size: 36rpx;
  color: #fff;
  font-weight: bold;
  display: block;
}

.stat-label {
  font-size: 20rpx;
  color: #888;
  display: block;
  margin-top: 6rpx;
}

.stats-detail {
  display: flex;
  flex-wrap: wrap;
}

.detail-row {
  width: 50%;
  display: flex;
  justify-content: space-between;
  padding: 8rpx 10rpx;
}

.detail-label {
  font-size: 24rpx;
  color: #888;
}

.detail-value {
  font-size: 24rpx;
  color: #fff;
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
  color: #fff;
  font-weight: bold;
}

.section-count {
  font-size: 24rpx;
  color: #888;
}

.empty-section {
  padding: 60rpx;
  text-align: center;
  color: #666;
  font-size: 26rpx;
  background-color: #1a1a2e;
  border-radius: 16rpx;
}

/* 订单卡片 */
.order-card {
  background-color: #1a1a2e;
  border-radius: 16rpx;
  padding: 24rpx;
  margin-bottom: 16rpx;
}

.order-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16rpx;
}

.order-left {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.order-type {
  width: 44rpx;
  height: 44rpx;
  line-height: 44rpx;
  text-align: center;
  border-radius: 8rpx;
  font-size: 24rpx;
  font-weight: bold;
}

.type-buy {
  background-color: rgba(233,69,96,0.2);
  color: #e94560;
}

.type-sell {
  background-color: rgba(11,232,129,0.2);
  color: #0be881;
}

.order-name {
  font-size: 28rpx;
  color: #fff;
  font-weight: bold;
}

.order-code {
  font-size: 22rpx;
  color: #888;
}

.order-pnl {
  font-size: 30rpx;
  font-weight: bold;
}

.order-row {
  display: flex;
}

.order-cell {
  flex: 1;
}

.cell-label {
  font-size: 20rpx;
  color: #888;
  display: block;
}

.cell-value {
  font-size: 26rpx;
  color: #fff;
  display: block;
  margin-top: 4rpx;
}

.order-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1rpx solid rgba(255,255,255,0.05);
  padding-top: 12rpx;
  margin-top: 12rpx;
}

.order-reason {
  font-size: 22rpx;
  color: #3498db;
  max-width: 350rpx;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.order-time {
  font-size: 20rpx;
  color: #666;
}

.price-up { color: #e94560; }
.price-down { color: #0be881; }
</style>
