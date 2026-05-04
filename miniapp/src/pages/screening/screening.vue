<template>
  <view class="desktop-shell">
    <view class="sidebar">
      <view class="brand">
        <view class="brand-mark">QH</view>
        <view>
          <text class="brand-title">量化猎人</text>
          <text class="brand-subtitle">高质量信号 · 低频执行</text>
        </view>
      </view>

      <view class="nav">
        <view
          v-for="item in navItems"
          :key="item.key"
          class="nav-item"
          :class="{ active: item.key === 'screening' }"
          @click="goPage(item)"
        >
          <text class="nav-cn">{{ item.label }}</text>
          <text class="nav-en">{{ item.meta }}</text>
        </view>
      </view>
    </view>

    <view class="main">
      <view class="topbar">
        <view class="search-wrap">
          <text class="search-label">搜索</text>
          <input
            class="search-input"
            placeholder="输入任意股票名称或代码，例如 茅 / 平 / 600"
            v-model="keyword"
            @input="onSearchInput"
            @confirm="onSearch"
          />
          <view class="suggestions" v-if="showSuggestions">
            <view
              v-for="stock in searchResults"
              :key="stock.code"
              class="suggestion-item"
              @click="selectSearchStock(stock)"
            >
              <view>
                <text class="suggestion-name">{{ stock.name || '--' }}</text>
                <text class="suggestion-code">{{ stock.code }}</text>
              </view>
              <text class="suggestion-meta">{{ stock.market || stock.exchange || 'A股' }}</text>
            </view>
            <view class="suggestion-empty" v-if="!searching && searchResults.length === 0">
              未找到匹配个股
            </view>
          </view>
        </view>

        <view class="top-actions">
          <view class="strategy-pill">策略：<text>{{ strategyName }}</text></view>
          <view class="status-pill" :class="{ warn: serviceWarn }">
            <text class="status-dot"></text>
            <text>{{ serviceWarn ? '服务异常' : '服务正常' }}</text>
          </view>
          <view class="btn secondary" @click="loadData">刷新</view>
          <view class="btn primary" :class="{ disabled: loading }" @click="onRefresh">
            {{ loading ? '运行中' : '运行选股' }}
          </view>
          <view class="btn danger" @click="toggleKillSwitch">
            {{ killActive ? '解除熔断' : '熔断' }}
          </view>
        </view>
      </view>

      <view class="hero">
        <text class="hero-title">小型灵活猎人型量化工具</text>
        <text class="hero-copy">
          以量化手册为准：新闻监控、公告解读、情绪判断、盘口结构分析、技术分析、结构化决策、风控复核和模拟交易闭环。
        </text>
        <view class="hero-tags">
          <text>高质量信号</text>
          <text>低频执行</text>
          <text>小容量机会</text>
          <text>交易执行正常</text>
        </view>
      </view>

      <view class="metric-grid">
        <view class="metric-card">
          <text class="metric-label">选股池</text>
          <text class="metric-value">{{ stockList.length }}</text>
          <text class="metric-sub">Top50 候选</text>
        </view>
        <view class="metric-card">
          <text class="metric-label">最高评分</text>
          <text class="metric-value red">{{ bestScore }}</text>
          <text class="metric-sub">多因子综合</text>
        </view>
        <view class="metric-card">
          <text class="metric-label">买入候选</text>
          <text class="metric-value">{{ buyCandidateCount }}</text>
          <text class="metric-sub">观察池 {{ watchCount }} 只</text>
        </view>
        <view class="metric-card">
          <text class="metric-label">市场情绪</text>
          <text class="metric-value tone">{{ marketTone }}</text>
          <text class="metric-sub">{{ updatedAt ? `更新 ${updatedAt}` : '等待刷新' }}</text>
        </view>
      </view>

      <view class="content-grid">
        <view class="panel">
          <view class="panel-title">
            <text>最新选股 Top5</text>
            <view class="btn compact primary" :class="{ disabled: loading }" @click="onRefresh">
              {{ loading ? '运行中' : '运行选股' }}
            </view>
          </view>
          <view class="top-list">
            <view v-for="(stock, index) in topFive" :key="stock.code" class="top-row" @click="onStockClick(stock)">
              <text class="rank">{{ index + 1 }}</text>
              <view class="stock-cell">
                <text class="stock-name">{{ stock.name || '--' }}</text>
                <text class="stock-code">{{ stock.code }}</text>
              </view>
              <text class="score">{{ formatScore(stock.score) }}</text>
            </view>
            <view class="empty-state" v-if="!loading && topFive.length === 0">
              暂无选股结果，点击“运行选股”生成。
            </view>
            <view class="empty-state" v-if="loading">
              正在智能筛选中...
            </view>
          </view>
        </view>

        <view class="panel">
          <view class="panel-title">
            <text>执行安全状态</text>
            <text class="badge" :class="killActive ? 'danger' : 'ok'">{{ killActive ? '熔断中' : '正常' }}</text>
          </view>
          <view class="status-table">
            <view class="status-row">
              <text>交易时段</text>
              <text>非交易时段</text>
            </view>
            <view class="status-row">
              <text>自动交易</text>
              <text>已关闭</text>
            </view>
            <view class="status-row">
              <text>最大持仓</text>
              <text>0 / 10</text>
            </view>
            <view class="status-row">
              <text>风险提示</text>
              <text>{{ killActive ? (killReason || '熔断已开启，交易执行暂停') : '默认模拟交易，真实下单未开启' }}</text>
            </view>
          </view>
        </view>
      </view>

      <view class="panel screening-panel">
        <view class="panel-title">
          <view>
            <text>智能选股 Top50</text>
            <text class="panel-sub">量价、资金、技术、情绪综合评分</text>
          </view>
          <view class="update-text">{{ updatedAt ? `上次更新：${updatedAt}` : '尚未更新' }}</view>
        </view>

        <view class="table">
          <view class="table-head">
            <text>#</text>
            <text>股票</text>
            <text>评分</text>
            <text>现价</text>
            <text>涨跌</text>
            <text>信号</text>
          </view>
          <view
            class="table-row"
            v-for="(stock, index) in stockList"
            :key="stock.code"
            @click="onStockClick(stock)"
          >
            <text class="rank" :class="rankClass(index)">{{ index + 1 }}</text>
            <view class="stock-cell">
              <text class="stock-name">{{ stock.name || '--' }}</text>
              <text class="stock-code">{{ stock.code }}</text>
            </view>
            <view>
              <text class="score">{{ formatScore(stock.score) }}</text>
              <view class="score-bar">
                <view class="score-fill" :style="{ width: scoreWidth(stock.score) }"></view>
              </view>
            </view>
            <text>{{ formatPrice(stock.price) }}</text>
            <text class="change-badge" :class="changeClass(stock.pct_change)">
              {{ formatChange(stock.pct_change) }}
            </text>
            <text>{{ signalText(stock.signal_type) }}</text>
          </view>
          <view class="empty-state table-empty" v-if="!loading && stockList.length === 0">
            暂无选股结果，点击“运行选股”生成。
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script>
import {
  activateKillSwitch,
  deactivateKillSwitch,
  getKillSwitchStatus,
  getScreeningResults,
  runScreening,
  searchStocks
} from '@/utils/api.js'

