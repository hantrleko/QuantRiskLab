# 数据来源

生成日期：2026-10-13。本文件由本地缓存建库重写，本次没有重新请求 FRED。

平台不提供买卖建议。没有真实观测的序列不会用假数据填补。

## 本次入库序列

行数是 as_of 为今天时、点时查询可见的非缺失观测数，不是把全部 vintage 叠在一起的行数。

| 序列 | 名称 | 来源 | 频率 | 可见行数 | 起始 | 结束 | 修订月数 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BAMLC0A0CM | 美国公司债 OAS | fred | Daily, Close | 785 | 2023-10-10 | 2026-10-08 | 0 | 已入库 |
| CPIAUCSL | 美国 CPI（季调） | alfred | Monthly | 139 | 2015-01-01 | 2026-08-01 | 131 | 已入库 |
| DCOILWTICO | WTI 原油现货价格 | fred | Daily | 4150 | 2010-01-04 | 2026-10-06 | 0 | 已入库 |
| DFF | 有效联邦基金利率 | fred | Daily, 7-Day | 6125 | 2010-01-01 | 2026-10-08 | 0 | 已入库 |
| DGS10 | 10年期美国国债收益率 | fred | Daily | 4195 | 2010-01-04 | 2026-10-08 | 0 | 已入库 |
| DGS2 | 2年期美国国债收益率 | fred | Daily | 4195 | 2010-01-04 | 2026-10-08 | 0 | 已入库 |
| SP500 | 标普500价格指数 | fred | Daily, Close | 2512 | 2016-10-13 | 2026-10-12 | 0 | 已入库 |
| T10Y2Y | 10年减2年国债利差 | fred | Daily | 4196 | 2010-01-04 | 2026-10-09 | 0 | 已入库 |
| VIXCLS | VIX 波动率指数 | fred | Daily, Close | 4251 | 2010-01-04 | 2026-10-09 | 0 | 已入库 |
| DFII10 | 10年期美国国债实际收益率 | fred | Daily | 4204 | 2010-01-04 | 2026-10-22 | 0 | 2026-10-25 追加，非空行数 |
| T10YIE | 10年期盈亏平衡通胀率 | fred | Daily | 4205 | 2010-01-04 | 2026-10-23 | 0 | 2026-10-25 追加，非空行数 |
| DTWEXBGS | 广义美元指数 | fred | Daily | 4181 | 2010-01-04 | 2026-10-16 | 0 | 2026-10-25 追加，非空行数。按水平差使用，不计算百分比回撤 |

## 失败与未采用的请求

| 来源 | 序列或文件 | HTTP | URL | 错误 |
| --- | --- | --- | --- | --- |
| fred | GOLDAMGBD228NLBM | 400 | https://api.stlouisfed.org/fred/series/observations?series_id=GOLDAMGBD228NLBM&file_type=json&observation_start=2010-01-01&observation_end=2026-10-13 | Bad Request.  The series does not exist. |
| alfred | UNRATE | 0 | https://api.stlouisfed.org/fred/series | UNRATE HTTP 0: curl: (28) Operation timed out after 90015 milliseconds with 0 bytes received  |
| fred | GOLDPMGBD228NLBM | None | https://api.stlouisfed.org/fred/series?series_id=GOLDPMGBD228NLBM&file_type=json | 没有本地文件。不再重试。 |

### 五次探测的最终状态

早先中断时记下五次失败探测。有完整本地观测的序列已经入库；没有观测文件的保持缺口。这里不重新请求 FRED。

| 序列 | 状态 |
| --- | --- |
| DCOILWTICO | 本地观测文件完整，已入库。2020-04-20 价格为负，仍留在序列中。这一天和下一期不进入简单收益或 VaR。价格比回撤可以低于 -100%。不外推。 |
| SP500 | 本地观测文件完整，已入库。样本从 2016-10-13 起，是价格指数，不含股息。 |
| GOLDAMGBD228NLBM | 缺口。本地响应是 HTTP 400，序列不存在，没有观测文件。不再重试。 |
| GOLDPMGBD228NLBM | 缺口。没有本地文件。不再重试。 |
| UNRATE | 缺口。只有 series 元数据，没有 vintage 观测文件。短请求超时后不再重试。 |


## 槽位决策

