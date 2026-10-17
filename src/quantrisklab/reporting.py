"""Write the source ledger, fixtures, and integrity checks after a download."""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path

import polars as pl

from quantrisklab.fred_key import ensure_fred_api_key
from quantrisklab.metrics.risk import summarize_price
from quantrisklab.paths import (
    DECISIONS_JSON,
    FAILURES_JSON,
    MANIFEST_JSON,
    QUALITY_JSON,
    RAW_DIR,
    ROOT,
    ensure_dirs,
)
from quantrisklab.sources.bis import BisSdmxClient
from quantrisklab.sources.http_util import sha256_file
from quantrisklab.store.database import connect_readonly
from quantrisklab.store.pit import query_series

logger = logging.getLogger("quantrisklab.report")
FIXTURES = ROOT / "tests" / "fixtures"
SUMMARY = ROOT / "data" / "results" / "v0_summary.json"
DATA_SOURCES = ROOT / "DATA_SOURCES.md"
SCAN_SUFFIXES = {".py", ".md", ".json", ".txt", ".csv", ".ts", ".tsx", ".css", ".html", ".toml", ".ini", ".log"}


def write_outputs() -> int:
    ensure_dirs()
    manifest = _read_json(MANIFEST_JSON, [])
    failures = _read_json(FAILURES_JSON, [])
    decisions = _read_json(DECISIONS_JSON, {})
    quality = _read_json(QUALITY_JSON, [])
    problems = verify_manifest(manifest)
    problems.extend(scan_for_key())
    fixture_notes = export_fixtures()
    metrics = []
    if _database_ready():
        problems.extend(verify_cftc_release_order())
        metrics = price_metric_summaries()
    summary = {
        "as_of": date.today().isoformat(),
        "series": [
            {
                "series_id": row.get("series_id"),
                "title_zh": row.get("title_zh"),
                "source": row.get("source"),
                "frequency": row.get("frequency"),
                "n_visible": row.get("n_visible"),
                "start": row.get("start"),
                "end": row.get("end"),
                "stale": row.get("stale"),
                "revised_observations": row.get("revised_observations"),
                "price_metrics": row.get("price_metrics"),
            }
            for row in quality
        ],
        "failures": failures,
        "metrics": metrics,
        "fixtures": fixture_notes,
        "integrity_problems": problems,
        "backtest": "未做。没有可交易全收益、费用、期货展期和成交假设，不能报告策略收益。",
        "charts": chart_plan(quality),
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    DATA_SOURCES.write_text(render_sources(manifest, failures, decisions, quality, problems), encoding="utf-8")
    if problems:
        for item in problems:
            logger.error("完整性问题 %s", item)
        return 1
    return 0


def verify_manifest(manifest: list[dict]) -> list[str]:
    problems = []
    checked = 0
    for row in manifest:
        if int(row.get("http_status") or 0) != 200:
            continue
        path = ROOT / row["path"]
        if not path.exists():
            problems.append(f"manifest 指向的文件不存在: {row['path']}")
            continue
        digest = sha256_file(path)
        if digest != row.get("sha256"):
            problems.append(f"SHA256 不一致: {row['path']}")
            continue
        checked += 1
    if checked == 0:
        problems.append("没有可核对的成功下载文件")
    return problems


def verify_cftc_release_order() -> list[str]:
    connection = connect_readonly()
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM cftc_positions WHERE release_date <= observation_date"
        ).fetchone()[0]
    except Exception as exc:
        logger.exception("CFTC 时点检查失败")
        return [f"CFTC 时点检查失败: {exc}"]
    finally:
        connection.close()
    if count:
        return [f"CFTC 有 {count} 行发布日不晚于观测日"]
    return []