export default {
  data() {
    return {
      keyword: '',
      searchTimer: null,
      searchResults: [],
      searching: false,
      stockList: [],
      loading: false,
      updatedAt: '',
      serviceWarn: false,
      killActive: false,
      killReason: '',
      strategyName: '短线策略',
      navItems: [
        { key: 'overview', label: '总览', meta: 'Overview', path: '/pages/index/index' },
        { key: 'market', label: '行情', meta: 'Market', path: '/pages/index/index' },
        { key: 'watch', label: '自选', meta: 'Watch', path: '/pages/index/index' },
        { key: 'strategy', label: '策略', meta: 'Strategy', path: '/pages/screening/screening' },
        { key: 'research', label: '研究', meta: 'Report', path: '/pages/stock-detail/stock-detail' },
        { key: 'screening', label: '选股', meta: 'Top50', path: '/pages/screening/screening' },
        { key: 'signals', label: '信号', meta: 'Signals', path: '/pages/signals/signals' },
        { key: 'portfolio', label: '持仓', meta: 'Paper', path: '/pages/portfolio/portfolio' },
        { key: 'history', label: '回测', meta: 'Lab', path: '/pages/history/history' },
        { key: 'news', label: '新闻', meta: 'Events', path: '/pages/news/news' },
        { key: 'risk', label: '风控', meta: 'Risk', path: '/pages/signals/signals' }
      ]
    }
  },

  computed: {
    topFive() {
      return this.stockList.slice(0, 5)
    },
    bestScore() {
      if (!this.stockList.length) return '--'
      return this.formatScore(Math.max(...this.stockList.map(s => Number(s.score) || 0)))
    },
    buyCandidateCount() {
      return this.stockList.filter(s => s.signal_type === 'buy_candidate').length
    },
    watchCount() {
      return this.stockList.filter(s => s.signal_type === 'watch').length
    },
    marketTone() {
      if (!this.stockList.length) return '中性偏多'
      const avg = this.stockList.reduce((sum, s) => sum + (Number(s.score) || 0), 0) / this.stockList.length
      if (avg >= 70) return '积极'
      if (avg >= 45) return '中性偏多'
      return '谨慎'
    },
    showSuggestions() {
      return this.keyword.trim().length > 0 && (this.searching || this.searchResults.length > 0)
    }
  },

  onLoad() {
    this.loadData()
    this.loadKillStatus()
  },

  onPullDownRefresh() {
    this.loadData().then(() => uni.stopPullDownRefresh())
  },

  methods: {
    async loadData() {
      try {
        const res = await getScreeningResults()
        if (res && res.results) {
          this.stockList = res.results
          this.updatedAt = res.updated_at || ''
        }
        this.serviceWarn = false
      } catch (e) {
        this.serviceWarn = true
        console.error('加载选股结果失败:', e)
      }
    },

    async loadKillStatus() {
      try {
        const res = await getKillSwitchStatus()
        this.killActive = !!(res && res.active)
        this.killReason = (res && res.reason) || ''
      } catch (e) {
        console.error('加载熔断状态失败:', e)
      }
    },

    async onRefresh() {
      if (this.loading) return
      this.loading = true
      try {
        const res = await runScreening()
        if (res && res.results) {
          this.stockList = res.results
          this.updatedAt = new Date().toLocaleString()
          uni.showToast({ title: `筛选出${res.count || res.results.length}只`, icon: 'none' })
        }
        this.serviceWarn = false
      } catch (e) {
        this.serviceWarn = true
        console.error('选股失败:', e)
        uni.showToast({ title: '选股失败，请检查后端服务', icon: 'none' })
      } finally {
        this.loading = false
      }
    },

    onSearchInput() {
      clearTimeout(this.searchTimer)
      const kw = this.keyword.trim()
      if (!kw) {
        this.searchResults = []
        this.searching = false
        return
      }
      this.searching = true
      this.searchTimer = setTimeout(() => this.fetchSearchResults(kw), 260)
    },

    async fetchSearchResults(keyword) {
      try {
        const res = await searchStocks(keyword)
        this.searchResults = Array.isArray(res) ? res.slice(0, 8) : []
      } catch (e) {
        this.searchResults = []
      } finally {
        this.searching = false
      }
    },

    async onSearch() {
      const kw = this.keyword.trim()
      if (!kw) return
      if (!this.searchResults.length) {
        await this.fetchSearchResults(kw)
      }
      if (this.searchResults.length) {
        this.selectSearchStock(this.searchResults[0])
      } else {
        uni.showToast({ title: '未找到匹配个股', icon: 'none' })
      }
    },

    selectSearchStock(stock) {
      this.keyword = `${stock.name || ''} ${stock.code}`.trim()
      this.searchResults = []
      uni.navigateTo({
        url: `/pages/stock-detail/stock-detail?code=${stock.code}`
      })
    },

    toggleKillSwitch() {
      const nextActive = !this.killActive
      uni.showModal({
        title: nextActive ? '启动熔断' : '解除熔断',
        content: nextActive
          ? '启动后模拟交易执行会暂停，适合异常行情或调试期间使用。'
          : '解除后模拟交易执行链路恢复可用。',
        success: async (res) => {
          if (!res.confirm) return
          try {
            if (nextActive) {
              const result = await activateKillSwitch('前端手动熔断')
              this.killActive = true
              this.killReason = result.reason || '前端手动熔断'
              uni.showToast({ title: '已启动熔断', icon: 'none' })
            } else {
              await deactivateKillSwitch()
              this.killActive = false
              this.killReason = ''
              uni.showToast({ title: '已解除熔断', icon: 'none' })
            }
          } catch (e) {
            uni.showToast({ title: '熔断操作失败', icon: 'none' })
          }
        }
      })
    },

    onStockClick(stock) {
      uni.navigateTo({
        url: `/pages/stock-detail/stock-detail?code=${stock.code}`
      })
    },

    goPage(item) {
      if (item.key === 'screening') return
      if (item.path === '/pages/stock-detail/stock-detail') {
        uni.navigateTo({ url: '/pages/stock-detail/stock-detail?code=600519' })
        return
      }
      uni.navigateTo({
        url: item.path,
        fail: () => uni.redirectTo({ url: item.path })
      })
    },

    rankClass(index) {
      if (index < 3) return 'rank-top'
      if (index < 10) return 'rank-high'
      return ''
    },

    changeClass(pct) {
      if (pct > 0) return 'price-up'
      if (pct < 0) return 'price-down'
      return 'price-flat'
    },

    signalText(signal) {
      if (signal === 'buy_candidate') return '买入候选'
      if (signal === 'watch') return '观察'
      return signal || '观察'
    },

    formatScore(score) {
      const value = Number(score)
      if (!Number.isFinite(value)) return '--'
      return value.toFixed(value % 1 === 0 ? 0 : 1)
    },

    scoreWidth(score) {
      const value = Math.max(0, Math.min(100, Number(score) || 0))
      return `${value}%`
    },

    formatPrice(price) {
      const value = Number(price)
      if (!Number.isFinite(value) || value === 0) return '--'
      return value.toFixed(2)
    },

    formatChange(pct) {
      const value = Number(pct)
      if (!Number.isFinite(value)) return '--'
      if (value === 0) return '0.00%'
      return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
    }
  }
}
</script>