```json
{
  "bis": {
    "enabled": false,
    "base_url": "https://stats.bis.org/api/v1",
    "example_dataflow": "WS_CBPOL",
    "note": "央行政策利率数据流。V0.1 只保留入口，不拉取全量 SDMX。"
  },
  "fred": [
    {
      "slot": "dgs2",
      "chosen": "DGS2",
      "attempts": [
        {
          "series_id": "DGS2",
          "ok": true,
          "stale": false,
          "start": "2010-01-04",
          "end": "2026-10-08",
          "rows": 4375,
          "frequency": "Daily",
          "unit": "Percent",
          "url": "https://api.stlouisfed.org/fred/series/observations?series_id=DGS2&file_type=json&observation_start=2010-01-01&observation_end=2026-10-13",
          "resumed": true
        }
      ]
    },
    {
      "slot": "dgs10",
      "chosen": "DGS10",
      "attempts": [
        {
          "series_id": "DGS10",
          "ok": true,
          "stale": false,
          "start": "2010-01-04",
          "end": "2026-10-08",
          "rows": 4375,
          "frequency": "Daily",
          "unit": "Percent",
          "url": "https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&file_type=json&observation_start=2010-01-01&observation_end=2026-10-13",
          "resumed": true
        }
      ]
    },
    {
      "slot": "dff",
      "chosen": "DFF",
      "attempts": [
        {
          "series_id": "DFF",
          "ok": true,
          "stale": false,
          "start": "2010-01-01",
          "end": "2026-10-08",
          "rows": 6125,
          "frequency": "Daily, 7-Day",
          "unit": "Percent",
          "url": "https://api.stlouisfed.org/fred/series/observations?series_id=DFF&file_type=json&observation_start=2010-01-01&observation_end=2026-10-13",
          "resumed": true
        }
      ]
    },
    {
      "slot": "t10y2y",
      "chosen": "T10Y2Y",
      "attempts": [
        {
          "series_id": "T10Y2Y",
          "ok": true,
          "stale": false,
          "start": "2010-01-04",
          "end": "2026-10-09",
          "rows": 4376,
          "frequency": "Daily",
          "unit": "Percent",
          "url": "https://api.stlouisfed.org/fred/series/observations?series_id=T10Y2Y&file_type=json&observation_start=2010-01-01&observation_end=2026-10-13",
          "resumed": true
        }
      ]
    },
    {
      "slot": "vix",
      "chosen": "VIXCLS",
      "attempts": [
        {
          "series_id": "VIXCLS",
          "ok": true,
          "stale": false,
          "start": "2010-01-04",
          "end": "2026-10-09",
          "rows": 4376,
          "frequency": "Daily, Close",
          "unit": "Index",
          "url": "https://api.stlouisfed.org/fred/series/observations?series_id=VIXCLS&file_type=json&observation_start=2010-01-01&observation_end=2026-10-13",
          "resumed": true
        }
      ]
    },
    {
      "slot": "wti",
      "chosen": "DCOILWTICO",
      "attempts": [
        {
          "series_id": "DCOILWTICO",
          "ok": true,
          "stale": false,
          "start": "2010-01-04",
          "end": "2026-10-06",
          "rows": 4373,
          "frequency": "Daily",
          "unit": "Dollars per Barrel",
          "url": "https://api.stlouisfed.org/fred/series/observations?series_id=DCOILWTICO&file_type=json&observation_start=2010-01-01&observation_end=2026-10-13",
          "resumed": true
        }
      ]
    },
    {
      "slot": "gold",
      "chosen": null,
      "attempts": [
        {
          "series_id": "GOLDAMGBD228NLBM",
          "ok": false,
          "error": "Bad Request.  The series does not exist.",
          "url": "https://api.stlouisfed.org/fred/series/observations?series_id=GOLDAMGBD228NLBM&file_type=json&observation_start=2010-01-01&observation_end=2026-10-13",
          "http_status": 400
        }
      ]
    },
    {
      "slot": "equity",
      "chosen": "SP500",
      "attempts": [
        {
          "series_id": "SP500",
          "ok": true,
          "stale": false,
          "start": "2016-10-13",
          "end": "2026-10-12",
          "rows": 2608,
          "frequency": "Daily, Close",
          "unit": "Index",
          "url": "https://api.stlouisfed.org/fred/series/observations?series_id=SP500&file_type=json&observation_start=2010-01-01&observation_end=2026-10-13",
          "resumed": true
        }
      ]
    },
    {
      "slot": "credit",
      "chosen": "BAMLC0A0CM",
      "attempts": [
        {
          "series_id": "BAMLC0A0CM",
          "ok": true,
          "stale": false,
          "start": "2023-10-10",
          "end": "2026-10-08",
          "rows": 794,
          "frequency": "Daily, Close",
          "unit": "Percent",
          "url": "https://api.stlouisfed.org/fred/series/observations?series_id=BAMLC0A0CM&file_type=json&observation_start=2010-01-01&observation_end=2026-10-13",
          "resumed": true
        }
      ]
    }
  ],
  "alfred": [
    {
      "slot": "unrate",
      "chosen": null,
      "error": "UNRATE HTTP 0: curl: (28) Operation timed out after 90015 milliseconds with 0 bytes received\r\n",
      "url": "https://api.stlouisfed.org/fred/series"
    },
    {
      "slot": "cpi",
      "chosen": "CPIAUCSL",
      "rows": 682,
      "revised_observations": 131,
      "start": "2015-01-01",
      "end": "2026-08-01",
      "url": "https://api.stlouisfed.org/fred/series/observations?series_id=CPIAUCSL&file_type=json&observation_start=2015-01-01&observation_end=2026-10-13&realtime_start=2015-01-01&realtime_end=2026-10-13"
    }
  ],
  "cftc": {
    "markets": [
      "gold",
      "sp500",
      "ust10y",
      "wti"
    ],
    "rows": 368,
    "start": "2025-01-07",
    "end": "2026-10-06"
  }
}
```

