<template>
  <view class="container">
    <!-- 交易风格 -->
    <view class="section">
      <text class="section-title">交易风格</text>
      <view class="option-cards">
        <view
          class="option-card"
          v-for="style in tradingStyles"
          :key="style.value"
          :class="{ active: settings.trading_style === style.value }"
          @click="settings.trading_style = style.value"
        >
          <text class="option-icon">{{ style.icon }}</text>
          <text class="option-name">{{ style.label }}</text>
          <text class="option-desc">{{ style.desc }}</text>
        </view>
      </view>
    </view>

    <!-- 风险偏好 -->
    <view class="section">
      <text class="section-title">风险偏好</text>
      <view class="option-cards">
        <view
          class="option-card"
          v-for="risk in riskLevels"
          :key="risk.value"
          :class="{ active: settings.risk_appetite === risk.value }"
          @click="settings.risk_appetite = risk.value"
        >
          <text class="option-icon">{{ risk.icon }}</text>
          <text class="option-name">{{ risk.label }}</text>
          <text class="option-desc">{{ risk.desc }}</text>
        </view>
      </view>
    </view>

    <!-- 板块开关 -->
    <view class="section">
      <text class="section-title">板块偏好</text>
      <view class="toggle-list">
        <view class="toggle-item">
          <text class="toggle-label">主板</text>
          <switch :checked="settings.board_allow.main" @change="settings.board_allow.main = $event.detail.value" color="#d71920" />
        </view>
        <view class="toggle-item">
          <text class="toggle-label">创业板</text>
          <switch :checked="settings.board_allow.gem" @change="settings.board_allow.gem = $event.detail.value" color="#d71920" />
        </view>
        <view class="toggle-item">
          <text class="toggle-label">科创板</text>
          <switch :checked="settings.board_allow.star" @change="settings.board_allow.star = $event.detail.value" color="#d71920" />
        </view>
        <view class="toggle-item">
          <text class="toggle-label">北交所</text>
          <switch :checked="settings.board_allow.bse" @change="settings.board_allow.bse = $event.detail.value" color="#d71920" />
        </view>
      </view>
    </view>

    <!-- 板块黑名单 -->
    <view class="section">
      <text class="section-title">板块黑名单</text>
      <view class="blacklist">
        <view class="blocked-tag" v-for="(sector, index) in settings.blocked_sectors" :key="index">
          <text>{{ sector }}</text>
          <view class="remove-btn" @click="removeBlockedSector(index)">
            <text>X</text>
          </view>
        </view>
        <view class="add-btn" @click="addBlockedSector">
          <text>+ 添加</text>
        </view>
      </view>
    </view>

    <!-- 保存按钮 -->
    <view class="save-btn" @click="onSave">
      <text>保存设置</text>
    </view>

    <!-- 说明 -->
    <view class="info-section">
      <text class="info-title">说明</text>
      <text class="info-text">- 短线模式：选股侧重量价和资金流向，适合日内/隔日交易</text>
      <text class="info-text">- 中线模式：均衡考虑各因子，适合1-4周持有</text>
      <text class="info-text">- 长线模式：选股侧重技术面和市场情绪，适合1月以上持有</text>
      <text class="info-text">- 板块黑名单：被屏蔽的板块股票不会出现在选股结果中</text>
    </view>
  </view>
</template>

<script>
import { getSettings, updateSettings } from '@/utils/api.js'