<style scoped>
.desktop-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 252px minmax(0, 1fr);
  background: #f5f6fa;
  color: #151922;
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
}

.sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  padding: 22px 16px;
  background: #fff;
  border-right: 1px solid #e9edf3;
  overflow-y: auto;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 8px 22px;
}

.brand-mark {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: #d71920;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
}

.brand-title,
.brand-subtitle,
.nav-cn,
.nav-en,
.hero-title,
.hero-copy,
.metric-label,
.metric-value,
.metric-sub,
.panel-sub,
.update-text,
.stock-name,
.stock-code {
  display: block;
}

.brand-title {
  font-size: 18px;
  font-weight: 800;
}

.brand-subtitle {
  margin-top: 2px;
  color: #707988;
  font-size: 12px;
}

.nav {
  display: grid;
  gap: 6px;
}

.nav-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 48px;
  padding: 0 12px;
  border-radius: 10px;
  color: #707988;
  cursor: pointer;
}

.nav-item.active {
  background: #fff0f0;
  color: #d71920;
}

.nav-cn {
  font-size: 16px;
  font-weight: 800;
}

.nav-en {
  color: #a2aab7;
  font-size: 12px;
}

.main {
  min-width: 0;
  padding: 22px;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: grid;
  grid-template-columns: minmax(320px, 1fr) auto;
  gap: 14px;
  align-items: center;
  padding: 12px;
  margin: -22px -22px 18px;
  background: rgba(245, 246, 250, 0.92);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid rgba(233, 237, 243, 0.8);
}