## 时点规则

查询日 `as_of` 只能使用 `release_date <= as_of` 且 `observation_date <= as_of` 的记录。同一观测日有多版时，保留当时已发布的最新一版。

### FRED 市场与利率序列

这些序列没有逐期 ALFRED vintage。FRED 最新拉取里的 `realtime_start` 是查询窗口，不是每一期的发布时间，因此 `release_date` 设为观测日。含义是：价格或利率在观测日已经形成。FRED 网页入库时间可能更晚，那不是市场发布时间。这个假设让历史 `as_of` 看不到未来日期，但不会重建“次日上午才公布”的发布滞后。

利率、利差和 VIX 是水平值。本版不把它们换算成债券收益或资产 VaR。

### ALFRED

已入库的 ALFRED 序列把每一行的 `realtime_start` 当作 `release_date`。最新修订不会回填到更早的 `as_of`。没有本地 vintage 文件的序列保持缺口：UNRATE 只有 series 元数据，没有观测文件，上一次短请求超时后不再重试。不能用当前值假装做了修订史。CPIAUCSL 若出现在上表，修订月数来自本地文件里可区分的旧版。

### CFTC

压缩包里的日期是持仓观测日，通常为周二，不是公布日。公布日按 CFTC 规则：同周周五美东 15:30；若周三、周四或周五为美国联邦假日，则顺延到下一个营业日。该规则对照了 [2026 年官方发布日历](https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm) 中的延迟日：2026-01-05、2026-06-22、2026-07-06、2026-11-16、2026-11-30、2026-12-28。观测日当天看不到本期仓位。政府停摆等临时改期不在规则内，只以文件和这套假日规则为准。建库只读取 `data/raw/cftc` 里已经保存的压缩包，不重新下载。

净持仓是合约张数，不是价格。

## BIS SDMX

央行政策利率数据流。V0.1 只保留入口，不拉取全量 SDMX。

契约：`GET https://stats.bis.org/api/v1/dataflow/BIS` 列出数据流；`GET https://stats.bis.org/api/v1/data/{dataflow}/{key}/all` 取数。V0.1 不下载、不入库。

## 许可证与使用条件

- FRED / ALFRED：https://fred.stlouisfed.org/legal 。发表时注明圣路易斯联储 FRED，并遵守各序列上游来源的条款。
- CFTC COT：美国联邦政府公开报告，https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm 。
- 原始响应、SHA256、单位、频率、观测区间和发布日规则记在 `data/manifest.json`，与原始文件、parquet 分开。

## 指标与不做的事

价格序列可以计算简单收益、实现波动率、最大回撤、历史模拟 VaR 和 Expected Shortfall。WTI 是现货，不是期货展期收益。股指若使用 FRED 价格指数，则不含股息。黄金若已停更，只保留真实结尾，不外推。

V0.1 不做回测，也不报告策略收益。缺少可交易全收益、费用、滑点、展期和成交约束，制造一条净值会是假结果。

## 完整性

