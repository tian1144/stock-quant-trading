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
          :class="{ active: item.key === 'news' }"
          @click="goPage(item)"
        >
          <text class="nav-cn">{{ item.label }}</text>
          <text class="nav-en">{{ item.meta }}</text>
        </view>
      </view>
    </view>

    <view class="main">
      <view class="topbar">
        <view class="page-title">
          <text class="title">新闻监控</text>
          <text class="subtitle">财联社 / 新浪财经事件流，服务于情绪评分、风险暂停和个股研究。</text>
        </view>
        <view class="actions">
          <view class="status-pill" :class="{ warn: serviceWarn }">
            <text class="status-dot"></text>
            <text>{{ serviceWarn ? '新闻源异常' : '监听中' }}</text>
          </view>
          <view class="btn" @click="loadNews">刷新缓存</view>
          <view class="btn primary" :class="{ disabled: loading }" @click="onRefreshNews">
            {{ loading ? '捕获中' : '立即捕获新闻' }}
          </view>
        </view>
      </view>

      <view class="hero">
        <text class="hero-title">随时捕获新闻 / 公告 / 宏观事件</text>
        <text class="hero-copy">
          新闻板块负责把外部事件变成可评分信号：识别正负面情绪、重大冲击、风险暂停和相关标的，再进入选股、研究与风控链路。
        </text>
        <view class="hero-tags">
          <text>事件分级</text>
          <text>情绪粗评</text>
          <text>风险暂停</text>
          <text>关联个股</text>
        </view>
      </view>

      <view class="metric-grid">
        <view class="metric-card">
          <text class="metric-label">事件流</text>
          <text class="metric-value">{{ newsList.length }}</text>
          <text class="metric-sub">最近 50 条</text>
        </view>
        <view class="metric-card">
          <text class="metric-label">正面新闻</text>
          <text class="metric-value red">{{ sentiment.positive_news || 0 }}</text>
          <text class="metric-sub">关键词粗筛</text>
        </view>
        <view class="metric-card">
          <text class="metric-label">负面新闻</text>
          <text class="metric-value green">{{ sentiment.negative_news || 0 }}</text>
          <text class="metric-sub">风险排雷</text>
        </view>
        <view class="metric-card">
          <text class="metric-label">市场情绪</text>
          <text class="metric-value tone">{{ sentiment.level || 'neutral' }}</text>
          <text class="metric-sub">评分 {{ formatScore(sentiment.score) }}</text>
        </view>
      </view>

      <view class="content-grid">
        <view class="panel">
          <view class="panel-title">
            <view>
              <text>高优先级事件</text>
              <text class="panel-sub">优先查看可能影响交易暂停或仓位控制的新闻</text>
            </view>
          </view>
          <view class="event-list">
            <view v-for="item in highPriorityNews" :key="item.id || item.title" class="event-card">
              <view class="event-title-row">
                <text class="event-title">{{ item.title || '--' }}</text>
                <text class="badge red">{{ impactLabel(item) }}</text>
              </view>
              <text class="event-meta">{{ item.source || '新闻源' }} · {{ item.time || '--' }}</text>
            </view>
            <view class="empty-state" v-if="!loading && highPriorityNews.length === 0">
              暂无高优先级事件。
            </view>
          </view>
        </view>

        <view class="panel">
          <view class="panel-title">
            <view>
              <text>捕获策略</text>
              <text class="panel-sub">新闻进入交易链路前先做可信度与风险判断</text>
            </view>
          </view>
          <view class="status-table">
            <view class="status-row">
              <text>刷新节奏</text>
              <text>后端每 15 分钟调度，前端可手动捕获</text>
            </view>
            <view class="status-row">
              <text>风险词</text>
              <text>减持 / 处罚 / 诉讼 / 暴跌 / 亏损 / 监管</text>
            </view>
            <view class="status-row">
              <text>机会词</text>
              <text>中标 / 回购 / 增持 / 订单 / 业绩 / 合作</text>
            </view>
            <view class="status-row">
              <text>下游使用</text>
              <text>情绪评分、事件评分、风控复核、个股研究</text>
            </view>
          </view>
        </view>
      </view>

      <view class="panel news-panel">
        <view class="panel-title">
          <view>
            <text>实时新闻流</text>
            <text class="panel-sub">点击刷新可重新捕获外部新闻源</text>
          </view>
          <text class="update-text">{{ lastUpdated ? `更新：${lastUpdated}` : '等待新闻刷新' }}</text>
        </view>

        <view class="news-list">
          <view v-for="item in newsList" :key="item.id || item.title" class="news-row">
            <view>
              <text class="news-title">{{ item.title || '--' }}</text>
              <text class="news-meta">{{ item.source || '新闻源' }} · {{ item.time || '--' }}</text>
            </view>
            <view class="news-badges">
              <text class="badge" :class="newsToneClass(item)">{{ newsTone(item) }}</text>
              <text class="badge gray">{{ item.related_symbols ? `${item.related_symbols.length}标的` : '待匹配' }}</text>
            </view>
          </view>
          <view class="empty-state" v-if="!loading && newsList.length === 0">
            暂无新闻。请确认后端服务已启动，或点击“立即捕获新闻”。
          </view>
          <view class="empty-state" v-if="loading">
            正在捕获新闻...
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script>
import { getNews, refreshNews } from '@/utils/api.js'