.search-wrap {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  height: 44px;
  padding: 0 14px;
  border: 1px solid #e9edf3;
  border-radius: 12px;
  background: #fff;
}

.search-label {
  color: #8a93a3;
  font-weight: 700;
}

.search-input {
  min-width: 0;
  flex: 1;
  height: 42px;
  color: #151922;
  font-size: 15px;
}

.suggestions {
  position: absolute;
  left: 0;
  right: 0;
  top: calc(100% + 8px);
  z-index: 50;
  max-height: 320px;
  overflow-y: auto;
  padding: 8px;
  border: 1px solid #e9edf3;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 14px 36px rgba(15, 23, 42, 0.08);
}

.suggestion-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 10px 12px;
  border-radius: 10px;
  cursor: pointer;
}

.suggestion-item:hover {
  background: #fff0f0;
}

.suggestion-name {
  font-size: 14px;
  font-weight: 800;
}

.suggestion-code {
  margin-left: 8px;
  color: #707988;
  font-family: Menlo, Consolas, monospace;
  font-size: 12px;
}

.suggestion-meta,
.suggestion-empty {
  color: #707988;
  font-size: 12px;
}

.suggestion-empty {
  padding: 10px 12px;
}

.top-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.strategy-pill,
.status-pill,
.btn {
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #e9edf3;
  border-radius: 10px;
  background: #fff;
  white-space: nowrap;
}

