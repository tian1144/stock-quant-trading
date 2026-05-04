<template>
  <view class="container">
    <!-- 大盘指数 -->
    <view class="index-banner">
      <view class="index-item" v-for="idx in indices" :key="idx.code">
        <text class="index-name">{{ idx.name }}</text>
        <text class="index-value" :class="idx.pct_change >= 0 ? 'price-up' : 'price-down'">
          {{ formatPrice(idx.price) }}
        </text>
        <text class="index-change" :class="idx.pct_change >= 0 ? 'price-up' : 'price-down'">
          {{ idx.pct_change >= 0 ? '+' : '' }}{{ idx.pct_change }}%
        </text>
      </view>
    </view>

    <!-- 操作栏 -->
    <view class="action-row">
      <text class="section-title">行业板块排行</text>
      <view class="refresh-btn" @click="onRefresh">
        <text>{{ loading ? '刷新中...' : '刷新' }}</text>
      </view>
    </view>

    <!-- 板块列表 -->
    <view class="sector-list">
      <view
        class="sector-item"
        v-for="(sector, index) in sectors"
        :key="sector.code"
        @click="onSectorClick(sector)"
      >
        <view class="sector-rank">
          <text class="rank-num" :class="index < 3 ? 'rank-top' : ''">{{ index + 1 }}</text>
        </view>
        <view class="sector-info">
          <text class="sector-name">{{ sector.name }}</text>
          <view class="sector-detail">
            <text class="leader-text" v-if="sector.leader_name">
              龙头: {{ sector.leader_name }}
            </text>
            <text class="advance-text">
              {{ sector.advance_count || 0 }}涨/{{ sector.decline_count || 0 }}跌
            </text>
          </view>
        </view>
        <view class="sector-right">
          <text class="sector-change" :class="sector.pct_change >= 0 ? 'price-up' : 'price-down'">
            {{ sector.pct_change >= 0 ? '+' : '' }}{{ sector.pct_change }}%
          </text>
          <text class="sector-flow" :class="(sector.main_net_inflow || 0) >= 0 ? 'price-up' : 'price-down'">
            {{ formatFlow(sector.main_net_inflow) }}
          </text>
        </view>
      </view>

      <view class="loading" v-if="loading">
        <text>加载中...</text>
      </view>

      <view class="empty" v-if="!loading && sectors.length === 0">
        <text>暂无板块数据</text>
        <view class="refresh-btn" @click="onRefresh">点击加载</view>
      </view>
    </view>

    <!-- 板块详情弹窗 -->
    <view class="sector-modal" v-if="showDetail" @click="showDetail = false">
      <view class="modal-content" @click.stop>
        <view class="modal-header">
          <text class="modal-title">{{ detailSector.name }}</text>
          <view class="modal-close" @click="showDetail = false">
            <text>X</text>
          </view>
        </view>

        <view class="modal-body">
          <!-- 资金流向 -->
          <view class="detail-section" v-if="detailData.money_flow">
            <text class="section-label">资金流向</text>
            <view class="flow-grid">
              <view class="flow-cell">
                <text class="flow-l">主力净流入</text>
                <text class="flow-v" :class="(detailData.money_flow.main_net_inflow||0)>=0?'price-up':'price-down'">
                  {{ formatFlow(detailData.money_flow.main_net_inflow) }}
                </text>
              </view>
              <view class="flow-cell">
                <text class="flow-l">超大单</text>
                <text class="flow-v" :class="(detailData.money_flow.super_large_inflow||0)>=0?'price-up':'price-down'">
                  {{ formatFlow(detailData.money_flow.super_large_inflow) }}
                </text>
              </view>
            </view>
          </view>

          <!-- 龙头股 -->
          <view class="detail-section" v-if="detailData.leader">
            <text class="section-label">龙头股</text>
            <view class="leader-card">
              <text class="leader-name">{{ detailData.leader.name }}</text>
              <text class="leader-code">{{ detailData.leader.code }}</text>
              <text class="leader-change price-up">
                +{{ detailData.leader.pct_change }}%
              </text>
            </view>
          </view>

          <!-- 热门股 -->
          <view class="detail-section" v-if="detailData.hot_stocks && detailData.hot_stocks.length">
            <text class="section-label">热门股</text>
            <view class="hot-list">
              <view class="hot-item" v-for="s in detailData.hot_stocks" :key="s.code">
                <text class="hot-name">{{ s.name }}</text>
                <text class="hot-change" :class="s.pct_change >= 0 ? 'price-up' : 'price-down'">
                  {{ s.pct_change >= 0 ? '+' : '' }}{{ s.pct_change }}%
                </text>
              </view>
            </view>
          </view>

          <!-- 新闻 -->
          <view class="detail-section">
            <text class="section-label">相关新闻</text>
            <view v-if="detailData.positive_news && detailData.positive_news.length">
              <text class="news-tag positive-tag">利好</text>
              <view class="news-item" v-for="n in detailData.positive_news" :key="n.id">
                <text class="news-title">{{ n.title }}</text>
              </view>
            </view>
            <view v-if="detailData.negative_news && detailData.negative_news.length">
              <text class="news-tag negative-tag">利空</text>
              <view class="news-item" v-for="n in detailData.negative_news" :key="n.id">
                <text class="news-title">{{ n.title }}</text>
              </view>
            </view>
            <view v-if="!detailData.news || detailData.news.length === 0">
              <text class="empty-text">暂无相关新闻</text>
            </view>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script>
