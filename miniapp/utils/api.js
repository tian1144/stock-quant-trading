// API 请求封装
// 后端服务地址配置
// 本地开发：使用 http://localhost:8000
// 远程访问：使用 http://你的IP:8000（如 http://192.168.1.100:8000）
// H5模式下会自动使用代理，无需修改此地址
const getBaseUrl = () => {
  // H5模式下使用相对路径（通过vite代理）
  // #ifdef H5
  return ''
  // #endif
  
  // 非H5模式（小程序等）需要完整地址
  // #ifndef H5
  return 'http://localhost:8000'
  // #endif
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