def scan_for_key() -> list[str]:
    try:
        ensure_fred_api_key()
    except Exception as exc:
        logger.exception("无法加载 FRED_API_KEY 以做泄漏扫描")
        return [f"密钥扫描未能启动: {exc}"]
    key = os.environ.get("FRED_API_KEY", "").encode()
    if len(key) < 16:
        return ["FRED_API_KEY 为空，无法扫描泄漏"]
    leaked = []
    roots = [ROOT / "src", ROOT / "tests", ROOT / "frontend", ROOT / "scripts", RAW_DIR, ROOT / "logs", ROOT / "data"]
    files = [DATA_SOURCES, ROOT / "README.md", ROOT / "ARCHITECTURE.md", ROOT / "pyproject.toml"]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or _skip(path):
                continue
            files.append(path)
    seen = set()
    for path in files:
        if path in seen or not path.exists() or not path.is_file() or _skip(path):
            continue
        seen.add(path)
        if path.stat().st_size > 40_000_000 or path.suffix.lower() not in SCAN_SUFFIXES:
            continue
        if key in path.read_bytes():
            leaked.append(str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path))
    return [f"密钥出现在文件中: {item}" for item in leaked]


def _skip(path: Path) -> bool:
    parts = set(path.parts)
    return bool(parts & {".venv", "node_modules", "dist", "__pycache__", ".git"})


def export_fixtures() -> dict:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    notes = {"alfred": None, "price": None, "cftc": None, "missing": None}
    if not _database_ready():
        return notes
    notes["alfred"] = _alfred_fixture()
    notes["price"] = _price_fixture()
    notes["cftc"] = _cftc_fixture()
    notes["missing"] = _missing_fixture()
    return notes


