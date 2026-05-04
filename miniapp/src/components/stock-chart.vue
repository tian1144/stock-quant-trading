<template>
  <view class="chart-wrapper" :style="{ height: heightPx + 'px' }">
    <view :id="chartId" class="chart-container"></view>
  </view>
</template>

<script>
import * as echarts from 'echarts'

export default {
  name: 'StockChart',
  props: {
    chartId: {
      type: String,
      required: true
    },
    option: {
      type: Object,
      default: () => ({})
    },
    height: {
      type: Number,
      default: 500
    }
  },
  data() {
    return {
      chart: null
    }
  },
  computed: {
    heightPx() {
      // rpx转px (750rpx = 屏幕宽度)
      const systemInfo = uni.getSystemInfoSync()
      return (this.height / 750) * systemInfo.windowWidth
    }
  },
  watch: {
    option: {
      handler(newOption) {
        if (this.chart && newOption && Object.keys(newOption).length > 0) {
          this.chart.setOption(newOption, true)
        }
      },
      deep: true
    }
  },
  mounted() {
    this.$nextTick(() => {
      setTimeout(() => {
        this.initChart()
      }, 100)
    })
    window.addEventListener('resize', this.handleResize)
  },
  beforeUnmount() {
    if (this.chart) {
      this.chart.dispose()
      this.chart = null
    }
    window.removeEventListener('resize', this.handleResize)
  },
  methods: {
    initChart() {
      const dom = document.getElementById(this.chartId)
      if (dom) {
        this.chart = echarts.init(dom)
        if (this.option && Object.keys(this.option).length > 0) {
          this.chart.setOption(this.option, true)
        }
      }
    },
    handleResize() {
      if (this.chart) {
        this.chart.resize()
      }
    }
  }
}
</script>

<style scoped>
.chart-wrapper {
  width: 100%;
}

.chart-container {
  width: 100%;
  height: 100%;
}
</style>
