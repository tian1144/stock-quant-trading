<template>
  <view class="container">
    <!-- 系统状态栏 -->
    <view class="kill-banner" :class="{ active: killSwitch.active }">
      <view>
        <text class="kill-title">{{ killSwitch.active ? '熔断已开启' : '熔断未开启' }}</text>
        <text class="kill-desc">{{ killSwitch.active ? (killSwitch.reason || '交易执行已暂停') : '交易执行链路正常' }}</text>
      </view>
      <view class="kill-action" @click="toggleKillSwitch">
        <text>{{ killSwitch.active ? '解除' : '熔断' }}</text>
      </view>
    </view>

    <view class="status-bar">
      <view class="status-item">
        <text class="status-label">自动交易</text>
        <view class="toggle-btn" :class="{ active: autoTrade, disabled: killSwitch.active }" @click="toggleAutoTrade">
          <text>{{ killSwitch.active ? 'HALT' : (autoTrade ? 'ON' : 'OFF') }}</text>
        </view>
      </view>
      <view class="status-item">
        <text class="status-label">交易时段</text>
        <text class="status-value" :class="isTradingHours ? 'text-green' : 'text-gray'">
          {{ isTradingHours ? '交易中' : '已休市' }}
        </text>
      </view>
    </view>

    <!-- 操作按钮 -->
    <view class="action-row">
      <view class="detect-btn" @click="onDetect" :class="{ detecting: detecting }">
        <text>{{ detecting ? '检测中...' : '手动检测信号' }}</text>
      </view>
      <view class="refresh-info">
        <text>每5秒自动检测</text>
      </view>
    </view>

    <!-- 买入信号 -->
    <view class="section">
      <view class="section-header">
        <text class="section-title buy-color">买入信号</text>
        <text class="section-count">{{ buySignals.length }}</text>
      </view>

      <view v-if="buySignals.length === 0" class="empty-section">
        <text>暂无买入信号</text>
      </view>

      <view
        class="signal-card buy-card"
        v-for="signal in buySignals"
        :key="signal.signal_id"
      >
        <view class="card-header">
          <view class="card-left">
            <text class="stock-name">{{ signal.name }}</text>
            <text class="stock-code">{{ signal.code }}</text>
          </view>
          <view class="card-right">
            <text class="signal-strength" :class="'strength-' + signal.strength">
              {{ strengthText(signal.strength) }}
            </text>
          </view>
        </view>

        <view class="card-body">
          <view class="info-row">
            <text class="info-label">信号价格</text>
            <text class="info-value">{{ formatPrice(signal.price) }}</text>
          </view>
          <view class="info-row">
            <text class="info-label">目标价</text>
            <text class="info-value price-up">{{ formatPrice(signal.target_price) }}</text>
          </view>
          <view class="info-row">
            <text class="info-label">止损价</text>
            <text class="info-value price-down">{{ formatPrice(signal.stop_loss_price) }}</text>
          </view>
          <view class="info-row">
            <text class="info-label">触发条件</text>
            <text class="info-value conditions">{{ signal.reason }}</text>
          </view>
        </view>

        <view class="card-footer">
          <text class="expire-time">{{ signal.expires_at }} 过期</text>
          <view class="execute-btn" @click="onExecuteBuy(signal)">
            <text>执行买入</text>
          </view>
        </view>
      </view>
    </view>

    <!-- 卖出信号 -->
    <view class="section">
      <view class="section-header">
        <text class="section-title sell-color">卖出信号</text>
        <text class="section-count">{{ sellSignals.length }}</text>
      </view>

      <view v-if="sellSignals.length === 0" class="empty-section">
        <text>暂无卖出信号</text>
      </view>

      <view
        class="signal-card sell-card"
        v-for="signal in sellSignals"
        :key="signal.signal_id"
      >
        <view class="card-header">
          <view class="card-left">
            <text class="stock-name">{{ signal.name }}</text>
            <text class="stock-code">{{ signal.code }}</text>
          </view>
          <view class="card-right">
            <text class="signal-strength" :class="'strength-' + signal.strength">
              {{ strengthText(signal.strength) }}
            </text>
          </view>
        </view>

        <view class="card-body">
          <view class="info-row">
            <text class="info-label">当前价</text>
            <text class="info-value">{{ formatPrice(signal.price) }}</text>
          </view>
          <view class="info-row">
            <text class="info-label">成本价</text>
            <text class="info-value">{{ formatPrice(signal.avg_cost) }}</text>
          </view>
          <view class="info-row">
            <text class="info-label">浮动盈亏</text>
            <text class="info-value" :class="signal.floating_profit_pct >= 0 ? 'price-up' : 'price-down'">
              {{ signal.floating_profit_pct >= 0 ? '+' : '' }}{{ signal.floating_profit_pct }}%
            </text>
          </view>
          <view class="info-row">
            <text class="info-label">卖出数量</text>
            <text class="info-value">{{ signal.quantity }}股</text>
          </view>
          <view class="info-row">
            <text class="info-label">触发条件</text>
            <text class="info-value conditions">{{ signal.reason }}</text>
          </view>
        </view>

        <view class="card-footer">
          <text class="expire-time">{{ signal.expires_at }} 过期</text>
          <view class="execute-btn sell-btn" @click="onExecuteSell(signal)">
            <text>执行卖出</text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script>
