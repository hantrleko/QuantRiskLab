# QuantRiskLab V0.3.1 Release Candidate 验收

日期：2026-10-17。没有推送 GitHub，没有部署 Railway，没有改写 Git 历史。已经核对过的尾部、lift、相似聚类和 CFTC 顺延公式没有改写。

版本号：界面与 `quantrisklab.__version__` 为 0.3.1 Release Candidate。公开数据库再分发许可仍未确认，所以这不是对外发布版本。

## 修复前后截图

修复前在 `F:\projects\QuantRiskLab\audit-screenshots\`。修复后在 `F:\projects\QuantRiskLab\audit-screenshots-v031\`。

| 修复后 | 内容 |
| --- | --- |
| `audit-screenshots-v031\desktop-overview.png` | 1440px 风险总览，含快照号 |
| `audit-screenshots-v031\desktop-pit.png` | 1440px 历史时点 |
| `audit-screenshots-v031\desktop-research.png` | 1440px 风险研究 |
| `audit-screenshots-v031\desktop-audit.png` | 1440px 数据审计 |
| `audit-screenshots-v031\mobile-overview.png` | 390px 风险总览 |
| `audit-screenshots-v031\mobile-pit.png` | 390px 历史时点 |
| `audit-screenshots-v031\mobile-research.png` | 390px 风险研究 |
| `audit-screenshots-v031\mobile-audit.png` | 390px 数据审计 |
| `audit-screenshots-v031\desktop-empty-2000.png` | 2000-01-01 无数据 |
| `audit-screenshots-v031\desktop-asof-2012.png` | 2012-01-03 |

## 日期切换

请求序号只接受最后一次查询。开始新查询时先清空图表，加载、成功、无数据、失败四态互斥。结果提交后写入 `data-committed`，并丢掉结束日晚于 as_of 的片段。

`tests/e2e/date-switch.cjs` 连续切换 2026-10-17、2012-01-03、2020-03-23、2000-01-01，再回到 2012 和 2026。每次都等到 `data-committed` 等于所选日期。可见结果里没有更晚的日期。2000-01-01 显示「截至 2000-01-01 没有可见观测」。该脚本通过。

空历史不再让结构接口 500。没有利率样本时，方差分段返回「没有足够的利率变动」，不改变有数据时的滚动方差规则。

## 时点展示

页眉显示查询日期、数据库覆盖终点、快照 `20261013T110018Z` 和生成时间 `2026-10-13T11:00:18+00:00`。

审计表把新鲜度和可得性分开。DFF 写明「日期近似，不是精确公布时刻」，并保留纽约联储下一营业日上午约 9:00 的说明。没有把 `available_at_utc` 填成精确时刻。

历史时点页列出 CPI、DFF、DGS10 和 CFTC 的可得性规则。CPI 图仍比较查询日可见修订和今天的最新修订，后者有文字标明。

## 界面

柱状图纵轴改为 `containLabel`，图例改到图下方，并提供「重置缩放」。1440px 总览能看到完整的收益率变动轴标题。

390px 审计表放在横向滚动区域里，最小宽度 920px。截图只显示视口内的左半部分，其余列需要横向滑动，不再把所有列挤进 390px。

错误态不再和「正在按…重新计算」同时出现。

## 非正价格测试

`test_window_containing_negative_wti_does_not_compound` 使用 18.27、-36.98、8.0。窗口状态是 `not_computable`，复合收益是 null。这只锁住已有规则，没有改计算方法。

## 测试与构建

`pytest`：23 项通过，1 条 Starlette/`httpx` 弃用警告。其中包含原先 8 项集成测试和新增的负价格窗口测试。

`tests/e2e/date-switch.cjs`：通过。运行时使用本机已安装的 Playwright，不在仓库里新增 `node_modules`。

`npx tsc --noEmit`：通过。

`npm run build`：通过。产物 `frontend/dist/assets/index-bSJKZyQW.js`（1,287.93 kB，gzip 423.08 kB）和 `index-CNq5--po.css`。Vite 提示单个 JS 块超过 500 kB，不影响这次构建成功。

## 仍阻塞公开部署

`data/quantrisklab.duckdb` 仍在公开 Git 历史里。FRED 与标普 500 的再分发许可没有新的结论。未经批准，不删除该文件，不改写历史，不更新 Railway。