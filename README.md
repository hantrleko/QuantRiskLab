# QuantRiskLab V0.2

时点宏观与风险研究工作台。它读取真实的公开数据，在给定日期 `as_of` 上只展示当时已经发布的观测，并计算少量可复核的风险描述统计。

本平台不提供买卖建议，也不报告策略收益。

## 环境

- Python 3.12，用 uv 安装依赖
- 前端需要本机的 npm
- 接口端口 8876，前端开发端口 5280。本机 8765 和 5173 常被其他程序占用。开发服务器把 `/api` 代理到 8876。

设置密钥时只使用环境变量名 `FRED_API_KEY`。不要把密钥写进仓库、命令历史文档或日志。

已有缓存时不要重跑整条下载。用下面这条只读缓存建库；它不会从 DGS2 重新请求 FRED。

```powershell
cd F:\projects\QuantRiskLab
uv run python scripts/build_cached_v0.py
```

`scripts/build_cached_v0.py` 只读取已经保存在 `data/raw` 的文件，不会重新请求 FRED。WTI、标普 500、公司债 OAS 和 CPI vintage 若已有本地文件，会在这次建库时入库。黄金上午定盘价、黄金下午定盘价和 UNRATE vintage 仍是缺口，不要为了补齐而反复重跑。

如果没有设置环境变量，程序会从 `F:\AI\API` 里文件名包含 fred 的本地文件读取一次，并只注入当前进程的 `FRED_API_KEY`。密钥不会打印，也不会写入代码或 manifest。

## 启动

```powershell
uv run uvicorn quantrisklab.api.app:app --host 127.0.0.1 --port 8876
```

另一个终端：

```powershell
cd F:\projects\QuantRiskLab\frontend
npm install
npm run dev
```

浏览器打开 `http://127.0.0.1:5280`。测试：

```powershell
uv run pytest
```

测试可能打印 Starlette 的提示：`httpx` 配合 `TestClient` 已弃用，建议改用 `httpx2`。这不改变接口结果，V0.1 不为此更换测试客户端。DuckDB 查询已使用 `to_arrow_table()`。

## V0.2 能回答什么

- 在某个 `as_of`，当时已发布的国债收益率、利差、VIX、价格和 CFTC 净持仓是多少。
- 失业率或 CPI 的已发布 vintage 之间有没有修订；更晚的修订不会出现在更早的 `as_of`。
- 真实价格序列的简单收益、实现波动率、最大回撤、历史模拟 VaR 和 Expected Shortfall。
- 选定窗口内，价格收益或利率差分如何相关。
- 10 年期收益率在 63 个观测内变动达到 0.50 个百分点的独立片段有多少次，这些窗口里标普 500、WTI 和 VIX 怎么变。
- 当前利率变动、VIX 和价格风险特征与多少段不重叠的历史状态接近。
- 预先指定的 2013、2017、2020 和 2022 窗口在所选 `as_of` 之前是否已经发生；没有发生的窗口不会出现。
- 原始文件的 URL、访问日期、SHA256、单位、频率和缺失情况。具体序列见 `DATA_SOURCES.md`。

## V0.2 不能回答什么

- 不能给出买卖建议，也不能给出目标仓位。
- 不能做诚实的策略回测。现货和价格指数不是可交易全收益，没有费用、滑点、期货展期和成交约束。因此这里没有净值曲线。
- 不能把利率或利差水平当成资产价格。页面上的收益率图是水平值。
- 不能把 CFTC 的周二观测日当成当天已经公开的仓位。
- 不能把非 ALFRED 的 FRED 序列当成完整修订史。它们的 `release_date` 被设为观测日，只表示“这一天的价格或利率已经形成”，不表示 FRED 数据库的入库时间。
- 不包含 BIS SDMX 批量数据。接口契约在 `DATA_SOURCES.md`。
- 样本从各序列配置的起点开始，不是各官方序列的全部历史。
- 不能把滚动方差分段当成 Markov switching。两状态 MLE 在本机交互时限内没有返回，页面上的高方差段只是 12 周滚动方差相对中位数。

## 部署

公开站点由 FastAPI 同时提供接口和已构建的前端。数据库快照 `data/quantrisklab.duckdb` 随仓库发布，里面是已经下载的公开序列，不含密钥。原始下载和 parquet 不入库。

Railway 使用仓库根目录的 `Dockerfile`。平台注入 `PORT` 后，进程监听 `0.0.0.0:$PORT`。

## 布局

后端在 `src/quantrisklab`。原始下载在 `data/raw`，parquet 在 `data/parquet`，DuckDB 在 `data/quantrisklab.duckdb`，来源清单在 `data/manifest.json`。这些缓存和密钥文件已写入 `.gitignore`。
