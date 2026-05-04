/**
 * ECharts 图表配置构建函数
 * 用于分时图、K线图、筹码分布、资金流向
 */

const COLOR_UP = '#e94560'
const COLOR_DOWN = '#0be881'
const COLOR_BG = '#1a1a2e'
const COLOR_TEXT = '#888888'
const COLOR_GRID = 'rgba(255,255,255,0.05)'
const COLOR_MA5 = '#f39c12'
const COLOR_MA10 = '#3498db'
const COLOR_MA20 = '#e94560'

/**
 * 分时图配置
 */
export function buildMinuteChartOption(minutes) {
  if (!minutes || minutes.length === 0) return {}

  const times = minutes.map(m => m.time)
  const prices = minutes.map(m => m.price)
  const avgPrices = minutes.map(m => m.avg_price)
  const volumes = minutes.map(m => m.volume)
  const firstPrice = prices[0]

  return {
    backgroundColor: COLOR_BG,
    animation: false,
    grid: [
      { left: 50, right: 20, top: 10, height: '60%' },
      { left: 50, right: 20, top: '75%', height: '20%' }
    ],
    xAxis: [
      {
        type: 'category',
        data: times,
        gridIndex: 0,
        axisLine: { lineStyle: { color: COLOR_GRID } },
        axisLabel: { color: COLOR_TEXT, fontSize: 10 },
        splitLine: { show: false },
      },
      {
        type: 'category',
        data: times,
        gridIndex: 1,
        axisLine: { lineStyle: { color: COLOR_GRID } },
        axisLabel: { show: false },
        splitLine: { show: false },
      }
    ],
    yAxis: [
      {
        type: 'value',
        gridIndex: 0,
        axisLine: { lineStyle: { color: COLOR_GRID } },
        axisLabel: { color: COLOR_TEXT, fontSize: 10 },
        splitLine: { lineStyle: { color: COLOR_GRID } },
        scale: true,
      },
      {
        type: 'value',
        gridIndex: 1,
        axisLine: { lineStyle: { color: COLOR_GRID } },
        axisLabel: { show: false },
        splitLine: { show: false },
      }
    ],
    series: [
      {
        name: '价格',
        type: 'line',
        data: prices,
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'none',
        lineStyle: { color: COLOR_UP, width: 1.5 },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(233,69,96,0.3)' },
              { offset: 1, color: 'rgba(233,69,96,0)' }
            ]
          }
        },
      },
      {
        name: '均价',
        type: 'line',
        data: avgPrices,
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'none',
        lineStyle: { color: COLOR_MA5, width: 1, type: 'dashed' },
      },
      {
        name: '成交量',
        type: 'bar',
        data: volumes,
        xAxisIndex: 1,
        yAxisIndex: 1,
        itemStyle: {
          color: (params) => {
            return prices[params.dataIndex] >= firstPrice ? COLOR_UP : COLOR_DOWN
          }
        },
      }
    ]
  }
}

/**
 * K线图配置
 */
