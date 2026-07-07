# A股恐惧贪婪指数 AFGI

这是一个可部署到 GitHub Actions 的 A 股市场情绪分析系统 1.0 版本。它会在每天收盘后自动抓取免费数据，进行多源校验，计算 0-100 的恐惧贪婪指数，并通过微信推送给客户。

## 指数分档

| 分数 | 状态 | 仓位建议 |
|---:|---|---|
| 0-10 | 极度恐惧 | 0%-20% |
| 10-30 | 恐惧 | 20%-40% |
| 30-70 | 中立 | 40%-60% |
| 70-90 | 贪婪 | 60%-80% |
| 90-100 | 极度贪婪 | 50%-65%，避免追高 |

## 1.0 指标结构

| 模块 | 权重 | 当前数据策略 |
|---|---:|---|
| 沪深300趋势 | 20% | 东方财富历史行情 + 多源指数现价校验 |
| 市场宽度 | 18% | 东方财富全 A 快照，单源时降权提示 |
| 成交与流动性 | 15% | 沪深300成交额相对近30日均值 |
| 机构态度 | 20% | 宽基ETF + IF股指期货，缺源时降权 |
| 风险波动 | 12% | 沪深300近20日波动率 |
| 板块强弱/情绪地图 | 15% | 东方财富行业板块排名，单源时降权提示 |

系统会在数据不足时主动提示：

- `OK`：至少两个来源可用，误差在阈值内。
- `WARN`：只有一个来源，指数可计算但降低权重。
- `CONFLICT`：多个来源差异过大，该指标不参与计算。
- `MISSING`：无法获取数据，该指标不参与计算。

如果可用总权重低于 70%，当天报告会标记为“试算”。

## 微信推送方式

默认支持三种免费/低门槛通道，任选其一即可：

1. 企业微信机器人：适合推送到客户服务群。
2. WxPusher：适合按 UID 推送给关注用户。
3. Server酱：适合通过微信服务通知推送。

在 GitHub 仓库中进入 `Settings -> Secrets and variables -> Actions`，按需添加：

| Secret | 说明 |
|---|---|
| `WECHAT_WEBHOOK_URL` | 企业微信机器人 Webhook 地址 |
| `WXPUSHER_APP_TOKEN` | WxPusher 应用 token |
| `WXPUSHER_UIDS` | WxPusher 用户 UID，多个用英文逗号分隔 |
| `SERVERCHAN_SENDKEY` | Server酱 SendKey |

如果没有配置任何微信密钥，程序只会生成报告，不会发送。

## GitHub Actions 自动运行

工作流文件在 `.github/workflows/daily-afgi.yml`。

默认时间：

```yaml
cron: "45 8 * * 1-5"
```

GitHub Actions 使用 UTC 时间，`08:45 UTC` 对应北京时间 `16:45`，已经在 A 股收盘后。工作流也支持手动运行：

`Actions -> Daily AFGI Report -> Run workflow`

## 本地运行

安装依赖：

```bash
pip install -r requirements.txt
```

只生成报告，不发送微信：

```bash
AFGI_DRY_RUN=true python -m afgi.main
```

生成结果会写入：

```text
reports/latest.md
reports/YYYY-MM-DD.md
reports/YYYY-MM-DD.json
```

## 重要说明

1. 1.0 版本使用免费公开数据，数据源可能临时变更或限流。
2. 系统会对异常、缺失、单源、冲突数据进行提示和降权。
3. 当前模型适合做市场情绪观察和研究，不构成投资建议。
4. 微信推送到客户前，建议先用 `workflow_dispatch` 手动跑几天，观察报告稳定性。
