# 架构

QuantRiskLab V0.2 是一个本地研究工作台：下载少量可复核的公开数据，把发布日和观测日分开保存，再用只读接口喂给深色研究界面。V0.2 在已有缓存上增加利率变动的跨资产结构，不新增虚构序列。

## 模块

- `catalog.py`：要下载的 FRED 槽位、ALFRED 序列和 CFTC 市场。利率槽位标记为不能做价格指标。
- `sources/fred.py`：FRED 最新观测。公开 URL 不含密钥。
- `sources/alfred.py`：把 FRED observations 的实时窗口交给 ALFRED 模式，`release_date` 使用每条记录的 `realtime_start`。
- `sources/cftc.py`：解析 COT 压缩包。观测日来自文件，公布日按文档化日历规则计算。
- `sources/bis.py`：BIS SDMX 契约。`fetch_series` 会拒绝下载。
- `store/pit.py`：`as_of` 过滤。条件是 `release_date <= as_of` 且 `observation_date <= as_of`，再对每个观测日保留最新发布版。
- `store/database.py`：DuckDB 表 `observations`、`series_meta`、`cftc_positions`、`manifest`。manifest 同时写成 `data/manifest.json`，与原始文件和 parquet 分开。
- `quality/checks.py`：可见样本的缺失、长缺口、重复 vintage 键和修订月数。
- `metrics/risk.py`：价格简单收益、实现波动率、最大回撤、历史模拟 VaR / Expected Shortfall，以及差分相关。Statsmodels 的 Ljung-Box 只作为收益自相关的描述统计。
- `metrics/structure.py`：利率快速变动片段、下尾共现、相关网络、相似历史状态、滚动方差高波动段，以及预设危机窗口。输入必须已经过 `as_of` 过滤。两状态 Markov MLE 没有放进交互请求，因为在本机上不能按时返回。
- `api/app.py`：127.0.0.1:8876。健康检查、目录、质量、序列、指标、相关、热力图、持仓、描述性回归和 `/api/structure`。前端通过 Vite 把 `/api` 代理到这个端口。
- `frontend`：React、TypeScript、ECharts。图表只读上述接口。

## 时点

宏观修订序列可能在观测月之后多次改写。库里保留多行：同一 `observation_date` 配不同 `release_date`。查询不会把下载日的最新值填回过去。

CFTC 文件里的日期是持仓截止日。公布通常在同周周五；若周三到周五遇美国联邦假日，则顺延到下一营业日。因此观测日当天的查询结果不包含本期仓位。

非修订的市场价格和利率没有逐期 vintage。它们的 `release_date` 等于观测日。这避免把 FRED 查询窗口误当成每一期的发布时间，也避免在历史 `as_of` 中看到未来日期。它不重建“下一交易日早晨才发表”的发布滞后。

## 指标边界

只有 `price_metrics` 为真的序列进入收益、波动率、回撤、VaR 和 Expected Shortfall。VaR 使用收益的经验分位数；Expected Shortfall 是该分位数及以下收益的平均。损失口径取相反数，只为了在图上把亏损画成正值。

收益率差分相关和 ΔDGS10 对 ΔDGS2 的 OLS 是样本内描述，不是因果，也不是预测。

## 复现

`scripts/reproduce_v0.py` 下载或覆盖原始响应，重建 DuckDB 和 parquet，核对 SHA256，确认 CFTC 公布日晚于观测日，扫描密钥泄漏，写出 `DATA_SOURCES.md`、`data/results/v0_summary.json` 和测试摘录。摘录来自真实响应，文件头或旁路 JSON 记录来源 URL 和访问日期。

## 明确不做

V0.1 没有回测引擎。没有可交易全收益、费用、展期和成交模型时，任何策略净值都是假的。BIS 全量 SDMX 也不在本版范围内。
