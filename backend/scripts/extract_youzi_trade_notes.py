"""
Read-only extractor for local Youzi trade-sheet materials.

The source folder is outside the project and must not be modified. This script
uses only Python standard-library parsers for Office Open XML files, then writes
an extraction report inside backend/data/ai/youzi_trade_notes/.
"""
from __future__ import annotations

import json
import os
import re
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET


SOURCE_ROOT = Path(r"E:\迅雷\下载目录\游资交割单")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "backend" / "data" / "ai" / "youzi_trade_notes"

KEYWORDS = [
    "交割单",
    "心法",
    "情绪",
    "龙头",
    "板块",
    "复盘",
    "龙虎榜",
    "买卖点",
    "仓位",
    "风险",
    "公告",
    "题材",
    "看盘",
    "短线",
    "模式",
    "退学",
    "炒股养家",
    "涅盘",
    "涅槃",
    "92科比",
    "乔帮主",
    "赵老哥",
    "BJ炒家",
    "轮回666",
]

THEME_PATTERNS = {
    "emotion_cycle": ["情绪", "周期", "退潮", "高潮", "冰点", "修复", "分歧", "一致"],
    "leader_sector": ["龙头", "板块", "主线", "题材", "强弱", "辨识度", "带动"],
    "entry_timing": ["买点", "低吸", "半路", "打板", "回封", "分时", "承接", "突破"],
    "exit_timing": ["卖点", "止损", "止盈", "不及预期", "炸板", "破位", "减仓"],
    "position_risk": ["仓位", "回撤", "风险", "控制", "纪律", "空仓"],
    "disclosure_news": ["公告", "信息", "利好", "利空", "公开信息", "新闻"],
    "lhb_review": ["龙虎榜", "席位", "营业部", "交割单", "复盘"],
    "market_tape": ["看盘", "盘口", "量能", "换手", "封单", "炸板", "大单"],
}


def _text_from_xml_bytes(data: bytes) -> str:
    try:
        root = ET.fromstring(data)
    except Exception:
        return ""
    texts = []
    for node in root.iter():
        if node.tag.endswith("}t") and node.text:
            texts.append(node.text)
        elif node.tag.endswith("}tab"):
            texts.append("\t")
        elif node.tag.endswith("}br"):
            texts.append("\n")
    return "".join(texts)


def extract_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.startswith("word/") and n.endswith(".xml")]
            parts = []
            for name in names:
                if name.startswith(("word/document", "word/header", "word/footer")):
                    parts.append(_text_from_xml_bytes(zf.read(name)))
            return "\n".join(parts)
    except Exception:
        return ""


def extract_pptx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            names = sorted(n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml"))
            return "\n".join(_text_from_xml_bytes(zf.read(name)) for name in names)
    except Exception:
        return ""


def extract_xlsx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            shared = []
            if "xl/sharedStrings.xml" in zf.namelist():
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                for si in root:
                    vals = [node.text or "" for node in si.iter() if node.tag.endswith("}t")]
                    shared.append("".join(vals))
            rows = []
            sheet_names = sorted(n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
            for sheet_name in sheet_names:
                root = ET.fromstring(zf.read(sheet_name))
                for row in root.iter():
                    if not row.tag.endswith("}row"):
                        continue
                    cells = []
                    for c in row:
                        if not c.tag.endswith("}c"):
                            continue
                        cell_type = c.attrib.get("t")
                        value = ""
                        for child in c:
                            if child.tag.endswith("}v") and child.text:
                                value = child.text
                                break
                        if cell_type == "s":
                            try:
                                value = shared[int(value)]
                            except Exception:
                                pass
                        if value:
                            cells.append(value)
                    if cells:
                        rows.append("\t".join(cells))
            return "\n".join(rows)
    except Exception:
        return ""


def extract_txt(path: Path) -> str:
    for encoding in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            return path.read_text(encoding=encoding, errors="ignore")
        except Exception:
            continue
    return ""


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:12000]


def priority_score(path: Path) -> int:
    name = str(path)
    score = sum(10 for kw in KEYWORDS if kw in name)
    ext = path.suffix.lower()
    if ext in {".docx", ".xlsx", ".pptx", ".txt"}:
        score += 30
    if ext == ".pdf":
        score += 8
    if "从小散到游资的49堂课" in name:
        score += 25
    if "悟道心法" in name:
        score += 20
    return score


def theme_hits(text: str) -> dict:
    return {theme: sum(text.count(word) for word in words) for theme, words in THEME_PATTERNS.items()}


def main() -> None:
    if not SOURCE_ROOT.exists():
        raise SystemExit(f"source root not found: {SOURCE_ROOT}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    files = [p for p in SOURCE_ROOT.rglob("*") if p.is_file()]
    by_ext = Counter(p.suffix.lower() or "<none>" for p in files)

    parsed = []
    unsupported = Counter()
    candidates = sorted(files, key=lambda p: (priority_score(p), -p.stat().st_size), reverse=True)
    for path in candidates:
        ext = path.suffix.lower()
        if ext not in {".docx", ".pptx", ".xlsx", ".txt"}:
            unsupported[ext or "<none>"] += 1
            continue
        if len(parsed) >= 180:
            break
        if ext == ".docx":
            text = extract_docx(path)
        elif ext == ".pptx":
            text = extract_pptx(path)
        elif ext == ".xlsx":
            text = extract_xlsx(path)
        else:
            text = extract_txt(path)
        text = clean_text(text)
        if not text:
            continue
        rel = str(path.relative_to(SOURCE_ROOT))
        parsed.append(
            {
                "relative_path": rel,
                "extension": ext,
                "size": path.stat().st_size,
                "priority": priority_score(path),
                "char_count": len(text),
                "theme_hits": theme_hits(text),
                "preview": text[:700],
            }
        )

    totals = Counter()
    for item in parsed:
        totals.update(item["theme_hits"])

    report = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_root": str(SOURCE_ROOT),
        "file_count": len(files),
        "file_count_by_type": dict(sorted(by_ext.items())),
        "parsed_count": len(parsed),
        "unsupported_or_deferred_by_type": dict(sorted(unsupported.items())),
        "theme_hit_totals": dict(totals),
        "parsed_documents": parsed,
        "notes": [
            "PDF、图片、音视频和旧版 .xls/.doc/.ppt 本轮只做文件索引，未做 OCR/音视频转写。",
            "本脚本只读取源目录，输出写入项目 backend/data/ai/youzi_trade_notes。",
        ],
    }
    out_path = OUTPUT_DIR / "youzi_extraction_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(out_path), "parsed_count": len(parsed), "file_count": len(files)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