export default {
  data() {
    return {
      newsList: [],
      sentiment: {},
      loading: false,
      serviceWarn: false,
      lastUpdated: '',
      refreshTimer: null,
      navItems: [
        { key: 'overview', label: '总览', meta: 'Overview', path: '/pages/index/index' },
        { key: 'market', label: '行情', meta: 'Market', path: '/pages/index/index' },
        { key: 'watch', label: '自选', meta: 'Watch', path: '/pages/index/index' },
        { key: 'strategy', label: '策略', meta: 'Strategy', path: '/pages/screening/screening' },
        { key: 'research', label: '研究', meta: 'Report', path: '/pages/stock-detail/stock-detail?code=600519' },
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
    highPriorityNews() {
      return this.newsList.filter(item => this.isRiskNews(item) || this.isOpportunityNews(item)).slice(0, 8)
    }
  },

  onLoad() {
    this.loadNews()
    this.refreshTimer = setInterval(() => this.loadNews(), 60000)
  },

  onUnload() {
    if (this.refreshTimer) clearInterval(this.refreshTimer)
  },

  onPullDownRefresh() {
    this.loadNews().then(() => uni.stopPullDownRefresh())
  },

  methods: {
    async loadNews() {
      try {
        const res = await getNews()
        this.newsList = (res && res.news) || []
        this.sentiment = (res && res.sentiment) || {}
        this.lastUpdated = new Date().toLocaleString()
        this.serviceWarn = false
      } catch (e) {
        this.serviceWarn = true
        console.error('加载新闻失败:', e)
      }
    },

    async onRefreshNews() {
      if (this.loading) return
      this.loading = true
      try {
        const res = await refreshNews()
        this.newsList = (res && res.news) || []
        this.sentiment = (res && res.sentiment) || {}
        this.lastUpdated = new Date().toLocaleString()
        this.serviceWarn = false
        uni.showToast({ title: `捕获${this.newsList.length}条新闻`, icon: 'none' })
      } catch (e) {
        this.serviceWarn = true
        uni.showToast({ title: '新闻捕获失败', icon: 'none' })
      } finally {
        this.loading = false
      }
    },

    goPage(item) {
      if (item.key === 'news') return
      uni.navigateTo({
        url: item.path,
        fail: () => uni.redirectTo({ url: item.path })
      })
    },

    isRiskNews(item) {
      const text = `${item.title || ''} ${item.content || ''}`
      return /减持|处罚|诉讼|暴跌|亏损|监管|调查|退市|风险|熔断/.test(text)
    },

    isOpportunityNews(item) {
      const text = `${item.title || ''} ${item.content || ''}`
      return /中标|回购|增持|订单|业绩|合作|签约|突破|创新高|政策/.test(text)
    },

    newsTone(item) {
      if (this.isRiskNews(item)) return '风险'
      if (this.isOpportunityNews(item)) return '机会'
      return '中性'
    },

    newsToneClass(item) {
      if (this.isRiskNews(item)) return 'red'
      if (this.isOpportunityNews(item)) return 'green'
      return 'gray'
    },

    impactLabel(item) {
      if (this.isRiskNews(item)) return '风险排雷'
      if (this.isOpportunityNews(item)) return '机会事件'
      return '关注'
    },

    formatScore(score) {
      const value = Number(score)
      if (!Number.isFinite(value)) return '--'
      return value.toFixed(1)
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
.title,
.subtitle,
.hero-title,
.hero-copy,
.metric-label,
.metric-value,
.metric-sub,
.panel-sub,
.update-text,
.event-title,
.event-meta,
.news-title,
.news-meta {
  display: block;
}

.brand-title {
  font-size: 18px;
  font-weight: 800;
}

.brand-subtitle,
.subtitle,
.metric-sub,
.panel-sub,
.update-text,
.event-meta,
.news-meta {
  color: #8a93a3;
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
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px;
  margin: -22px -22px 18px;
  background: rgba(245, 246, 250, 0.92);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid rgba(233, 237, 243, 0.8);
}

.title {
  font-size: 20px;
  font-weight: 900;
}

.subtitle {
  margin-top: 4px;
}

.actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

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

.btn.disabled {
  opacity: .58;
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
  max-width: 820px;
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

.metric-grid,
.content-grid {
  display: grid;
  gap: 18px;
  margin-top: 18px;
}

.metric-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.content-grid {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
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

.metric-value.red {
  color: #d71920;
}

.metric-value.green {
  color: #138a43;
}

.metric-value.tone {
  color: #d71920;
  font-family: inherit;
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

.event-list,
.status-table,
.news-list {
  padding: 18px 22px;
}

.event-card,
.news-row,
.status-row {
  border-bottom: 1px dashed #edf0f5;
}

.event-card {
  padding: 12px 0;
}

.event-title-row,
.news-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: center;
}

.event-title,
.news-title {
  color: #151922;
  font-weight: 850;
  line-height: 1.5;
}

.event-meta,
.news-meta {
  margin-top: 5px;
}

.status-row {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr);
  gap: 14px;
  padding: 10px 0;
}

.status-row text:first-child {
  color: #8a93a3;
}

.status-row text:last-child {
  font-weight: 800;
}

.news-panel {
  margin-top: 18px;
}

.news-row {
  min-height: 58px;
  padding: 12px 0;
}

.news-badges {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  flex-wrap: wrap;
}

.badge {
  width: fit-content;
  padding: 5px 10px;
  border-radius: 9px;
  font-size: 12px;
  font-weight: 900;
  white-space: nowrap;
}

.badge.red {
  background: #fff0f0;
  color: #d71920;
}

.badge.green {
  background: #eefaf2;
  color: #138a43;
}

.badge.gray {
  background: #f2f4f8;
  color: #707988;
}

.empty-state {
  padding: 24px 0;
  color: #8a93a3;
  text-align: center;
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

  .topbar,
  .event-title-row,
  .news-row {
    grid-template-columns: 1fr;
    display: grid;
  }

  .actions,
  .news-badges {
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
