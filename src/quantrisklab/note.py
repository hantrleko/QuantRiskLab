"""Render a research note from an existing payload. This module does not estimate anything."""

from __future__ import annotations

import csv
import io

CAPTION = "约化式，不是因果估计，也不是交易结果。"
COLUMNS = ("as_of", "window", "item", "estimate", "se", "ci95_low", "ci95_high", "n", "reason")
_COVAR = (
    ("equity_on_oil", "delta_covar_oil"),
    ("equity_on_yield_change", "delta_covar_yield"),
)


def _blank(as_of: str, window: int, item: str) -> dict:
    return {
        "as_of": as_of,
        "window": window,
        "item": item,
        "estimate": None,
        "se": None,
        "ci95_low": None,
        "ci95_high": None,
        "n": None,
        "reason": "",
    }


def note_rows(payload: dict, window: int) -> list[dict]:
    """One row per published research item. Ineligible items keep an empty estimate."""
    as_of = str(payload["as_of"])
    rows: list[dict] = []

    def add(item: str, **fields: object) -> None:
        row = _blank(as_of, window, item)
        row.update(fields)
        rows.append(row)

    projection = payload.get("local_projection") or {}
    horizons = projection.get("horizons") or []
    if not horizons:
        add("local_projection", reason=projection.get("reason") or "没有期限结果")
    for item in horizons:
        eligible = bool(item.get("eligible")) and item.get("beta") is not None
        interval = item.get("ci95") or [None, None]
        if eligible:
            add(
                f"lp_{item['horizon']}d",
                estimate=item.get("beta"),
                se=item.get("se"),
                ci95_low=interval[0],
                ci95_high=interval[1],
                n=item.get("n"),
            )
        else:
            add(
                f"lp_{item['horizon']}d",
                reason=item.get("reason") or projection.get("reason") or "该期限没有系数",
            )

    euler = payload.get("euler") or {}
    if euler.get("eligible"):
        names = euler.get("names") or []
        shares = euler.get("shares") or []
        shrunk = (euler.get("shrinkage") or {}).get("shares") or []
        for index, name in enumerate(names):
            add(
                f"variance_share:{name}",
                estimate=shares[index] if index < len(shares) else None,
                n=euler.get("n"),
            )
            if index < len(shrunk):
                add(f"variance_share_shrunk:{name}", estimate=shrunk[index], n=euler.get("n"))
        shrinkage = euler.get("shrinkage") or {}
        if shrinkage.get("intensity") is not None:
            add("shrinkage_intensity", estimate=shrinkage["intensity"], n=euler.get("n"))
    else:
        add("variance_share", reason=euler.get("reason") or "方差贡献不可用")

    covar = payload.get("covar") or {}
    for key, item_name in _COVAR:
        block = covar.get(key) or {}
        if block.get("eligible") and block.get("delta_covar") is not None:
            add(item_name, estimate=block["delta_covar"], n=block.get("n"))
        else:
            add(item_name, reason=block.get("reason") or "分位数差值不可用")

    add("caption", reason=CAPTION)
    return rows


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return format(value, ".16g")
    return str(value)


def note_csv(payload: dict, window: int) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in note_rows(payload, window):
        writer.writerow({column: _cell(row[column]) for column in COLUMNS})
    return buffer.getvalue()


def note_markdown(payload: dict, window: int) -> str:
    rows = note_rows(payload, window)
    as_of = rows[0]["as_of"] if rows else payload.get("as_of", "")
    lines = [
        "# QuantRiskLab 研究记录",
        "",
        f"- as_of: {as_of}",
        f"- window: {window}",
        f"- {CAPTION}",
        "",
        "| " + " | ".join(COLUMNS) + " |",
        "| " + " | ".join("---" for _ in COLUMNS) + " |",
    ]
    for row in rows:
        cells = [_cell(row[column]).replace("|", "\\|") for column in COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def _tex(value: str) -> str:
    return (
        value.replace("\\", r"\textbackslash{}")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("_", r"\_")
        .replace("#", r"\#")
    )


def note_latex(payload: dict, window: int) -> str:
    rows = note_rows(payload, window)
    as_of = rows[0]["as_of"] if rows else payload.get("as_of", "")
    lines = [
        r"\begin{table}[ht]",
        r"\centering",
        r"\begin{tabular}{lrrrrl}",
        r"\toprule",
        r"item & estimate & se & ci95 low & ci95 high & reason \\",
        r"\midrule",
    ]
    for row in rows:
        if row["item"] == "caption":
            continue
        lines.append(
            " & ".join(
                [
                    _tex(str(row["item"])),
                    _tex(_cell(row["estimate"]) or "--"),
                    _tex(_cell(row["se"]) or "--"),
                    _tex(_cell(row["ci95_low"]) or "--"),
                    _tex(_cell(row["ci95_high"]) or "--"),
                    _tex(_cell(row["reason"])),
                ]
            )
            + r" \\"
        )
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            rf"\caption{{QuantRiskLab as-of {as_of}, window {window}. {_tex(CAPTION)}}}",
            r"\end{table}",
        ]
    )
    return "\n".join(lines) + "\n"


def note_document(payload: dict, window: int, fmt: str) -> tuple[str, str, str]:
    as_of = payload["as_of"]
    stem = f"quantrisklab-note-{as_of}-w{window}"
    if fmt == "csv":
        return note_csv(payload, window), "text/csv; charset=utf-8", f"{stem}.csv"
    if fmt == "md":
        return note_markdown(payload, window), "text/markdown; charset=utf-8", f"{stem}.md"
    if fmt == "tex":
        return note_latex(payload, window), "text/plain; charset=utf-8", f"{stem}.tex"
    raise ValueError(fmt)
