<script>
export default {
  onLaunch() {
    console.log('App Launch')
  },
  onShow() {
    console.log('App Show')
  },
  onHide() {
    console.log('App Hide')
  }
}
</script>

<style>
/* 全局主题变量 */
:root {
  --bg-primary: #f6f7fb;
  --bg-card: #ffffff;
  --bg-header: #d71920;
  --color-up: #d71920;
  --color-down: #138a43;
  --color-accent: #d71920;
  --text-primary: #151922;
  --text-secondary: #666f7f;
  --text-muted: #9aa3b2;
  --border-light: #edf0f5;
  --shadow-card: 0 8rpx 24rpx rgba(15, 23, 42, 0.06);
}

/* 全局样式 */
page {
  background-color: var(--bg-primary);
  color: var(--text-primary);
  font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', 'Segoe UI', Roboto, sans-serif;
  font-size: 28rpx;
  line-height: 1.5;
}

/* 全局滚动条隐藏（H5） */
::-webkit-scrollbar {
  display: none;
}

/* 全局点击高亮去除 */
view, text {
  -webkit-tap-highlight-color: transparent;
}

/* 安全区域适配 */
.safe-area-bottom {
  padding-bottom: env(safe-area-inset-bottom);
}
</style>