import {
  getSignals,
  detectSignals,
  toggleAutoTrade,
  getSystemStatus,
  buyStock,
  sellStock,
  getKillSwitchStatus,
  activateKillSwitch,
  deactivateKillSwitch
} from '@/utils/api.js'

export default {
  data() {
    return {
      buySignals: [],
      sellSignals: [],
      autoTrade: false,
      isTradingHours: false,
      detecting: false,
      refreshTimer: null,
      killSwitch: {
        active: false,
        reason: '',
        triggered_at: ''
      }
    }
  },

  onLoad() {
    this.loadData()
    this.loadStatus()
    this.loadKillSwitch()
    this.startAutoRefresh()
  },

  onUnload() {
    this.stopAutoRefresh()
  },

  onPullDownRefresh() {
    Promise.all([this.loadData(), this.loadStatus(), this.loadKillSwitch()]).then(() => uni.stopPullDownRefresh())
  },

  methods: {
    async loadData() {
      try {
        const res = await getSignals()
        if (res) {
          this.buySignals = res.buy_signals || []
          this.sellSignals = res.sell_signals || []
        }
      } catch (e) {
        console.error('加载信号失败:', e)
      }
    },

    async loadStatus() {
      try {
        const res = await getSystemStatus()
        if (res) {
          this.autoTrade = res.auto_trade_enabled || false
          this.isTradingHours = res.is_trading_hours || false
        }
      } catch (e) {
        console.error('加载状态失败:', e)
      }
    },

    async loadKillSwitch() {
      try {
        const res = await getKillSwitchStatus()
        if (res) this.killSwitch = res
      } catch (e) {
        console.error('加载熔断状态失败:', e)
      }
    },

    async onDetect() {
      if (this.detecting) return
      this.detecting = true
      try {
        const res = await detectSignals()
        if (res) {
          this.buySignals = res.buy_signals || []
          this.sellSignals = res.sell_signals || []
          uni.showToast({ title: `检测到${res.total}个信号`, icon: 'none' })
        }
      } catch (e) {
        console.error('检测失败:', e)
        uni.showToast({ title: '检测失败', icon: 'none' })
      } finally {
        this.detecting = false
      }
    },

    async toggleAutoTrade() {
      if (this.killSwitch.active) {
        uni.showToast({ title: '熔断中，自动交易不可开启', icon: 'none' })
        return
      }
      const newState = !this.autoTrade
      try {
        await toggleAutoTrade(newState)
        this.autoTrade = newState
        uni.showToast({ title: `自动交易已${newState ? '开启' : '关闭'}`, icon: 'none' })
      } catch (e) {
        console.error('切换失败:', e)
      }
    },

    toggleKillSwitch() {
      if (this.killSwitch.active) {
        uni.showModal({
          title: '解除熔断',
          content: '确认恢复交易执行链路？',
          success: async (res) => {
            if (res.confirm) {
              await deactivateKillSwitch()
              await this.loadKillSwitch()
              uni.showToast({ title: '熔断已解除', icon: 'none' })
            }
          }
        })
      } else {
        uni.showModal({
          title: '启动熔断',
          content: '启动后手动交易和自动交易都会被风控拒绝。',
          success: async (res) => {
            if (res.confirm) {
              await activateKillSwitch('前端手动熔断')
              await this.loadKillSwitch()
              uni.showToast({ title: '已启动熔断', icon: 'none' })
            }
          }
        })
      }
    },

    onExecuteBuy(signal) {
      uni.showModal({
        title: '确认买入',
        content: `${signal.name} ${signal.code}\n价格: ${signal.price}\n条件: ${signal.reason}`,
        success: async (res) => {
          if (res.confirm) {
            try {
              const qty = 100
              const result = await buyStock(signal.code, signal.price, qty, `信号买入: ${signal.reason}`)
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

    onExecuteSell(signal) {
      uni.showModal({
        title: '确认卖出',
        content: `${signal.name} ${signal.code}\n价格: ${signal.price}\n数量: ${signal.quantity}股\n条件: ${signal.reason}`,
        success: async (res) => {
          if (res.confirm) {
            try {
              const result = await sellStock(signal.code, signal.price, signal.quantity, `信号卖出: ${signal.reason}`)
              if (result && result.order) {
                uni.showToast({ title: '卖出成功', icon: 'success' })
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

    startAutoRefresh() {
      this.refreshTimer = setInterval(() => {
        this.loadData()
        this.loadKillSwitch()
      }, 5000)
    },

    stopAutoRefresh() {
      if (this.refreshTimer) {
        clearInterval(this.refreshTimer)
        this.refreshTimer = null
      }
    },

    strengthText(strength) {
      const map = { strong: '强', medium: '中', weak: '弱' }
      return map[strength] || strength
    },

    formatPrice(price) {
      if (!price || price === 0) return '--'
      return price.toFixed(2)
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

.kill-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 22rpx 24rpx;
  margin-bottom: 20rpx;
  background-color: #ffffff;
  border-radius: 12rpx;
  border: 1rpx solid #edf0f5;
  box-shadow: 0 8rpx 24rpx rgba(15, 23, 42, 0.05);
}

.kill-banner.active {
  background-color: #fff0f0;
  border-color: #ffd6d6;
}

.kill-title {
  display: block;
  color: #151922;
  font-size: 30rpx;
  font-weight: bold;
}

.kill-desc {
  display: block;
  margin-top: 4rpx;
  color: #666f7f;
  font-size: 22rpx;
}

.kill-action {
  padding: 12rpx 24rpx;
  border-radius: 8rpx;
  color: #ffffff;
  background-color: #d71920;
  font-size: 24rpx;
  font-weight: bold;
}

/* 状态栏 */
.status-bar {
  display: flex;
  justify-content: space-around;
  background-color: #ffffff;
  border-radius: 12rpx;
  padding: 24rpx;
  margin-bottom: 20rpx;
  box-shadow: 0 8rpx 24rpx rgba(15, 23, 42, 0.05);
}

.status-item {
  text-align: center;
}

.status-label {
  font-size: 22rpx;
  color: #7b8494;
  display: block;
  margin-bottom: 10rpx;
}

.status-value {
  font-size: 28rpx;
  font-weight: bold;
}

.toggle-btn {
  display: inline-block;
  padding: 10rpx 30rpx;
  border-radius: 8rpx;
  background-color: #f2f4f8;
  color: #7b8494;
  font-size: 26rpx;
  font-weight: bold;
}

.toggle-btn.active {
  background-color: #fff0f0;
  color: #d71920;
}

.toggle-btn.disabled {
  background-color: #fff0f0;
  color: #d71920;
}

.text-green { color: #138a43; }
.text-gray { color: #7b8494; }

/* 操作行 */
.action-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20rpx;
}

.detect-btn {
  padding: 16rpx 36rpx;
  background-color: #d71920;
  border-radius: 8rpx;
  color: #fff;
  font-size: 26rpx;
}

.detect-btn.detecting {
  opacity: 0.6;
}

.refresh-info {
  font-size: 22rpx;
  color: #9aa3b2;
}

/* 区块 */
.section {
  margin-bottom: 30rpx;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16rpx;
}

.section-title {
  font-size: 32rpx;
  font-weight: bold;
}

.buy-color { color: #d71920; }
.sell-color { color: #138a43; }

.section-count {
  font-size: 28rpx;
  color: #7b8494;
  background-color: #ffffff;
  padding: 6rpx 20rpx;
  border-radius: 20rpx;
}

.empty-section {
  padding: 40rpx;
  text-align: center;
  color: #666;
  font-size: 26rpx;
  background-color: #ffffff;
  border-radius: 12rpx;
  box-shadow: 0 8rpx 24rpx rgba(15, 23, 42, 0.04);
}

/* 信号卡片 */
.signal-card {
  background-color: #ffffff;
  border-radius: 12rpx;
  padding: 24rpx;
  margin-bottom: 16rpx;
  border-left: 6rpx solid transparent;
  box-shadow: 0 8rpx 24rpx rgba(15, 23, 42, 0.05);
}

.buy-card { border-left-color: #d71920; }
.sell-card { border-left-color: #138a43; }

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16rpx;
}

.stock-name {
  font-size: 30rpx;
  color: #151922;
  font-weight: bold;
}

.stock-code {
  font-size: 22rpx;
  color: #7b8494;
  margin-left: 12rpx;
}

.signal-strength {
  padding: 6rpx 20rpx;
  border-radius: 16rpx;
  font-size: 24rpx;
  font-weight: bold;
}

.strength-strong { color: #d71920; background-color: #fff0f0; }
.strength-medium { color: #b45309; background-color: #fff8eb; }
.strength-weak { color: #7b8494; background-color: #f2f4f8; }

.card-body {
  margin-bottom: 16rpx;
}

.info-row {
  display: flex;
  justify-content: space-between;
  padding: 8rpx 0;
}

.info-label {
  font-size: 24rpx;
  color: #7b8494;
}

.info-value {
  font-size: 24rpx;
  color: #151922;
}

.conditions {
  color: #d71920;
  text-align: right;
  max-width: 400rpx;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1rpx solid #edf0f5;
  padding-top: 16rpx;
}

.expire-time {
  font-size: 20rpx;
  color: #9aa3b2;
}

.execute-btn {
  padding: 12rpx 30rpx;
  background-color: #d71920;
  border-radius: 20rpx;
  color: #fff;
  font-size: 24rpx;
}

.sell-btn {
  background-color: #138a43;
  color: #ffffff;
}

.price-up { color: #d71920; }
.price-down { color: #138a43; }
</style>