export default {
  data() {
    return {
      settings: {
        trading_style: 'short',
        risk_appetite: 'moderate',
        board_allow: {
          main: true,
          gem: true,
          star: true,
          bse: true,
        },
        blocked_sectors: [],
      },
      tradingStyles: [
        { value: 'short', label: '短线', icon: 'T', desc: '日内/隔日，量价资金为主' },
        { value: 'medium', label: '中线', icon: 'M', desc: '1-4周，均衡各因子' },
        { value: 'long', label: '长线', icon: 'L', desc: '1月+，技术情绪为主' },
      ],
      riskLevels: [
        { value: 'conservative', label: '保守', icon: 'S', desc: '低风险，稳健收益' },
        { value: 'moderate', label: '稳健', icon: 'B', desc: '平衡风险与收益' },
        { value: 'aggressive', label: '激进', icon: 'G', desc: '高风险，追求高收益' },
      ],
    }
  },

  onLoad() {
    this.loadSettings()
  },

  methods: {
    async loadSettings() {
      try {
        const res = await getSettings()
        if (res) {
          this.settings = {
            ...this.settings,
            ...res,
            board_allow: { ...this.settings.board_allow, ...(res.board_allow || {}) },
          }
        }
      } catch (e) {
        console.error('加载设置失败:', e)
      }
    },

    async onSave() {
      try {
        await updateSettings(this.settings)
        uni.showToast({ title: '保存成功', icon: 'success' })
      } catch (e) {
        console.error('保存失败:', e)
        uni.showToast({ title: '保存失败', icon: 'none' })
      }
    },

    addBlockedSector() {
      uni.showModal({
        title: '添加板块黑名单',
        editable: true,
        placeholderText: '输入板块名称（如：房地产）',
        success: (res) => {
          if (res.confirm && res.content && res.content.trim()) {
            const name = res.content.trim()
            if (!this.settings.blocked_sectors.includes(name)) {
              this.settings.blocked_sectors.push(name)
            }
          }
        }
      })
    },

    removeBlockedSector(index) {
      this.settings.blocked_sectors.splice(index, 1)
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

.section {
  margin-bottom: 30rpx;
}

.section-title {
  font-size: 30rpx;
  color: #151922;
  font-weight: bold;
  display: block;
  margin-bottom: 16rpx;
}

/* 选项卡片 */
.option-cards {
  display: flex;
  gap: 16rpx;
}

.option-card {
  flex: 1;
  padding: 24rpx 16rpx;
  background-color: #ffffff;
  border-radius: 12rpx;
  text-align: center;
  border: 2rpx solid transparent;
  box-shadow: 0 6rpx 18rpx rgba(15, 23, 42, 0.04);
}

.option-card.active {
  border-color: #d71920;
  background-color: #fff7f7;
}

.option-icon {
  font-size: 40rpx;
  display: block;
  margin-bottom: 8rpx;
}

.option-name {
  font-size: 28rpx;
  color: #151922;
  font-weight: bold;
  display: block;
}

.option-desc {
  font-size: 20rpx;
  color: #7b8494;
  display: block;
  margin-top: 6rpx;
}

/* Toggle列表 */
.toggle-list {
  background-color: #ffffff;
  border-radius: 12rpx;
  padding: 8rpx 24rpx;
  box-shadow: 0 6rpx 18rpx rgba(15, 23, 42, 0.04);
}

.toggle-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20rpx 0;
  border-bottom: 1rpx solid #edf0f5;
}

.toggle-item:last-child {
  border-bottom: none;
}

.toggle-label {
  font-size: 28rpx;
  color: #151922;
}

/* 黑名单 */
.blacklist {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
}

.blocked-tag {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 10rpx 20rpx;
  background-color: #fff0f0;
  border-radius: 8rpx;
  color: #d71920;
  font-size: 24rpx;
}

.remove-btn {
  width: 32rpx;
  height: 32rpx;
  line-height: 32rpx;
  text-align: center;
  font-size: 20rpx;
  color: #d71920;
}

.add-btn {
  padding: 10rpx 20rpx;
  background-color: #f2f4f8;
  border-radius: 8rpx;
  color: #666f7f;
  font-size: 24rpx;
}

/* 保存按钮 */
.save-btn {
  margin: 30rpx 0;
  padding: 28rpx 0;
  text-align: center;
  background-color: #d71920;
  border-radius: 10rpx;
  color: #fff;
  font-size: 30rpx;
  font-weight: bold;
}

.save-btn:active {
  opacity: 0.8;
}

/* 说明 */
.info-section {
  padding: 24rpx;
  background-color: #ffffff;
  border-radius: 12rpx;
  box-shadow: 0 6rpx 18rpx rgba(15, 23, 42, 0.04);
}

.info-title {
  font-size: 26rpx;
  color: #d71920;
  display: block;
  margin-bottom: 12rpx;
}

.info-text {
  font-size: 22rpx;
  color: #7b8494;
  display: block;
  margin-bottom: 8rpx;
  line-height: 1.6;
}
</style>
