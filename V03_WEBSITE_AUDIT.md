# QuantRiskLab V0.3 只读验收

日期：2026-10-17。范围是本机 `http://127.0.0.1:5280/` 与 `http://127.0.0.1:8876/`。没有改程序，没有提交，没有部署。

线上 `https://quantrisklab-production.up.railway.app` 仍是部署时的版本，本次没有打开它做视觉验收。

## 截图

Playwright 1.64.1，Chromium headless。桌面 1440×900，移动 390×844，整页截图。

| 文件 | 内容 |
| --- | --- |
| `F:\projects\QuantRiskLab\audit-screenshots\desktop-overview.png` | 桌面风险总览 |
| `F:\projects\QuantRiskLab\audit-screenshots\desktop-pit.png` | 桌面历史时点 |
| `F:\projects\QuantRiskLab\audit-screenshots\desktop-research.png` | 桌面风险研究 |
| `F:\projects\QuantRiskLab\audit-screenshots\desktop-audit.png` | 桌面数据审计 |
| `F:\projects\QuantRiskLab\audit-screenshots\mobile-overview.png` | 移动风险总览 |
| `F:\projects\QuantRiskLab\audit-screenshots\mobile-pit.png` | 移动历史时点 |
| `F:\projects\QuantRiskLab\audit-screenshots\mobile-research.png` | 移动风险研究 |
| `F:\projects\QuantRiskLab\audit-screenshots\mobile-audit.png` | 移动数据审计 |
| `F:\projects\QuantRiskLab\audit-screenshots\desktop-tooltip.png` | 图例点击后的柱状图 |
| `F:\projects\QuantRiskLab\audit-screenshots\desktop-zoom.png` | 滚轮之后的视口 |
| `F:\projects\QuantRiskLab\audit-screenshots\desktop-legend.png` | 图例交互 |
| `F:\projects\QuantRiskLab\audit-screenshots\desktop-asof-2012.png` | 日期改为 2012-01-03 后的整页 |
| `F:\projects\QuantRiskLab\audit-screenshots\desktop-asof-2020.png` | 日期改为 2020-03-23 后的整页 |
| `F:\projects\QuantRiskLab\audit-screenshots\desktop-empty-2000.png` | 日期改为 2000-01-01 |
| `F:\projects\QuantRiskLab\audit-screenshots\desktop-error-structure.png` | 拦截结构接口为 500 |
| `F:\projects\QuantRiskLab\audit-screenshots\playwright-log.json` | 控制台与网络记录 |

主流程的控制台错误、失败请求、HTTP 4xx/5xx 都是 0。500 只出现在故意拦截的错误用例里。

## 页面验收

四个导航都能点开，页签高亮正确。

风险总览有利率条形图、利率与信用利差、VIX、价格相关和 VaR。历史时点几乎只有 CPI 修订图，没有把 `/api/availability` 的质量等级画出来。风险研究包含网络、尾部、危机对照、热力图、滚动相关和 CFTC。数据审计有质量表和三条下载失败记录。

日期框能改，页脚 `as_of` 会立刻跟着变。改到 2012-01-03 后约 3 秒，可见正文里仍然有 `2026-09-28`。改到 2000-01-01 后，正文长度与 2026-10-13 完全相同（都是 1958）。接口本身不会返回截止日期之后的片段。因此这是界面刷新滞后或空结果没有清掉旧图，不是数据库把未来数据算了进去。

错误提示有效。结构接口被拦截为 500 时，页面出现红色条文：`风险结构没有算出来：500 {"detail":"audit forced failure"}`。同一屏仍留着「等待后端计算」和「还没有结构结果」，加载态和错误态叠在一起。

悬浮提示和图例能点。点「窗口变动」并滚轮之后，柱状图收成一根，纵轴标题被裁成「年收益率变动」。没有单独的加载骨架。2000-01-01 没有变成明确的空数据说明。

## 统计核查

用 DuckDB 按 `release_date <= as_of` 且 `observation_date <= as_of` 独立重算，再对接口。

截至 2026-10-17，标普 500 与 WTI 重叠收益 2491 个，联合下尾 22 个。独立计算 coexceedance 0.17663588920112402，lift 3.507328。接口数字相同。

截至 2020-03-23，n=858，联合下尾 9 个，coexceedance 0.2097902097902098，lift 4.176311519740399。接口数字相同。

截至 2012-01-03，两边都没有标普与 WTI 的重叠收益，接口 coexceedance 和 lift 为空。相似片段 0。危机窗口列表为空，因为 2013 年缩减讨论还没开始。没有任何片段的结束日晚于 as_of。

