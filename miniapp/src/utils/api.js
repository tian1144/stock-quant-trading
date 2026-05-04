// API 请求封装
// 后端服务地址配置
// 本地开发：使用 http://localhost:8000
// 远程访问：使用 http://你的IP:8000（如 http://192.168.1.100:8000）
// H5模式下会自动使用代理，无需修改此地址
const getBaseUrl = () => {
  // H5环境下使用空字符串（通过vite代理）
  // 非H5环境（小程序等）需要完整地址
  if (typeof window !== 'undefined') {
    return ''
  }
  return 'http://localhost:8000'
}

const BASE_URL = getBaseUrl()

/**
 * 通用请求方法
 * @param {string} url - 请求路径
 * @param {string} method - 请求方法
 * @param {object} data - 请求数据
 * @returns {Promise}
 */
export const request = (url, method = 'GET', data = {}) => {
  return new Promise((resolve, reject) => {
    uni.request({
      url: BASE_URL + url,
      method: method,
      data: data,
      header: {
        'Content-Type': 'application/json'
      },
      success: (res) => {
        if (res.statusCode === 200) {
          resolve(res.data)
        } else {
          reject(res)
        }
      },
      fail: (err) => {
        reject(err)
      }
    })
  })
}

/**
 * 获取股票列表
 * @param {number} limit - 数量限制
 * @param {number} offset - 偏移量
 */
export const getStockList = (limit = 100, offset = 0) => {
  return request(`/api/v1/stocks?limit=${limit}&offset=${offset}`)
}

/**
 * 搜索股票
 * @param {string} keyword - 搜索关键词
 */
export const searchStocks = (keyword) => {
  return request(`/api/v1/stocks/search?keyword=${encodeURIComponent(keyword)}`)
}

/**
 * 获取股票实时行情
 * @param {string} stockCode - 股票代码
 */
export const getStockQuote = (stockCode) => {
  return request(`/api/v1/market/snapshot/${stockCode}`)
}

/**
 * 批量获取股票行情
 * @param {array} stockCodes - 股票代码数组
 */
export const getStockQuotes = (stockCodes) => {
  const codes = stockCodes.join(',')
  return request(`/api/v1/market/snapshots?codes=${codes}`)
}

/**
 * 同步股票列表
 */
export const syncStockList = () => {
  return request('/api/v1/stocks/sync', 'POST')
}

// ==================== 量化交易系统 API ====================

// 选股
export const getScreeningResults = () => request('/api/v1/quant/screening/results')
export const runScreening = () => request('/api/v1/quant/screening/run', 'POST')

// 信号
export const getSignals = () => request('/api/v1/quant/signals')
export const detectSignals = () => request('/api/v1/quant/signals/detect', 'POST')

// 组合
export const getPortfolio = () => request('/api/v1/quant/portfolio')
export const getPositions = () => request('/api/v1/quant/portfolio/positions')
export const getOrders = (limit = 50) => request(`/api/v1/quant/portfolio/orders?limit=${limit}`)
export const getTradeStatistics = () => request('/api/v1/quant/portfolio/statistics')
export const buyStock = (code, price, quantity, reason = '手动买入') => {
  return request('/api/v1/quant/portfolio/buy', 'POST', { code, price, quantity, reason })
}
export const sellStock = (code, price, quantity, reason = '手动卖出') => {
  return request('/api/v1/quant/portfolio/sell', 'POST', { code, price, quantity, reason })
}
export const resetPortfolio = () => request('/api/v1/quant/portfolio/reset', 'POST')

// 系统
export const getSystemStatus = () => request('/api/v1/quant/system/status')
export const toggleAutoTrade = (enabled) => {
  return request('/api/v1/quant/system/auto-trade', 'POST', { enabled })
}

// 新闻
export const getNews = () => request('/api/v1/quant/news')
export const refreshNews = () => request('/api/v1/quant/news/refresh', 'POST')

// 风控
export const getRiskStatus = () => request('/api/v1/quant/risk')
export const getRiskConfig = () => request('/api/v1/quant/risk/config')
export const updateRiskConfig = (updates) => {
  return request('/api/v1/quant/risk/config', 'POST', updates)
}

// ==================== 股票详情 API ====================

export const getStockMinutes = (code) => request(`/api/v1/stocks/${code}/minutes`)
export const getStockKline = (code, period = 101, days = 120) => {
  return request(`/api/v1/stocks/${code}/kline?period=${period}&days=${days}`)
}
export const getStockChips = (code) => request(`/api/v1/stocks/${code}/chips`)
export const getStockDetail = (code) => request(`/api/v1/stocks/${code}/detail`)

// ==================== 板块 API ====================

export const getSectors = () => request('/api/v1/sectors')
export const getSectorDetail = (code) => request(`/api/v1/sectors/${code}`)

// ==================== 交易偏好 API ====================

export const getSettings = () => request('/api/v1/quant/settings')
export const updateSettings = (settings) => {
  return request('/api/v1/quant/settings', 'POST', settings)
}

// ==================== 手册六层闭环 API ====================

export const runBacktest = (code, shortWindow = 5, longWindow = 20, days = 120) => {
  return request('/api/v1/quant/backtest/run', 'POST', {
    code,
    short_window: shortWindow,
    long_window: longWindow,
    days
  })
}
export const getBacktestStrategies = () => request('/api/v1/quant/backtest/strategies')
export const getScoreCard = (code, strategy = 'short') => {
  return request(`/api/v1/quant/score/${code}?strategy=${strategy}`)
}
export const getDecision = (code, strategy = 'short') => {
  return request(`/api/v1/quant/decision/${code}?strategy=${strategy}`)
}
export const runRiskReview = (code, strategy = 'short') => {
  return request(`/api/v1/quant/risk-review/${code}`, 'POST', { strategy })
}
export const getMultiModelVerify = (code) => request(`/api/v1/quant/multi-model/${code}`)
export const scoreNews = (title, content = '', source = '') => {
  return request('/api/v1/quant/news/score', 'POST', { title, content, source })
}
export const getEventScore = (code) => request(`/api/v1/quant/news/event-score/${code}`)
export const getSentimentScore = (code = '') => {
  const query = code ? `?code=${encodeURIComponent(code)}` : ''
  return request(`/api/v1/quant/sentiment${query}`)
}
export const getDailyReport = () => request('/api/v1/quant/report/daily')
export const getPaperTradeLog = () => request('/api/v1/quant/report/paper-trade')
export const activateKillSwitch = (reason = '手动触发') => {
  return request('/api/v1/quant/kill-switch/activate', 'POST', { reason })
}
export const deactivateKillSwitch = () => request('/api/v1/quant/kill-switch/deactivate', 'POST')
export const getKillSwitchStatus = () => request('/api/v1/quant/kill-switch/status')