export function buildKlineChartOption(klines) {
  if (!klines || klines.length === 0) return {}

  const dates = klines.map(k => k.date)
  const ohlc = klines.map(k => [k.open, k.close, k.low, k.high])
  const volumes = klines.map((k, i) => ({
    value: k.volume,
    itemStyle: { color: k.close >= k.open ? COLOR_UP : COLOR_DOWN }
  }))

  // 计算MA
  const ma5 = calcMA(klines, 5)
  const ma10 = calcMA(klines, 10)
  const ma20 = calcMA(klines, 20)

  return {
    backgroundColor: COLOR_BG,
    animation: false,
    grid: [
      { left: 50, right: 20, top: 10, height: '55%' },
      { left: 50, right: 20, top: '72%', height: '22%' }
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        gridIndex: 0,
        axisLine: { lineStyle: { color: COLOR_GRID } },
        axisLabel: { color: COLOR_TEXT, fontSize: 10 },
        splitLine: { show: false },
      },
      {
        type: 'category',
        data: dates,
        gridIndex: 1,
        axisLine: { lineStyle: { color: COLOR_GRID } },
        axisLabel: { show: false },
        splitLine: { show: false },
      }
    ],
    yAxis: [
      {
        type: 'value',
        gridIndex: 0,
        axisLine: { lineStyle: { color: COLOR_GRID } },
        axisLabel: { color: COLOR_TEXT, fontSize: 10 },
        splitLine: { lineStyle: { color: COLOR_GRID } },
        scale: true,
      },
      {
        type: 'value',
        gridIndex: 1,
        axisLine: { lineStyle: { color: COLOR_GRID } },
        axisLabel: { show: false },
        splitLine: { show: false },
      }
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: ohlc,
        xAxisIndex: 0,
        yAxisIndex: 0,
        itemStyle: {
          color: COLOR_UP,
          color0: COLOR_DOWN,
          borderColor: COLOR_UP,
          borderColor0: COLOR_DOWN,
        },
      },
      {
        name: 'MA5',
        type: 'line',
        data: ma5,
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'none',
        lineStyle: { color: COLOR_MA5, width: 1 },
      },
      {
        name: 'MA10',
        type: 'line',
        data: ma10,
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'none',
        lineStyle: { color: COLOR_MA10, width: 1 },
      },
      {
        name: 'MA20',
        type: 'line',
        data: ma20,
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'none',
        lineStyle: { color: COLOR_MA20, width: 1 },
      },
      {
        name: '成交量',
        type: 'bar',
        data: volumes,
        xAxisIndex: 1,
        yAxisIndex: 1,
      }
    ]
  }
}

function calcMA(klines, period) {
  const result = []
  for (let i = 0; i < klines.length; i++) {
    if (i < period - 1) {
      result.push('-')
    } else {
      let sum = 0
      for (let j = 0; j < period; j++) {
        sum += klines[i - j].close
      }
      result.push((sum / period).toFixed(2))
    }
  }
  return result
}

/**
 * 筹码分布图配置
 */
export function buildChipChartOption(chipData) {
  if (!chipData || !chipData.bins) return {}

  const { bins, prices, profit_ratio, current_price, avg_cost, price_range } = chipData

  return {
    backgroundColor: COLOR_BG,
    animation: false,
    grid: { left: 60, right: 20, top: 20, bottom: 30 },
    xAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: COLOR_GRID } },
      axisLabel: { color: COLOR_TEXT, fontSize: 10, formatter: '{value}%' },
      splitLine: { lineStyle: { color: COLOR_GRID } },
    },
    yAxis: {
      type: 'category',
      data: prices,
      axisLine: { lineStyle: { color: COLOR_GRID } },
      axisLabel: { color: COLOR_TEXT, fontSize: 10 },
      inverse: true,
    },
    series: [{
      name: '筹码',
      type: 'bar',
      data: bins.map((v, i) => ({
        value: v,
        itemStyle: {
          color: prices[i] <= current_price ? 'rgba(233,69,96,0.7)' : 'rgba(11,232,129,0.7)'
        }
      })),
      barWidth: '60%',
    }],
    graphic: [{
      type: 'text',
      left: 70,
      top: 5,
      style: {
        text: `获利: ${profit_ratio}%  均价: ${avg_cost}`,
        fill: '#fff',
        fontSize: 12,
      }
    }]
  }
}

/**
 * 资金流向图配置
 */
export function buildMoneyFlowChartOption(flows) {
  if (!flows || flows.length === 0) return {}

  const dates = flows.map(f => f.date || '')
  const mainInflow = flows.map(f => f.main_net_inflow || 0)

  return {
    backgroundColor: COLOR_BG,
    animation: false,
    grid: { left: 50, right: 20, top: 20, bottom: 30 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLine: { lineStyle: { color: COLOR_GRID } },
      axisLabel: { color: COLOR_TEXT, fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: COLOR_GRID } },
      axisLabel: { color: COLOR_TEXT, fontSize: 10 },
      splitLine: { lineStyle: { color: COLOR_GRID } },
    },
    series: [{
      name: '主力净流入',
      type: 'bar',
      data: mainInflow.map(v => ({
        value: v,
        itemStyle: { color: v >= 0 ? COLOR_UP : COLOR_DOWN }
      })),
    }]
  }
}