- 成功下载文件的 SHA256 与 manifest 一致。
- 未在源码、文档和原始响应中发现 FRED 密钥。

## 原始文件清单

| 路径 | 序列 | HTTP | 单位 | 频率 | 观测起 | 观测止 | SHA256 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| data/raw/fred/DGS2.meta.json | DGS2 | 200 | Percent | Daily | 1976-06-01 | 2026-10-08 | 607ce860c8aa |
| data/raw/fred/DGS2.observations.offset0.json | DGS2 | 200 | Percent | Daily | 2010-01-01 | 2026-10-08 | 78b05e151a7f |
| data/raw/fred/DGS10.meta.json | DGS10 | 200 | Percent | Daily | 1962-01-02 | 2026-10-08 | 99f485d71a12 |
| data/raw/fred/DGS10.observations.offset0.json | DGS10 | 200 | Percent | Daily | 2010-01-01 | 2026-10-08 | 7bc9a23192f8 |
| data/raw/fred/DFF.meta.json | DFF | 200 | Percent | Daily, 7-Day | 1954-07-01 | 2026-10-08 | 69da3abd0458 |
| data/raw/fred/DFF.observations.offset0.json | DFF | 200 | Percent | Daily, 7-Day | 2010-01-01 | 2026-10-08 | 176477536d3f |
| data/raw/fred/T10Y2Y.meta.json | T10Y2Y | 200 | Percent | Daily | 1976-06-01 | 2026-10-09 | 6cab2750e5bc |
| data/raw/fred/T10Y2Y.observations.offset0.json | T10Y2Y | 200 | Percent | Daily | 2010-01-01 | 2026-10-09 | e409d5c74253 |
| data/raw/fred/VIXCLS.meta.json | VIXCLS | 200 | Index | Daily, Close | 1990-01-02 | 2026-10-09 | 950e291a8d07 |
| data/raw/fred/VIXCLS.observations.offset0.json | VIXCLS | 200 | Index | Daily, Close | 2010-01-01 | 2026-10-09 | a6dab5fe15b5 |
| data/raw/fred/DCOILWTICO.meta.json | DCOILWTICO | 200 | Dollars per Barrel | Daily | 1986-01-02 | 2026-10-06 | 148767dc9fd0 |
| data/raw/fred/DCOILWTICO.observations.offset0.json | DCOILWTICO | 200 | Dollars per Barrel | Daily | 2010-01-01 | 2026-10-06 | 7372a9da674f |
| data/raw/fred/SP500.meta.json | SP500 | 200 | Index | Daily, Close | 2016-10-13 | 2026-10-12 | 07e15a1f5b50 |
| data/raw/fred/SP500.observations.offset0.json | SP500 | 200 | Index | Daily, Close | 2016-10-13 | 2026-10-12 | b924686ca7a2 |
| data/raw/fred/BAMLC0A0CM.meta.json | BAMLC0A0CM | 200 | Percent | Daily, Close | 2023-10-10 | 2026-10-08 | 78003cd13c0b |
| data/raw/fred/BAMLC0A0CM.observations.offset0.json | BAMLC0A0CM | 200 | Percent | Daily, Close | 2023-10-10 | 2026-10-08 | fa0fbc7ef6b0 |
| data/raw/fred/CPIAUCSL.meta.json | CPIAUCSL | 200 | Index 1982-1984=100 | Monthly | 1947-01-01 | 2026-08-01 | 5357799bd909 |
| data/raw/alfred/CPIAUCSL.observations.offset0.json | CPIAUCSL | 200 | Index 1982-1984=100 | Monthly | 2015-01-01 | 2026-08-01 | 062556c2b05c |
| data/raw/cftc/fut_disagg_txt_2025.zip | fut_disagg_txt_2025.zip | 200 | contracts | Weekly | 2025-01-07 | 2025-12-30 | 17ac2fef1b53 |
| data/raw/cftc/fut_disagg_txt_2026.zip | fut_disagg_txt_2026.zip | 200 | contracts | Weekly | 2026-01-06 | 2026-10-06 | efe9751cd985 |
| data/raw/cftc/fut_fin_txt_2025.zip | fut_fin_txt_2025.zip | 200 | contracts | Weekly | 2025-01-07 | 2025-12-30 | 2ea0cda6395f |
| data/raw/cftc/fut_fin_txt_2026.zip | fut_fin_txt_2026.zip | 200 | contracts | Weekly | 2026-01-06 | 2026-10-06 | 09f68d6ff5d2 |
