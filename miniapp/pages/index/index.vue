<template>
  <view class="container">
    <!-- 搜索栏 -->
    <view class="search-bar">
      <input 
        class="search-input" 
        placeholder="输入股票代码或名称搜索" 
        v-model="keyword"
        @confirm="onSearch"
      />
      <view class="search-btn" @click="onSearch">搜索</view>
    </view>

    <!-- 股票列表 -->
    <view class="stock-list">
      <view class="list-header">
        <text class="header-name">股票名称/代码</text>
        <text class="header-price">最新价</text>
        <text class="header-change">涨跌幅</text>
      </view>
      
      <view 
        class="stock-item" 
        v-for="(stock, index) in stockList" 
        :key="stock.code"
        @click="onStockClick(stock)"
      >
        <view class="stock-info">
          <text class="stock-name">{{ stock.name }}</text>
          <text class="stock-code">{{ stock.code }}</text>
        </view>
        <view class="stock-price">
          <text class="price-value" :class="getPriceClass(stock)">
            {{ formatPrice(stock.price) }}
          </text>
        </view>
        <view class="stock-change">
          <text class="change-badge" :class="getPriceClass(stock)">
            {{ formatChange(stock.pct_change) }}
          </text>
        </view>
      </view>

      <!-- 加载更多 -->
      <view class="load-more" v-if="hasMore" @click="loadMore">
        <text>加载更多</text>
      </view>
      
      <!-- 加载中 -->
      <view class="loading" v-if="loading">
        <text>加载中...</text>
      </view>
      
      <!-- 空状态 -->
      <view class="empty" v-if="!loading && stockList.length === 0">
        <text>暂无数据</text>
        <view class="sync-btn" @click="onRefresh">刷新</view>
      </view>
    </view>
    
    <!-- 底部刷新提示 -->
    <view class="footer">
      <text class="footer-text">数据每5秒自动刷新 | 共{{ totalCount }}只股票</text>
    </view>
  </view>
</template>

<script>
import { getStockList, searchStocks, getStockQuotes } from '@/utils/api.js'

