"""Download plan. Interest rates are levels, not asset prices."""

from __future__ import annotations

FRED_LICENSE = (
    "经由 FRED API 获取。使用受 FRED 条款约束"
    "（https://fred.stlouisfed.org/legal），并受各序列上游来源条款约束。"
    "原始响应中的 series notes 一并存档。"
)

# Same-day publication: the economic information exists on the observation date.
# FRED's realtime_start on a latest-only pull is the query window, not a vintage.
SAME_DAY = (
    "该序列不走 ALFRED vintage。官方最新拉取里的 realtime_start 是查询窗口，"
    "不能当作每一期的发布日。本库将 release_date 设为 observation_date："
    "价格或利率在观测日已经形成并公开。FRED 网页入库时间可能更晚，那不是市场发布时间。"
)

YIELD_NOTE = "利率或利差是水平值，单位为百分点。本版本不把它换算成债券收益，也不计算资产 VaR。"

FRED_SLOTS: list[dict] = [
    {
        "slot": "dgs2",
        "candidates": ["DGS2"],
        "role": "yield",
        "title_zh": "2年期美国国债收益率",
        "price_metrics": False,
        "prefer_fresh": False,
        "observation_start": "2010-01-01",
        "release_rule": SAME_DAY + " 来源为美联储 H.15 国债恒定到期收益率。",
        "notes": YIELD_NOTE,
    },
    {
        "slot": "dgs10",
        "candidates": ["DGS10"],
        "role": "yield",
        "title_zh": "10年期美国国债收益率",
        "price_metrics": False,
        "prefer_fresh": False,
        "observation_start": "2010-01-01",
        "release_rule": SAME_DAY + " 来源为美联储 H.15。",
        "notes": YIELD_NOTE,
    },
    {
        "slot": "dff",
        "candidates": ["DFF"],
        "role": "yield",
        "title_zh": "有效联邦基金利率",
        "price_metrics": False,
        "prefer_fresh": False,
        "observation_start": "2010-01-01",
        "release_rule": SAME_DAY + " 纽约联储有效联邦基金利率，按观测日公布。",
        "notes": YIELD_NOTE,
    },
    {
        "slot": "t10y2y",
        "candidates": ["T10Y2Y"],
        "role": "spread",
        "title_zh": "10年减2年国债利差",
        "price_metrics": False,
        "prefer_fresh": False,
        "observation_start": "2010-01-01",
        "release_rule": SAME_DAY + " 由国债收益率相减，不是交易价格。",
        "notes": YIELD_NOTE,
    },
    {
        "slot": "vix",
        "candidates": ["VIXCLS"],
        "role": "volatility_index",
        "title_zh": "VIX 波动率指数",
        "price_metrics": False,
        "prefer_fresh": True,
        "observation_start": "2010-01-01",
        "release_rule": SAME_DAY + " Cboe VIX 在观测日收盘后公布。它是波动率指数，不是可持有资产的价格。",
        "notes": "只展示指数水平。不把 VIX 变动当作资产收益，不算 VaR。",
    },
    {
        "slot": "wti",
        "candidates": ["DCOILWTICO"],
        "role": "price",
        "title_zh": "WTI 原油现货价格",
        "price_metrics": True,
        "prefer_fresh": True,
        "observation_start": "2010-01-01",
        "release_rule": SAME_DAY + " EIA 库欣 WTI 现货，美元/桶。收益是现货简单收益，不含展期。",
        "notes": "现货价格序列，可用于收益、实现波动率、回撤、历史模拟 VaR 与 Expected Shortfall。",
    },
    {
        "slot": "gold",
        "candidates": ["GOLDAMGBD228NLBM"],
        "role": "price",
        "title_zh": "伦敦金价",
        "price_metrics": True,
        "prefer_fresh": True,
        "observation_start": "2010-01-01",
        "release_rule": SAME_DAY + " 伦敦金银市场定盘价，美元/金衡盎司。若序列已停更，不外推。",
        "notes": "优先上午定盘价。若已停更，尝试下午定盘价。停更序列只覆盖其真实样本。",
    },
    {
        "slot": "equity",
        "candidates": ["SP500", "WILL5000PRFC", "WILL5000PR", "NASDAQCOM", "DJIA"],
        "role": "price_index",
        "title_zh": "美国股指",
        "price_metrics": True,
        "prefer_fresh": True,
        "observation_start": "2010-01-01",
        "release_rule": SAME_DAY
        + " 价格指数在观测日收盘后可知。收益是价格指数简单收益，不含股息，不是全收益。",
        "notes": "优先 FRED 的 SP500。若不可用或停更，按候选顺序改用仍在更新的公开指数，并在元数据中写明限制。",
    },
    {
        "slot": "credit",
        "candidates": ["BAMLC0A0CM", "BAA10Y"],
        "role": "spread",
        "title_zh": "美国信用利差",
        "price_metrics": False,
        "prefer_fresh": True,
        "observation_start": "2010-01-01",
        "release_rule": SAME_DAY + " 信用利差是期权调整利差或评级利差，单位为百分点，不是债券价格。",
        "notes": YIELD_NOTE + " 优先 ICE BofA 美国公司债 OAS（BAMLC0A0CM），否则用穆迪 Baa 与 10 年国债利差（BAA10Y）。",
    },
]

ALFRED_SLOTS: list[dict] = [
    {
        "slot": "unrate",
        "series_id": "UNRATE",
        "role": "macro",
        "title_zh": "美国失业率",
        "price_metrics": False,
        "observation_start": "2015-01-01",
        "realtime_start": "2015-01-01",
        "release_rule": (
            "ALFRED vintage 的 realtime_start 作为 release_date。"
            "as_of 查询只保留 release_date <= as_of 的版本，再对每个观测月取最新一版。"
            "禁止用当前修订值回填历史。"
        ),
        "notes": "季节调整后的失业率，会修订。单位为百分点。不是资产价格。",
    },
    {
        "slot": "cpi",
        "series_id": "CPIAUCSL",
        "role": "macro",
        "title_zh": "美国 CPI（季调）",
        "price_metrics": False,
        "observation_start": "2015-01-01",
        "realtime_start": "2015-01-01",
        "release_rule": (
            "ALFRED vintage 的 realtime_start 作为 release_date。"
            "点时查询不得看到 as_of 之后才发布的修订。"
        ),
        "notes": "CPIAUCSL 为季调指数，存在月度与年度修订。不是资产价格。",
    },
]

CFTC_LICENSE = (
    "美国商品期货交易委员会 Commitments of Traders 公开报告。"
    "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm"
)

CFTC_YEARS = (2025, 2026)

CFTC_FILES = {
    "disagg": "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip",
    "tff": "https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip",
}

CFTC_MARKETS = {
    "gold": {
        "title_zh": "COMEX 黄金期货",
        "report": "disagg",
        "group": "managed_money",
        "group_zh": "管理资金",
    },
    "wti": {
        "title_zh": "NYMEX 轻质原油期货",
        "report": "disagg",
        "group": "managed_money",
        "group_zh": "管理资金",
    },
    "sp500": {
        "title_zh": "CME E-mini 标普500期货",
        "report": "tff",
        "group": "leveraged_funds",
        "group_zh": "杠杆资金",
    },
    "ust10y": {
        "title_zh": "CBOT 10年期美国国债期货",
        "report": "tff",
        "group": "leveraged_funds",
        "group_zh": "杠杆资金",
    },
}
