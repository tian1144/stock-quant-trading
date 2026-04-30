<template>
  <view class="container">
    <view class="search-bar">
      <input class="search-input" v-model="keyword" placeholder="搜索股票代码或名称..." @confirm="onSearch"/>
      <button class="search-btn" @click="onSearch">搜索</button>
      <button class="reset-btn" @click="resetSearch">重置</button>
    </view>
    <view class="stats">
      <text>共 <text class="count">{{ stockList.length }}</text> 只股票</text>
      <text class="update-time">最后更新：{{ lastUpdate }}</text>
    </view>
    <view class="stock-list">
      <view class="stock-item" v-for="stock in stockList" :key="stock.code" @click="onStockClick(stock)">
        <view class="stock-info">
          <text class="stock-name">{{ stock.name }}</text>
          <text class="stock-code">{{ stock.code }}</text>
        </view>
        <view class="stock-price"><text class="price" :class="getPriceClass(stock)">{{ formatPrice(stock.price) }}</text></view>
        <view class="stock-change"><text class="change-badge" :class="getPriceClass(stock)">{{ formatChange(stock.pct_change) }}</text></view>
      </view>
    </view>
    <view class="load-more" v-if="hasMore" @click="loadMore"><text>点击加载更多</text></view>
    <view class="empty" v-if="!loading && stockList.length === 0"><text>暂无数据</text></view>
    <view class="loading" v-if="loading"><text>正在加载数据...</text></view>
  </view>
</template>

<script>
import { getStockList } from '@/utils/api.js'

export default {
  data() {
    return {
      keyword: '', totalStocks: [], stockList: [],
      pageSize: 50, currentPage: 1, lastUpdate: '--',
      loading: false, refreshTimer: null, isSearching: false
    }
  },
  computed: {
    hasMore() { return !this.isSearching && this.currentPage * this.pageSize < this.totalStocks.length }
  },
  async onLoad() { await this.loadStockList(); this.startRefresh() },
  onUnload() { if (this.refreshTimer) clearInterval(this.refreshTimer) },
  methods: {
    async loadStockList() {
      if (this.loading) return
      this.loading = true
      try {
        const data = await getStockList({ limit: 10000, offset: 0 })
        if (data && data.stocks) {
          this.totalStocks = data.stocks
          this.currentPage = 1
          this.isSearching = false
          this.renderStockList()
          this.lastUpdate = new Date().toLocaleTimeString()
        }
      } catch (e) { console.error('加载失败:', e) }
      finally { this.loading = false }
    },
    renderStockList() {
      if (this.isSearching) return
      this.stockList = this.totalStocks.slice(0, this.currentPage * this.pageSize)
    },
    loadMore() { this.currentPage++; this.renderStockList() },
    async onSearch() {
      const kw = this.keyword.trim().toLowerCase()
      if (!kw) { this.resetSearch(); return }
      this.isSearching = true
      this.stockList = this.totalStocks.filter(s => s.code.toLowerCase().includes(kw) || s.name.toLowerCase().includes(kw))
    },
    resetSearch() { this.keyword = ''; this.isSearching = false; this.currentPage = 1; this.renderStockList() },
    startRefresh() { this.refreshTimer = setInterval(() => this.loadStockList(), 5000) },
    formatPrice(p) { return (p || p === 0) ? p.toFixed(2) : '--' },
    formatChange(c) { if (c == null) return '--'; if (c === 0) return '0.00%'; return (c > 0 ? '+' : '') + c.toFixed(2) + '%' },
    getPriceClass(s) { if (!s.pct_change || s.pct_change === 0) return 'price-flat'; return s.pct_change > 0 ? 'price-up' : 'price-down' },
    onStockClick(s) { console.log('点击:', s.code, s.name) }
  }
}
</script>

<style scoped>
.container { min-height: 100vh; background-color: #0f0f23; }
.search-bar { padding: 20rpx 30rpx; display: flex; gap: 20rpx; background-color: #12122b; }
.search-input { flex: 1; height: 70rpx; border-radius: 35rpx; padding: 0 30rpx; background-color: #1a1a2e; color: #fff; font-size: 28rpx; border: 1px solid #2a2a4a; }
.search-btn { height: 70rpx; line-height: 70rpx; padding: 0 30rpx; border-radius: 35rpx; background-color: #e94560; color: #fff; font-size: 26rpx; border: none; }
.reset-btn { height: 70rpx; line-height: 70rpx; padding: 0 30rpx; border-radius: 35rpx; background-color: #2a2a4a; color: #ccc; font-size: 26rpx; border: none; }
.stats { padding: 20rpx 30rpx; display: flex; justify-content: space-between; color: #888; font-size: 24rpx; }
.count { color: #e94560; font-weight: bold; }
.stock-item { padding: 25rpx 30rpx; display: flex; align-items: center; border-bottom: 1px solid #1a1a2e; }
.stock-info { flex: 1; }
.stock-name { color: #fff; font-size: 30rpx; font-weight: 500; }
.stock-code { color: #666; font-size: 24rpx; margin-top: 5rpx; }
.stock-price { width: 180rpx; text-align: right; font-size: 30rpx; font-weight: bold; }
.stock-change { width: 150rpx; text-align: right; }
.price-up { color: #e94560; }
.price-down { color: #0be881; }
.price-flat { color: #888; }
.change-badge { display: inline-block; padding: 6rpx 16rpx; border-radius: 8rpx; font-size: 24rpx; font-weight: 600; }
.change-badge.price-up { background-color: rgba(233,69,96,0.15); }
.change-badge.price-down { background-color: rgba(11,232,129,0.15); }
.change-badge.price-flat { background-color: rgba(136,136,136,0.15); }
.load-more { text-align: center; padding: 30rpx; color: #888; }
.empty { text-align: center; padding: 200rpx 0; color: #555; }
.loading { text-align: center; padding: 100rpx 0; color: #888; }
</style>
