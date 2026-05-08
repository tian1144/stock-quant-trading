# 公网访问与自定义域名部署

目标公网地址：

```text
https://www.ljreach.com
```

本项目当前 H5 与 API 都由本机 `http://127.0.0.1:8000` 提供。前端使用相对 API 路径，因此通过公网域名访问后，会自动请求同一域名下的后端接口。

## 推荐方案：Cloudflare Tunnel

这个方案不要求本机有公网 IP，也不要求路由器做端口映射。外部访问链路是：

```text
用户浏览器 -> www.ljreach.com -> Cloudflare Tunnel -> 本机 127.0.0.1:8000
```

## 前置条件

1. 已注册并拥有 `ljreach.com`。
2. 域名 DNS 已接入 Cloudflare。
3. 本机已安装 `cloudflared`。
4. 后端服务能在本机访问：`http://127.0.0.1:8000/api/v1/health`。

如果还没有域名所有权，无法直接启用 `www.ljreach.com`。可以先用临时穿透地址测试，等域名和 DNS 准备好后再绑定正式域名。

## 首次配置步骤

在项目根目录打开 PowerShell，先启动本地 H5：

```powershell
backend\venv\Scripts\python.exe preview_server.py
```

另开一个 PowerShell，登录 Cloudflare：

```powershell
cloudflared tunnel login
```

创建固定隧道：

```powershell
cloudflared tunnel create lianghua-h5
```

把 `deploy\cloudflared\config.yml.example` 复制到：

```text
C:\Users\Administrator\.cloudflared\config.yml
```

然后把其中的 `<TUNNEL_ID>` 替换成 `cloudflared tunnel create` 输出的隧道 ID。

给域名创建 DNS 路由：

```powershell
cloudflared tunnel route dns lianghua-h5 www.ljreach.com
```

启动固定隧道：

```powershell
cloudflared tunnel run lianghua-h5
```

成功后，外部用户访问：

```text
https://www.ljreach.com
```

## 日常启动

配置完成后，可以双击根目录：

```text
启动公网访问.bat
```

这个脚本会启动本地 H5 服务，并运行已配置好的 `lianghua-h5` 隧道。

## 临时测试

如果只是临时让别人访问，但还没有配置域名，可以运行：

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

命令行会输出一个 `trycloudflare.com` 临时地址。这个地址每次可能变化，不等于正式域名。

也可以直接双击项目根目录：

```text
启动临时公网访问.bat
```

它会先启动本地 H5 服务，再创建临时公网地址。把窗口中出现的 `https://*.trycloudflare.com` 发给朋友即可。

如果脚本提示找不到 `cloudflared.exe`，请把下载好的 `cloudflared.exe` 放到以下任意一个位置后再双击脚本：

```text
C:\Users\Administrator\Downloads\cloudflared.exe
C:\Users\Administrator\Desktop\cloudflared.exe
C:\cloudflared\cloudflared.exe
C:\Users\Administrator\Desktop\lianghua1\cloudflared.exe
```

## 安全边界

- 当前系统仍以投研分析和模拟交易为主。
- 真实交易 API 默认关闭，不应通过公网暴露真实下单能力。
- 公网开放后，建议优先增加登录、访问口令、IP 限制或 Cloudflare Access。
- 不要把 `.env`、隧道凭证 JSON、账号 Token 提交到仓库。

## 官方参考

- Cloudflare Tunnel 概览：https://developers.cloudflare.com/tunnel/
- Cloudflare Tunnel 下载：https://developers.cloudflare.com/tunnel/downloads/
- 本地管理 Tunnel：https://developers.cloudflare.com/tunnel/advanced/local-management/create-local-tunnel/
- DNS 路由到 Tunnel：https://developers.cloudflare.com/tunnel/routing/