2026-10-17 的相似代表日是 2025-08-15 和 2026-05-18，共 2 段。网络说明写明不是因果传染，并标出 `T10Y2Y = DGS10 - DGS2`。机械边在 2012 是 `dgs10_change -> curve_change`，在 2020-03-23 还有 `dgs2_change -> curve_change`。

## 时点与负价格

CPI 2015-01-01：as_of 2012-01-03 没有观测；2018-06-01 可见值 234.836；2020-03-23 和 2026-10-17 都是 234.747。修订没有提前出现。

CFTC 抽样 `ust10y` 观测日 2025-01-21、发布日 2025-01-24。观测日当天接口看不到这期仓位，发布日当天看得到 4 个市场。全表发布日都晚于观测日。

WTI 指标：`max_drawdown` 为 null，`max_drawdown_eligible` 为 false。标普 500 最大回撤仍是 -0.3392495902426059。结束于 2020-04-01 的利率片段仍报告 WTI 复合收益 -66.8%，状态是 `simple_compound`。负油价在 2020-04-20，不在这个片段里，现有利率片段也没有一条被标成 `not_computable`。百分比回撤的禁用生效了；「含非正价格则整段不报告复合收益」没有被当前这些片段触发。

## 快照与可得性

`/api/snapshot`：`snapshot_id` 为 `20261013T110018Z`，文件时间 2026-10-13T11:00:18Z。说明写的是建库时的 stale 标记，部署后不会按日历自动刷新。页面上没有展示这个快照号。

`/api/availability`：DFF、DGS2、DGS10、T10Y2Y、CPI、CFTC 的 `release_at_utc` 和 `available_at_utc` 都是 null。DFF 的质量是 `date_approximate`。没有把近似规则写成精确时刻。

数据审计表仍把 DFF 等序列的状态写成「在更新窗口内 / observation_date」。这和可得性接口的「日级近似」不是同一句话，读者会把观测日当成已经公开的时点。

## 视觉

桌面信息密度高，但能读。问题是纵轴标题被裁切，图例压在图上，历史时点页的 CPI 图例和纵轴叠在一起，下面留出大块空白。相关矩阵格子小，标签挤。

390px 上导航折成两行，日期和窗口按钮换行。审计表多列被压窄，长 URL 在格子里断开。图表本身没有为窄屏单独减列。

术语上，收益、百分点、持仓张数大体分得开。页首仍写「本版不做策略回测」，页脚写 V0.3，两处口径不一致。热力图里 10 年减 2 年几乎是一条平带，容易看成一种独立风险，页面没有在这张图旁边重复会计恒等式说明。

## 测试

集成测试 8 项全部通过，用时 216 秒，没有环境失败：

- `test_manifest.py` 2 项
- `test_missing.py` 1 项
- `test_pit.py` 3 项
- `test_risk_metrics.py` 1 项
- `test_secrets.py` 1 项

同一次收集里另有 14 项非集成测试被排除，本次没有重跑。没有执行新的生产构建。

主路径没有控制台错误。结构接口在正常日期下返回 200。故意的 500 能显示出来。

## 问题

P0：这次只读验收没有发现新的计算错误。尾部、时点过滤和 CFTC 发布日滞后与数据库一致。

P1：

- 日期改到 2012 或 2000 后，页脚先变，图表和片段列表会短暂或持续留下上一次的结果。
- 数据审计表把 `observation_date` 显示成当前状态，没有展示 `date_approximate`，近似发布被读成当天已经公开。
- 历史时点页只有一张 CPI 图，图例与坐标轴重叠。
- 移动端审计表不可读。
- 含 2020-04-20 负价格的窗口没有出现在利率片段里，复合收益禁用分支没有在界面上被走到。

P2：

- 柱状图纵轴标题裁切，图例遮挡。
- 图例点击加滚轮后，图会收成单柱，缺少重置提示。
- 错误出现时仍保留「等待后端计算」。
- 快照号和文件时间没有上屏。
- 页首「本版」和页脚 V0.3 不一致。

## 上线前必须做的修改

这些还没做，本次也没有部署。

1. 日期切换后先清空或标出「正在按新的 as_of 重算」，空结果不能留着上一次的图。
2. 审计页展示 `availability_quality`，不要把日级近似写成观测日即公开。
3. 修正裁切的轴标题、重叠图例，以及 390px 下的表格。
4. 决定公开 DuckDB 快照是否继续分发。历史提交里已经有这个文件，删除或改写历史需要单独授权。
5. 线上站点仍是旧部署。本地 V0.3 通过上述展示问题之前，不要替换生产。