.strategy-pill {
  padding: 0 14px;
  font-weight: 700;
}

.strategy-pill text {
  font-weight: 900;
}

.status-pill {
  gap: 7px;
  padding: 0 12px;
  color: #707988;
  font-size: 13px;
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #15a15a;
  box-shadow: 0 0 0 4px #e9f8ef;
}

.status-pill.warn .status-dot {
  background: #d71920;
  box-shadow: 0 0 0 4px #fff0f0;
}

.btn {
  padding: 0 15px;
  color: #151922;
  font-weight: 800;
  cursor: pointer;
}

.btn.primary {
  background: #d71920;
  border-color: #d71920;
  color: #fff;
}

.btn.secondary {
  background: #fff;
}

.btn.danger {
  background: #fff0f0;
  border-color: #ffd4d4;
  color: #d71920;
}

.btn.compact {
  min-height: 34px;
  padding: 0 14px;
}

.btn.disabled {
  opacity: 0.58;
  pointer-events: none;
}

.hero {
  padding: 30px 28px;
  border-radius: 18px;
  background: linear-gradient(135deg, #e31b23 0%, #a9161d 100%);
  color: #fff;
}

.hero-title {
  font-size: 30px;
  font-weight: 900;
}

.hero-copy {
  max-width: 760px;
  margin-top: 16px;
  font-size: 17px;
  font-weight: 700;
  line-height: 1.7;
}

.hero-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 24px;
}

.hero-tags text {
  padding: 8px 14px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.14);
  font-size: 13px;
  font-weight: 800;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 18px;
  margin-top: 18px;
}

.metric-card,
.panel {
  border: 1px solid #edf0f5;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 14px 36px rgba(15, 23, 42, 0.06);
}

.metric-card {
  padding: 22px;
}

.metric-label {
  color: #8a93a3;
  font-size: 13px;
}

.metric-value {
  margin-top: 8px;
  color: #151922;
  font-family: Menlo, Consolas, monospace;
  font-size: 28px;
  font-weight: 900;
}

.metric-value.red,
.score {
  color: #d71920;
}

.metric-value.tone {
  color: #d71920;
  font-family: inherit;
}

.metric-sub {
  margin-top: 8px;
  color: #9aa3b2;
  font-size: 12px;
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 18px;
  margin-top: 18px;
}