def _alfred_fixture() -> str:
    connection = connect_readonly()
    try:
        chosen = connection.execute(
            """
            SELECT series_id, observation_date
            FROM observations
            WHERE source = 'alfred' AND value IS NOT NULL
            GROUP BY series_id, observation_date
            HAVING COUNT(DISTINCT value) > 1
            ORDER BY observation_date
            LIMIT 3
            """
        ).fetchall()
        if not chosen:
            return "未发现修订，未写 PIT fixture"
        series_id = chosen[0][0]
        dates = {str(row[1])[:10] for row in chosen}
        arrow = connection.execute(
            """
            SELECT series_id, source, observation_date, release_date, value, realtime_start, realtime_end
            FROM observations
            WHERE source = 'alfred' AND series_id = ?
            ORDER BY observation_date, release_date
            """,
            [series_id],
        ).to_arrow_table()
    finally:
        connection.close()
    data = pl.from_arrow(arrow).filter(
        pl.col("observation_date").cast(pl.Utf8).str.slice(0, 10).is_in(list(dates))
    )
    path = FIXTURES / "alfred_pit.parquet"
    data.write_parquet(path)
    url = _manifest_url(series_id)
    (FIXTURES / "alfred_pit.json").write_text(
        json.dumps(
            {
                "source_url": url,
                "access_date": date.today().isoformat(),
                "series_id": series_id,
                "excerpt_dates": sorted(dates),
                "note": "真实 ALFRED vintage 摘录，不是合成数据。同一观测月的不同 value 来自不同 release_date。",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return f"{series_id} dates={len(dates)} rows={data.height}"


def _price_fixture() -> str:
    connection = connect_readonly()
    try:
        row = connection.execute(
            """
            SELECT series_id FROM series_meta
            WHERE price_metrics = TRUE
            ORDER BY stale, series_id
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return "没有价格序列，未写 VaR fixture"
        series_id = row[0]
        frame = query_series(connection, series_id, date.today())
    finally:
        connection.close()
    present = frame.filter(pl.col("value").is_not_null() & (pl.col("value") > 0)).sort("observation_date")
    if present.height < 80:
        return f"{series_id} 正价格样本不足"
    excerpt = present.tail(min(500, present.height))
    lines = [
        f"# source_url: {_manifest_url(series_id)}",
        f"# access_date: {date.today().isoformat()}",
        f"# series_id: {series_id}",
        f"# excerpt_start: {excerpt['observation_date'].min()}",
        f"# excerpt_end: {excerpt['observation_date'].max()}",
        "# note: real FRED price excerpt, not synthetic",
        "observation_date,value",
    ]
    for item in excerpt.select(["observation_date", "value"]).iter_rows(named=True):
        lines.append(f"{item['observation_date']},{item['value']}")
    (FIXTURES / "price_excerpt.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"{series_id} rows={excerpt.height}"


def _cftc_fixture() -> str:
    connection = connect_readonly()
    try:
        arrow = connection.execute(
            """
            SELECT market_id, observation_date, release_date, net_positions, source_file
            FROM cftc_positions
            WHERE net_positions IS NOT NULL AND release_date > observation_date
            ORDER BY market_id, observation_date
            LIMIT 24
            """
        ).to_arrow_table()
    finally:
        connection.close()
    frame = pl.from_arrow(arrow)
    if frame.is_empty():
        return "没有 CFTC 持仓，未写 fixture"
    frame.write_parquet(FIXTURES / "cftc_excerpt.parquet")
    (FIXTURES / "cftc_excerpt.json").write_text(
        json.dumps(
            {
                "source_url": "https://www.cftc.gov/files/dea/history/",
                "access_date": date.today().isoformat(),
                "note": "真实 COT 持仓摘录。release_date 按文档化的周五规则推算，不是文件字段。",
                "rows": frame.height,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return f"rows={frame.height}"


def _missing_fixture() -> str:
    candidates = sorted((RAW_DIR / "fred").glob("*.observations.offset0.json")) if (RAW_DIR / "fred").exists() else []
    for path in candidates:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("observations") or []
        dotted = [row for row in rows if row.get("value") == "."]
        numeric = [row for row in rows if row.get("value") not in {None, "", "."}]
        if not dotted or not numeric:
            continue
        excerpt = (dotted[:3] + numeric[:5])[:8]
        series_id = path.name.split(".observations")[0]
        (FIXTURES / "fred_missing.json").write_text(
            json.dumps(
                {
                    "source_url": f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&file_type=json",
                    "access_date": date.today().isoformat(),
                    "series_id": series_id,
                    "source_file": str(path.relative_to(ROOT)).replace("\\", "/"),
                    "note": "从真实 FRED 响应摘出的缺失值与数值，不是合成数据。",
                    "observations": excerpt,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return series_id
    return "原始响应里没有同时包含 '.' 和数值的片段"


def price_metric_summaries() -> list[dict]:
    connection = connect_readonly()
    rows = []
    try:
        ids = [
            item[0]
            for item in connection.execute(
                "SELECT series_id FROM series_meta WHERE price_metrics = TRUE ORDER BY series_id"
            ).fetchall()
        ]
        for series_id in ids:
            frame = query_series(connection, series_id, date.today())
            try:
                summary = summarize_price(frame, 63, 0.05)
                summary["series_id"] = series_id
            except Exception as exc:
                logger.exception("价格指标失败 series=%s", series_id)
                summary = {"series_id": series_id, "eligible": False, "reason": str(exc)}
            rows.append(summary)
    finally:
        connection.close()
    return rows


def chart_plan(quality: list[dict]) -> list[dict]:
    by_role: dict[str, list[str]] = {}
    prices = []
    for row in quality:
        by_role.setdefault(row.get("role") or "", []).append(row.get("series_id"))
        if row.get("price_metrics"):
            prices.append(row.get("series_id"))
    return [
        {"chart": "宏观收益率折线", "series": [item for item in ["DGS2", "DGS10", "DFF", "T10Y2Y"] if item in sum(by_role.values(), [])]},
        {"chart": "滚动相关矩阵", "price_series": prices, "level_series": by_role.get("yield", []) + by_role.get("spread", [])},
        {"chart": "风险热力图", "price_vol": prices, "level_scale": by_role.get("yield", [])},
        {"chart": "CFTC 净持仓", "source": "cftc"},
        {"chart": "ALFRED 时点对比", "series": by_role.get("macro", [])},
    ]


def render_sources(manifest, failures, decisions, quality, problems) -> str:
    lines = [
        "# 数据来源",
        "",
        f"生成日期：{date.today().isoformat()}。本文件由本地缓存建库重写，本次没有重新请求 FRED。",
        "",
        "平台不提供买卖建议。没有真实观测的序列不会用假数据填补。",
        "",
        "## 本次入库序列",
        "",
        "行数是 as_of 为今天时、点时查询可见的非缺失观测数，不是把全部 vintage 叠在一起的行数。",
        "",
        "| 序列 | 名称 | 来源 | 频率 | 可见行数 | 起始 | 结束 | 修订月数 | 状态 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    if not quality:
        lines.append("| — | 没有入库序列 | — | — | — | — | — | — | — |")
    for row in quality:
        state = "滞后或停更" if row.get("stale") else "已入库"
        lines.append(
            "| {series_id} | {title_zh} | {source} | {frequency} | {n_visible} | {start} | {end} | {revised_observations} | {state} |".format(
                state=state, **{key: row.get(key) for key in row}
            )
        )
    lines.extend(["", "## 失败与未采用的请求", ""])
    if not failures:
        lines.append("本次没有记录失败请求。候选序列里被放弃的停更序列写在下面的决策记录中。")
    else:
        lines.extend(["| 来源 | 序列或文件 | HTTP | URL | 错误 |", "| --- | --- | --- | --- | --- |"])
        for item in failures:
            lines.append(
                "| {source} | {series_id} | {http_status} | {url} | {error} |".format(
                    source=item.get("source"),
                    series_id=item.get("series_id"),
                    http_status=item.get("http_status"),
                    url=item.get("url"),
                    error=str(item.get("error") or "").replace("|", "/").replace("\n", " ")[:240],
                )
            )
    lines.extend(
        [
            "",
            "### 五次探测的最终状态",
            "",
            "早先中断时记下五次失败探测。有完整本地观测的序列已经入库；没有观测文件的保持缺口。这里不重新请求 FRED。",
            "",
            "| 序列 | 状态 |",
            "| --- | --- |",
            "| DCOILWTICO | 本地观测文件完整，已入库。2020-04-20 价格为负，仍留在序列中。这一天和下一期不进入简单收益或 VaR。价格比回撤可以低于 -100%。不外推。 |",
            "| SP500 | 本地观测文件完整，已入库。样本从 2016-10-13 起，是价格指数，不含股息。 |",
            "| GOLDAMGBD228NLBM | 缺口。本地响应是 HTTP 400，序列不存在，没有观测文件。不再重试。 |",
            "| GOLDPMGBD228NLBM | 缺口。没有本地文件。不再重试。 |",
            "| UNRATE | 缺口。只有 series 元数据，没有 vintage 观测文件。短请求超时后不再重试。 |",
            "",
        ]
    )
    lines.extend(["", "## 槽位决策", "", "```json", json.dumps(decisions, ensure_ascii=False, indent=2, default=str), "```", ""])
    lines.extend(
        [
            "## 时点规则",
            "",
            "查询日 `as_of` 只能使用 `release_date <= as_of` 且 `observation_date <= as_of` 的记录。同一观测日有多版时，保留当时已发布的最新一版。",
            "",
            "### FRED 市场与利率序列",
            "",
            "这些序列没有逐期 ALFRED vintage。FRED 最新拉取里的 `realtime_start` 是查询窗口，不是每一期的发布时间，因此 `release_date` 设为观测日。含义是：价格或利率在观测日已经形成。FRED 网页入库时间可能更晚，那不是市场发布时间。这个假设让历史 `as_of` 看不到未来日期，但不会重建“次日上午才公布”的发布滞后。",
            "",
            "利率、利差和 VIX 是水平值。本版不把它们换算成债券收益或资产 VaR。",
            "",
            "### ALFRED",
            "",
            "已入库的 ALFRED 序列把每一行的 `realtime_start` 当作 `release_date`。最新修订不会回填到更早的 `as_of`。没有本地 vintage 文件的序列保持缺口：UNRATE 只有 series 元数据，没有观测文件，上一次短请求超时后不再重试。不能用当前值假装做了修订史。CPIAUCSL 若出现在上表，修订月数来自本地文件里可区分的旧版。",
            "",
            "### CFTC",
            "",
            "压缩包里的日期是持仓观测日，通常为周二，不是公布日。公布日按 CFTC 规则：同周周五美东 15:30；若周三、周四或周五为美国联邦假日，则顺延到下一个营业日。该规则对照了 [2026 年官方发布日历](https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm) 中的延迟日：2026-01-05、2026-06-22、2026-07-06、2026-11-16、2026-11-30、2026-12-28。观测日当天看不到本期仓位。政府停摆等临时改期不在规则内，只以文件和这套假日规则为准。建库只读取 `data/raw/cftc` 里已经保存的压缩包，不重新下载。",
            "",
            "净持仓是合约张数，不是价格。",
            "",
            "## BIS SDMX",
            "",
            BisSdmxClient().describe()["note"],
            "",
            "契约：`GET https://stats.bis.org/api/v1/dataflow/BIS` 列出数据流；`GET https://stats.bis.org/api/v1/data/{dataflow}/{key}/all` 取数。V0.1 不下载、不入库。",
            "",
            "## 许可证与使用条件",
            "",
            "- FRED / ALFRED：https://fred.stlouisfed.org/legal 。发表时注明圣路易斯联储 FRED，并遵守各序列上游来源的条款。",
            "- CFTC COT：美国联邦政府公开报告，https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm 。",
            "- 原始响应、SHA256、单位、频率、观测区间和发布日规则记在 `data/manifest.json`，与原始文件、parquet 分开。",
            "",
            "## 指标与不做的事",
            "",
            "价格序列可以计算简单收益、实现波动率、最大回撤、历史模拟 VaR 和 Expected Shortfall。WTI 是现货，不是期货展期收益。股指若使用 FRED 价格指数，则不含股息。黄金若已停更，只保留真实结尾，不外推。",
            "",
            "V0.1 不做回测，也不报告策略收益。缺少可交易全收益、费用、滑点、展期和成交约束，制造一条净值会是假结果。",
            "",
            "## 完整性",
            "",
        ]
    )
    if problems:
        for item in problems:
            lines.append(f"- {item}")
    else:
        lines.append("- 成功下载文件的 SHA256 与 manifest 一致。")
        lines.append("- 未在源码、文档和原始响应中发现 FRED 密钥。")
    lines.extend(["", "## 原始文件清单", ""])
    lines.append("| 路径 | 序列 | HTTP | 单位 | 频率 | 观测起 | 观测止 | SHA256 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in manifest:
        lines.append(
            "| {path} | {series_id} | {http_status} | {original_unit} | {original_frequency} | {observation_date_min} | {observation_date_max} | {sha} |".format(
                path=row.get("path"),
                series_id=row.get("series_id"),
                http_status=row.get("http_status"),
                original_unit=row.get("original_unit") or "",
                original_frequency=row.get("original_frequency") or "",
                observation_date_min=row.get("observation_date_min"),
                observation_date_max=row.get("observation_date_max"),
                sha=(row.get("sha256") or "")[:12],
            )
        )
    lines.append("")
    return "\n".join(lines)


def _manifest_url(series_id: str) -> str:
    manifest = _read_json(MANIFEST_JSON, [])
    for row in manifest:
        if row.get("series_id") == series_id and "observations" in str(row.get("path")):
            return row.get("url") or ""
    return f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&file_type=json"


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _database_ready() -> bool:
    from quantrisklab.paths import DB_PATH

    return DB_PATH.exists()