import { getSectors, getSectorDetail, getStockQuotes } from '@/utils/api.js'

export default {
  data() {
    return {
      sectors: [],
      loading: false,
      showDetail: false,
      detailSector: {},
      detailData: {},
      indices: [
        { code: '000001', name: '上证指数', price: 0, pct_change: 0 },
        { code: '399001', name: '深证成指', price: 0, pct_change: 0 },
        { code: '399006', name: '创业板指', price: 0, pct_change: 0 },
      ],
    }
  },

  onLoad() {
    this.loadData()
    this.loadIndices()
  },

  onPullDownRefresh() {
    this.loadData().then(() => uni.stopPullDownRefresh())
  },

  methods: {
    async loadData() {
      if (this.loading) return
      this.loading = true
      try {
        const res = await getSectors()
        if (res && res.sectors) {
          this.sectors = res.sectors
        }
      } catch (e) {
        console.error('加载板块数据失败:', e)
      } finally {
        this.loading = false
      }
    },

    async loadIndices() {
      // 大盘指数用现有股票数据模拟
      try {
        const codes = ['000001', '399001', '399006']
        const data = await getStockQuotes(codes)
        if (data && data.snapshots) {
          data.snapshots.forEach(s => {
            const idx = this.indices.find(i => i.code === s.code)
            if (idx) {
              idx.price = s.price
              idx.pct_change = s.pct_change || 0
            }
          })
        }
      } catch (e) {
        console.error('加载指数失败:', e)
      }
    },

    async onRefresh() {
      await this.loadData()
    },

    async onSectorClick(sector) {
      this.detailSector = sector
      this.showDetail = true
      try {
        const res = await getSectorDetail(sector.code)
        if (res) {
          this.detailData = res
        }
      } catch (e) {
        console.error('加载板块详情失败:', e)
      }
    },

    formatPrice(p) {
      if (!p) return '--'
      return Number(p).toFixed(2)
    },

    formatFlow(v) {
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
  background-color: #0f0f23;
}

/* 大盘指数 */
.index-banner {
  display: flex;
  justify-content: space-around;
  padding: 24rpx 20rpx;
  background: linear-gradient(135deg, #1a1a2e, #16213e);
}

.index-item {
  text-align: center;
}

.index-name {
  font-size: 22rpx;
  color: #888;
  display: block;
}

.index-value {
  font-size: 32rpx;
  font-weight: bold;
  display: block;
  margin-top: 6rpx;
}

.index-change {
  font-size: 24rpx;
  display: block;
  margin-top: 4rpx;
}

/* 操作栏 */
.action-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16rpx 20rpx;
}

.section-title {
  font-size: 30rpx;
  color: #fff;
  font-weight: bold;
}

.refresh-btn {
  padding: 10rpx 24rpx;
  background-color: rgba(52,152,219,0.2);
  border-radius: 20rpx;
  color: #3498db;
  font-size: 24rpx;
}

/* 板块列表 */
.sector-list {
  padding: 0 20rpx;
}

.sector-item {
  display: flex;
  align-items: center;
  padding: 20rpx 0;
  border-bottom: 1rpx solid rgba(255,255,255,0.05);
}

.sector-item:active {
  background-color: rgba(255,255,255,0.03);
}

.sector-rank {
  width: 60rpx;
  text-align: center;
}

.rank-num {
  font-size: 26rpx;
  color: #888;
  font-weight: bold;
}

.rank-top {
  color: #e94560;
  font-size: 30rpx;
}

.sector-info {
  flex: 1;
  margin-left: 16rpx;
}

.sector-name {
  font-size: 28rpx;
  color: #fff;
  display: block;
}

.sector-detail {
  display: flex;
  gap: 16rpx;
  margin-top: 6rpx;
}

.leader-text, .advance-text {
  font-size: 20rpx;
  color: #888;
}

.sector-right {
  text-align: right;
}

.sector-change {
  font-size: 30rpx;
  font-weight: bold;
  display: block;
}

.sector-flow {
  font-size: 20rpx;
  display: block;
  margin-top: 4rpx;
}

.loading, .empty {
  padding: 60rpx;
  text-align: center;
  color: #666;
  font-size: 26rpx;
}

.empty .refresh-btn {
  margin-top: 20rpx;
  display: inline-block;
}

/* 弹窗 */
.sector-modal {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0,0,0,0.7);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-content {
  width: 90%;
  max-height: 80vh;
  background-color: #1a1a2e;
  border-radius: 20rpx;
  overflow-y: auto;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 24rpx;
  border-bottom: 1rpx solid rgba(255,255,255,0.05);
}

.modal-title {
  font-size: 32rpx;
  color: #fff;
  font-weight: bold;
}

.modal-close {
  width: 48rpx;
  height: 48rpx;
  line-height: 48rpx;
  text-align: center;
  color: #888;
  font-size: 28rpx;
}

.modal-body {
  padding: 20rpx 24rpx;
}

.detail-section {
  margin-bottom: 24rpx;
}

.section-label {
  font-size: 26rpx;
  color: #3498db;
  font-weight: bold;
  display: block;
  margin-bottom: 12rpx;
}

.flow-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
}

.flow-cell {
  width: 45%;
}

.flow-l {
  font-size: 20rpx;
  color: #888;
  display: block;
}

.flow-v {
  font-size: 26rpx;
  font-weight: bold;
  display: block;
  margin-top: 4rpx;
}

.leader-card {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 16rpx;
  background-color: rgba(255,255,255,0.03);
  border-radius: 12rpx;
}

.leader-name {
  font-size: 28rpx;
  color: #fff;
  font-weight: bold;
}

.leader-code {
  font-size: 22rpx;
  color: #888;
}

.leader-change {
  font-size: 28rpx;
  font-weight: bold;
  margin-left: auto;
}

.hot-list {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
}

.hot-item {
  display: flex;
  align-items: center;
  gap: 10rpx;
  padding: 10rpx 16rpx;
  background-color: rgba(255,255,255,0.03);
  border-radius: 8rpx;
}

.hot-name {
  font-size: 24rpx;
  color: #fff;
}

.hot-change {
  font-size: 22rpx;
  font-weight: bold;
}

.news-tag {
  display: inline-block;
  padding: 4rpx 16rpx;
  border-radius: 8rpx;
  font-size: 22rpx;
  margin-bottom: 10rpx;
}

.positive-tag {
  color: #e94560;
  background-color: rgba(233,69,96,0.15);
}

.negative-tag {
  color: #0be881;
  background-color: rgba(11,232,129,0.15);
}

.news-item {
  padding: 10rpx 0;
  border-bottom: 1rpx solid rgba(255,255,255,0.03);
}

.news-title {
  font-size: 24rpx;
  color: #ddd;
}

.empty-text {
  font-size: 24rpx;
  color: #666;
}

.price-up { color: #e94560; }
.price-down { color: #0be881; }
</style>