.panel-title {
  min-height: 62px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 18px 22px;
  border-bottom: 1px solid #edf0f5;
  font-size: 18px;
  font-weight: 900;
}

.panel-sub,
.update-text {
  margin-top: 4px;
  color: #8a93a3;
  font-size: 12px;
  font-weight: 500;
}

.top-list,
.status-table {
  padding: 18px 22px;
}

.top-row,
.table-row,
.status-row {
  display: grid;
  align-items: center;
  gap: 14px;
  min-height: 36px;
  border-bottom: 1px dashed #edf0f5;
}

.top-row {
  grid-template-columns: 44px minmax(0, 1fr) auto;
  cursor: pointer;
}

.top-row:last-child,
.status-row:last-child,
.table-row:last-child {
  border-bottom: 0;
}

.rank {
  color: #718095;
  font-family: Menlo, Consolas, monospace;
}

.rank-top {
  color: #d71920;
  font-weight: 900;
}

.rank-high {
  color: #b45309;
  font-weight: 900;
}

.stock-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #151922;
  font-weight: 900;
}

.stock-code {
  margin-top: 2px;
  color: #8a93a3;
  font-family: Menlo, Consolas, monospace;
  font-size: 12px;
}

.score {
  font-family: Menlo, Consolas, monospace;
  font-weight: 900;
}

.badge {
  padding: 5px 12px;
  border-radius: 9px;
  font-size: 12px;
  font-weight: 900;
}

.badge.ok {
  background: #e9f8ef;
  color: #138a43;
}

.badge.danger {
  background: #fff0f0;
  color: #d71920;
}

.status-row {
  grid-template-columns: 110px minmax(0, 1fr);
  padding: 10px 0;
}

.status-row text:first-child {
  color: #8a93a3;
}

.status-row text:last-child {
  font-weight: 800;
}

.screening-panel {
  margin-top: 18px;
}

.table {
  overflow-x: auto;
}

.table-head,
.table-row {
  display: grid;
  grid-template-columns: 56px minmax(150px, 1.5fr) minmax(100px, 1fr) minmax(90px, .8fr) minmax(90px, .8fr) minmax(100px, .8fr);
  align-items: center;
  min-width: 760px;
  padding: 14px 22px;
}

.table-head {
  color: #8a93a3;
  background: #fafbfe;
  font-size: 12px;
  font-weight: 800;
}

.table-row {
  cursor: pointer;
}

.table-row:hover,
.top-row:hover {
  background: #fffafa;
}

.score-bar {
  width: 86px;
  height: 6px;
  margin-top: 7px;
  overflow: hidden;
  border-radius: 99px;
  background: #edf0f5;
}

.score-fill {
  height: 100%;
  border-radius: inherit;
  background: #d71920;
}

.change-badge {
  width: fit-content;
  padding: 5px 10px;
  border-radius: 9px;
  font-weight: 900;
}

.price-up {
  background: #fff0f0;
  color: #d71920;
}

.price-down {
  background: #eefaf2;
  color: #138a43;
}

.price-flat {
  background: #f2f4f8;
  color: #707988;
}

.empty-state {
  padding: 24px 0;
  color: #8a93a3;
  text-align: center;
}

.table-empty {
  min-width: 760px;
}

@media (max-width: 1100px) {
  .desktop-shell {
    grid-template-columns: 1fr;
  }

  .sidebar {
    position: relative;
    height: auto;
    padding: 14px;
    border-right: 0;
    border-bottom: 1px solid #e9edf3;
  }

  .nav {
    grid-template-columns: repeat(5, minmax(0, 1fr));
  }

  .topbar {
    grid-template-columns: 1fr;
  }

  .top-actions {
    justify-content: flex-start;
  }

  .metric-grid,
  .content-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .main {
    padding: 14px;
  }

  .topbar {
    margin: -14px -14px 14px;
  }

  .nav {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .metric-grid,
  .content-grid {
    grid-template-columns: 1fr;
  }

  .hero {
    padding: 22px;
  }

  .hero-title {
    font-size: 24px;
  }
}
</style>
