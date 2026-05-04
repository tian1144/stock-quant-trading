<template>
  <view class="container">
    <!-- 搜索栏 -->
    <view class="search-bar">
      <view class="search-box">
        <text class="search-icon">Q</text>
        <input
          class="search-input"
          placeholder="输入股票代码或名称"
          v-model="keyword"
          @confirm="onSearch"
        />
      </view>
      <view class="search-btn" @click="onSearch">
        <text>搜索</text>
      </view>
    </view>

    <!-- 大盘指数 -->
    <view class="index-banner">
      <view class="index-item" v-for="idx in indices" :key="idx.code">
        <text class="index-name">{{ idx.name }}</text>
        <text class="index-value" :class="idx.pct_change >= 0 ? 'price-up' : 'price-down'">
          {{ formatPrice(idx.price) }}
        </text>
        <text class="index-change" :class="idx.pct_change >= 0 ? 'price-up' : 'price-down'">
          {{ idx.pct_change >= 0 ? '+' : '' }}{{ formatPct(idx.pct_change) }}
        </text>
      </view>
    </view>

    <!-- 板块筛选 -->
    <view class="filter-bar">
      <view
        class="filter-tab"
        v-for="tab in filterTabs"
        :key="tab.key"
        :class="{ active: activeFilter === tab.key }"
        @click="activeFilter = tab.key; applyFilter()"
      >
        <text>{{ tab.label }}</text>
      </view>
    </view>

    <!-- 排序栏 -->
    <view class="sort-bar">
      <view
        class="sort-item"
        v-for="s in sortOptions"
        :key="s.key"
        :class="{ active: activeSort === s.key }"
        @click="onSortChange(s.key)"
      >
        <text>{{ s.label }}</text>
        <text class="sort-arrow" v-if="activeSort === s.key">{{ sortDirection === 'desc' ? '↓' : '↑' }}</text>
      </view>
    </view>

    <!-- 股票列表 -->
    <view class="stock-list">
      <view
        class="stock-item"
        v-for="stock in displayList"
        :key="stock.code"
        @click="onStockClick(stock)"
      >
        <view class="stock-left">
          <text class="stock-name">{{ stock.name }}</text>
          <text class="stock-code">{{ stock.code }}</text>
        </view>
        <view class="stock-mid">
          <text class="stock-price" :class="getPriceClass(stock)">
            {{ formatPrice(stock.price) }}
          </text>
        </view>
        <view class="stock-right">
          <view class="change-badge" :class="getPriceClass(stock)">
            <text>{{ formatChange(stock.pct_change) }}</text>
          </view>
          <text class="stock-amount">{{ formatAmount(stock.amount) }}</text>
        </view>
      </view>

      <view class="load-more" v-if="hasMore" @click="loadMore">
        <text>加载更多 ({{ displayList.length }}/{{ filteredStocks.length }})</text>
      </view>

      <view class="loading" v-if="loading">
        <text>加载中...</text>
      </view>

      <view class="empty" v-if="!loading && displayList.length === 0">
        <text>暂无数据</text>
        <view class="refresh-btn" @click="onRefresh">
          <text>点击刷新</text>
        </view>
      </view>
    </view>

    <!-- 底部 -->
    <view class="footer">
      <text class="footer-text">共 {{ totalCount }} 只股票 | 数据每5秒刷新</text>
    </view>
  </view>
</template>

<script>
import { getStockList, searchStocks, getStockQuotes } from '@/utils/api.js'

