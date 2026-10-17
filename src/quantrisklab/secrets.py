"""把本机 FRED 密钥注入进程环境变量 FRED_API_KEY。不得记录密钥本身。"""

from __future__ import annotations

import logging
import os
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

API_DIR = Path(r"F:\AI\API")
_KEY_RE = re.compile(r"\b[A-Za-z0-9]{32}\b")


def load_fred_api_key() -> None:
    existing = os.environ.get("FRED_API_KEY", "").strip()
    if existing:
        logger.info("使用进程环境变量 FRED_API_KEY")
        return
    path = _find_key_file()
    if path is None:
        raise RuntimeError(
            "未设置 FRED_API_KEY，且在 F:\\AI\\API 未找到文件名包含 fred 的 txt/docx 密钥文件"
        )
    key = _read_key(path)
    if not key:
        raise RuntimeError(f"无法从 {path.name} 解析 FRED 密钥")
    os.environ["FRED_API_KEY"] = key
    logger.info("已从本机文件注入 FRED_API_KEY（文件名=%s），未写入仓库", path.name)


def _find_key_file() -> Path | None:
    if not API_DIR.is_dir():
        return None
    candidates: list[Path] = []
    for path in API_DIR.iterdir():
        if not path.is_file():
            continue
        name = path.name.lower()
        if "fred" not in name:
            continue
        if "comtrade" in name:
            continue
        if path.suffix.lower() in {".txt", ".key", ".env", ".docx"} or path.suffix == "":
            candidates.append(path)
    candidates.sort(key=lambda item: (item.suffix.lower() == ".docx", item.name.lower()))
    return candidates[0] if candidates else None


def _read_key(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        text = _docx_text(path)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        piece = line.strip()
        if not piece or piece.startswith("#"):
            continue
        if "=" in piece:
            piece = piece.split("=", 1)[1].strip().strip('"').strip("'")
        match = _KEY_RE.search(piece)
        if match:
            return match.group(0)
    match = _KEY_RE.search(text)
    return match.group(0) if match else ""


def _docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ET.fromstring(xml)
    parts = [node.text or "" for node in root.iter() if node.tag.endswith("}t")]
    return "\n".join(parts)