export default {
  data() {
    return {
      keyword: '',
      stockList: [],
      allStocks: [],
      loading: false,
      hasMore: true,
      page: 1,
      pageSize: 50,
      totalCount: 0,
      refreshTimer: null
    }
  },
  
  onLoad() {
    this.loadStockList()
    this.startRefreshTimer()
  },
  
  onUnload() {
    this.stopRefreshTimer()
  },
  
  onPullDownRefresh() {
    this.page = 1
    this.stockList = []
    this.loadStockList().then(() => {
      uni.stopPullDownRefresh()
    })
  },
  
  methods: {
    // 获取价格样式类
    getPriceClass(stock) {
      if (!stock.pct_change || stock.pct_change === 0) return 'price-flat'
      return stock.pct_change > 0 ? 'price-up' : 'price-down'
    },
    
    // 格式化价格
    formatPrice(price) {
      if (!price || price === 0) return '--'
      return price.toFixed(2)
    },
    
    // 格式化涨跌幅
    formatChange(pctChange) {
      if (pctChange === null || pctChange === undefined) return '--'
      if (pctChange === 0) return '0.00%'
      const prefix = pctChange > 0 ? '+' : ''
      return prefix + pctChange.toFixed(2) + '%'
    },
    
    // 加载股票列表（API已经包含实时行情数据）
    async loadStockList() {
      if (this.loading) return
      
      this.loading = true
      try {
        const res = await getStockList(10000, 0)
        if (res && res.stocks) {
          this.allStocks = res.stocks
          this.totalCount = res.total
          this.page = 1
          this.stockList = this.allStocks.slice(0, this.pageSize)
          this.hasMore = this.allStocks.length > this.pageSize
        }
      } catch (e) {
        console.error('加载股票列表失败:', e)
        uni.showToast({ title: '加载失败，请检查后端服务', icon: 'none' })
      } finally {
        this.loading = false
      }
    },
    
    // 加载更多
    loadMore() {
      this.page++
      const end = this.page * this.pageSize
      this.stockList = this.allStocks.slice(0, end)
      this.hasMore = end < this.allStocks.length
    },
    
    // 搜索
    async onSearch() {
      if (!this.keyword.trim()) {
        this.stockList = this.allStocks.slice(0, this.pageSize)
        this.hasMore = this.allStocks.length > this.pageSize
        return
      }
      
      this.loading = true
      try {
        const res = await searchStocks(this.keyword)
        if (res) {
          this.stockList = res
          this.hasMore = false
        }
      } catch (e) {
        console.error('搜索失败:', e)
        uni.showToast({ title: '搜索失败', icon: 'none' })
      } finally {
        this.loading = false
      }
    },
    
    // 刷新
    onRefresh() {
      this.page = 1
      this.stockList = []
      this.loadStockList()
    },
    
    // 点击股票
    onStockClick(stock) {
      uni.showToast({ title: stock.name + ' ' + stock.code, icon: 'none' })
    },
    
    // 开始定时刷新
    startRefreshTimer() {
      this.refreshTimer = setInterval(() => {
        this.refreshQuotes()
      }, 5000)
    },
    
    // 停止定时刷新
    stopRefreshTimer() {
      if (this.refreshTimer) {
        clearInterval(this.refreshTimer)
        this.refreshTimer = null
      }
    },
    
    // 刷新行情数据（重新从API获取）
    async refreshQuotes() {
      try {
        const res = await getStockList(10000, 0)
        if (res && res.stocks) {
          this.allStocks = res.stocks
          const end = this.page * this.pageSize
          this.stockList = this.allStocks.slice(0, end)
        }
      } catch (e) {
        console.error('刷新行情失败:', e)
      }
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

/* 搜索栏 */
.search-bar {
  display: flex;
  align-items: center;
  margin-bottom: 20rpx;
}

.search-input {
  flex: 1;
  height: 72rpx;
  background-color: #1a1a2e;
  border-radius: 36rpx;
  padding: 0 30rpx;
  color: #ffffff;
  font-size: 28rpx;
}

.search-btn {
  margin-left: 20rpx;
  padding: 0 30rpx;
  height: 72rpx;
  line-height: 72rpx;
  background-color: #e94560;
  border-radius: 36rpx;
  color: #ffffff;
  font-size: 28rpx;
}

/* 股票列表 */
.stock-list {
  background-color: #1a1a2e;
  border-radius: 16rpx;
  overflow: hidden;
}

.list-header {
  display: flex;
  padding: 20rpx 30rpx;
  background-color: #16213e;
  font-size: 24rpx;
  color: #888888;
}

.header-name {
  flex: 2;
}

.header-price {
  flex: 1;
  text-align: right;
}

.header-change {
  flex: 1.2;
  text-align: right;
}

.stock-item {
  display: flex;
  align-items: center;
  padding: 24rpx 30rpx;
  border-bottom: 1rpx solid rgba(22, 33, 62, 0.5);
}

.stock-item:active {
  background-color: #16213e;
}

.stock-info {
  flex: 2;
}

.stock-name {
  font-size: 30rpx;
  color: #ffffff;
  display: block;
}

.stock-code {
  font-size: 22rpx;
  color: #888888;
  display: block;
  margin-top: 5rpx;
}

.stock-price {
  flex: 1;
  text-align: right;
}

.price-value {
  font-size: 30rpx;
  font-weight: bold;
}

.stock-change {
  flex: 1.2;
  text-align: right;
}

.change-badge {
  display: inline-block;
  padding: 6rpx 16rpx;
  border-radius: 8rpx;
  font-size: 26rpx;
  font-weight: bold;
}

/* 涨跌颜色 */
.price-up {
  color: #e94560;
  background-color: rgba(233, 69, 96, 0.15);
}

.price-down {
  color: #0be881;
  background-color: rgba(11, 232, 129, 0.15);
}

.price-flat {
  color: #888888;
  background-color: rgba(136, 136, 136, 0.15);
}

/* 加载更多 */
.load-more {
  padding: 30rpx;
  text-align: center;
  color: #888888;
  font-size: 28rpx;
}

.load-more:active {
  background-color: #16213e;
}

/* 加载中 */
.loading {
  padding: 30rpx;
  text-align: center;
  color: #888888;
  font-size: 28rpx;
}

/* 空状态 */
.empty {
  padding: 100rpx 30rpx;
  text-align: center;
  color: #888888;
  font-size: 28rpx;
}

.sync-btn {
  margin-top: 30rpx;
  display: inline-block;
  padding: 20rpx 60rpx;
  background-color: #e94560;
  border-radius: 40rpx;
  color: #ffffff;
  font-size: 28rpx;
}

.sync-btn:active {
  opacity: 0.8;
}

/* 底部提示 */
.footer {
  padding: 30rpx;
  text-align: center;
}

.footer-text {
  font-size: 22rpx;
  color: #555555;
}
</style>