export default {
  data() {
    return {
      keyword: '',
      allStocks: [],
      filteredStocks: [],
      displayList: [],
      loading: false,
      hasMore: true,
      page: 1,
      pageSize: 50,
      totalCount: 0,
      refreshTimer: null,
      activeFilter: 'all',
      activeSort: 'change',
      sortDirection: 'desc',
      indices: [
        { code: '000001', name: '上证指数', price: 0, pct_change: 0 },
        { code: '399001', name: '深证成指', price: 0, pct_change: 0 },
        { code: '399006', name: '创业板指', price: 0, pct_change: 0 },
      ],
      filterTabs: [
        { key: 'all', label: '全部' },
        { key: 'sh', label: '沪A' },
        { key: 'sz', label: '深A' },
        { key: 'gem', label: '创业板' },
        { key: 'star', label: '科创板' },
      ],
      sortOptions: [
        { key: 'change', label: '涨跌幅' },
        { key: 'amount', label: '成交额' },
        { key: 'volume', label: '成交量' },
        { key: 'price', label: '价格' },
      ],
    }
  },

  onLoad() {
    this.loadStockList()
    this.loadIndices()
    this.startRefreshTimer()
  },

  onUnload() {
    this.stopRefreshTimer()
  },

  onPullDownRefresh() {
    this.loadStockList().then(() => uni.stopPullDownRefresh())
  },

  methods: {
    getPriceClass(stock) {
      if (!stock.pct_change || stock.pct_change === 0) return 'price-flat'
      return stock.pct_change > 0 ? 'price-up' : 'price-down'
    },

    formatPrice(price) {
      if (!price || price === 0) return '--'
      return Number(price).toFixed(2)
    },

    formatPct(pct) {
      if (!pct && pct !== 0) return '--'
      return Number(pct).toFixed(2) + '%'
    },

    formatChange(pctChange) {
      if (pctChange === null || pctChange === undefined) return '--'
      if (pctChange === 0) return '0.00%'
      const prefix = pctChange > 0 ? '+' : ''
      return prefix + Number(pctChange).toFixed(2) + '%'
    },

    formatAmount(amount) {
      if (!amount) return ''
      if (amount >= 100000000) return (amount / 100000000).toFixed(2) + '亿'
      if (amount >= 10000) return (amount / 10000).toFixed(0) + '万'
      return amount.toFixed(0)
    },

    async loadStockList() {
      if (this.loading) return
      this.loading = true
      try {
        const res = await getStockList(10000, 0)
        if (res && res.stocks) {
          this.allStocks = res.stocks
          this.totalCount = res.total
          this.applyFilter()
        }
      } catch (e) {
        console.error('加载股票列表失败:', e)
        uni.showToast({ title: '加载失败', icon: 'none' })
      } finally {
        this.loading = false
      }
    },

    async loadIndices() {
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

    applyFilter() {
      let list = this.allStocks
      if (this.activeFilter !== 'all') {
        list = list.filter(s => {
          const code = s.code || ''
          if (this.activeFilter === 'sh') return code.startsWith('60')
          if (this.activeFilter === 'sz') return code.startsWith('00')
          if (this.activeFilter === 'gem') return code.startsWith('30')
          if (this.activeFilter === 'star') return code.startsWith('68')
          return true
        })
      }
      this.filteredStocks = list
      this.page = 1
      this.applySorting()
    },

    applySorting() {
      const sorted = [...this.filteredStocks]
      const dir = this.sortDirection === 'desc' ? -1 : 1
      const key = this.activeSort
      sorted.sort((a, b) => {
        let va = a[key] || 0
        let vb = b[key] || 0
        return (va - vb) * dir
      })
      this.filteredStocks = sorted
      this.displayList = sorted.slice(0, this.page * this.pageSize)
      this.hasMore = sorted.length > this.displayList.length
    },

    onSortChange(key) {
      if (this.activeSort === key) {
        this.sortDirection = this.sortDirection === 'desc' ? 'asc' : 'desc'
      } else {
        this.activeSort = key
        this.sortDirection = 'desc'
      }
      this.applySorting()
    },

    loadMore() {
      this.page++
      this.displayList = this.filteredStocks.slice(0, this.page * this.pageSize)
      this.hasMore = this.filteredStocks.length > this.displayList.length
    },

    async onSearch() {
      if (!this.keyword.trim()) {
        this.applyFilter()
        return
      }
      this.loading = true
      try {
        const res = await searchStocks(this.keyword)
        if (res) {
          this.displayList = res
          this.hasMore = false
        }
      } catch (e) {
        console.error('搜索失败:', e)
      } finally {
        this.loading = false
      }
    },

    onRefresh() {
      this.loadStockList()
      this.loadIndices()
    },

    onStockClick(stock) {
      uni.navigateTo({
        url: `/pages/stock-detail/stock-detail?code=${stock.code}`
      })
    },

    startRefreshTimer() {
      this.refreshTimer = setInterval(() => {
        this.refreshQuotes()
      }, 5000)
    },

    stopRefreshTimer() {
      if (this.refreshTimer) {
        clearInterval(this.refreshTimer)
        this.refreshTimer = null
      }
    },

    async refreshQuotes() {
      try {
        const res = await getStockList(10000, 0)
        if (res && res.stocks) {
          this.allStocks = res.stocks
          this.applyFilter()
          this.loadIndices()
        }
      } catch (e) {
        // silent
      }
    }
  }
}
</script>

<style scoped>
.container {
  min-height: 100vh;
  background-color: #f6f7fb;
  padding-bottom: 20rpx;
}

/* 搜索栏 */
.search-bar {
  display: flex;
  align-items: center;
  padding: 16rpx 20rpx;
  background: #d71920;
  gap: 16rpx;
}

.search-box {
  flex: 1;
  display: flex;
  align-items: center;
  height: 68rpx;
  background-color: #ffffff;
  border-radius: 8rpx;
  padding: 0 24rpx;
}

.search-icon {
  font-size: 28rpx;
  color: #9aa3b2;
  margin-right: 12rpx;
}

.search-input {
  flex: 1;
  color: #151922;
  font-size: 26rpx;
}

.search-btn {
  padding: 0 28rpx;
  height: 68rpx;
  line-height: 68rpx;
  background-color: #b9151b;
  border-radius: 8rpx;
  color: #fff;
  font-size: 26rpx;
}

/* 大盘指数 */
.index-banner {
  display: flex;
  justify-content: space-around;
  padding: 20rpx;
  background: #ffffff;
  box-shadow: 0 8rpx 24rpx rgba(15, 23, 42, 0.05);
}

.index-item {
  text-align: center;
}

.index-name {
  font-size: 20rpx;
  color: #7b8494;
  display: block;
}

.index-value {
  font-size: 30rpx;
  font-weight: bold;
  display: block;
  margin-top: 4rpx;
}

.index-change {
  font-size: 22rpx;
  display: block;
  margin-top: 2rpx;
}

/* 板块筛选 */
.filter-bar {
  display: flex;
  padding: 16rpx 20rpx;
  gap: 12rpx;
  background-color: #f6f7fb;
  overflow-x: auto;
  white-space: nowrap;
}

.filter-tab {
  padding: 12rpx 28rpx;
  border-radius: 24rpx;
  font-size: 24rpx;
  color: #666f7f;
  background-color: #ffffff;
  border: 1rpx solid #edf0f5;
}

.filter-tab.active {
  color: #ffffff;
  background-color: #d71920;
}

/* 排序栏 */
.sort-bar {
  display: flex;
  padding: 14rpx 20rpx;
  border-bottom: 1rpx solid #edf0f5;
  background-color: #ffffff;
}

.sort-item {
  flex: 1;
  text-align: center;
  font-size: 22rpx;
  color: #7b8494;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4rpx;
}

.sort-item.active {
  color: #d71920;
}

.sort-arrow {
  font-size: 20rpx;
}

/* 股票列表 */
.stock-list {
  padding: 0 20rpx;
}

.stock-item {
  display: flex;
  align-items: center;
  padding: 20rpx 0;
  border-bottom: 1rpx solid #edf0f5;
}

.stock-item:active {
  background-color: #fff7f7;
}

.stock-left {
  flex: 2;
}

.stock-name {
  font-size: 28rpx;
  color: #151922;
  display: block;
}

.stock-code {
  font-size: 20rpx;
  color: #9aa3b2;
  display: block;
  margin-top: 4rpx;
}

.stock-mid {
  flex: 1.2;
  text-align: right;
}

.stock-price {
  font-size: 30rpx;
  font-weight: bold;
}

.stock-right {
  flex: 1.5;
  text-align: right;
}

.change-badge {
  display: inline-block;
  padding: 6rpx 16rpx;
  border-radius: 8rpx;
  font-size: 24rpx;
  font-weight: bold;
}

.stock-amount {
  font-size: 20rpx;
  color: #666;
  display: block;
  margin-top: 4rpx;
}

/* 涨跌色 */
.price-up { color: #d71920; }
.price-down { color: #138a43; }
.price-flat { color: #7b8494; }

/* 加载 */
.load-more {
  padding: 30rpx;
  text-align: center;
  color: #7b8494;
  font-size: 26rpx;
}

.loading {
  padding: 30rpx;
  text-align: center;
  color: #7b8494;
  font-size: 26rpx;
}

.empty {
  padding: 80rpx 30rpx;
  text-align: center;
  color: #7b8494;
  font-size: 28rpx;
}

.refresh-btn {
  margin-top: 24rpx;
  padding: 16rpx 48rpx;
  background-color: #d71920;
  border-radius: 8rpx;
  color: #fff;
  font-size: 26rpx;
  display: inline-block;
}

/* 底部 */
.footer {
  padding: 30rpx;
  text-align: center;
}

.footer-text {
  font-size: 20rpx;
  color: #9aa3b2;
}
</style>
