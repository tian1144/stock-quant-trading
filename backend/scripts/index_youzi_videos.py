"""
Index youzi video files for later transcription/OCR learning.
"""
from __future__ import annotations

import csv
import json
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = Path(r"E:\迅雷\下载目录\游资交割单")
OUT_DIR = ROOT / "backend" / "data" / "ai" / "youzi_trade_notes" / "video"
OUT_JSON = OUT_DIR / "video_index.json"
OUT_CSV = OUT_DIR / "video_index.csv"
FFPROBE = Path(r"E:\ffmpeg\ffmpeg-n7.1-latest-win64-gpl-shared-7.1\bin\ffprobe.exe")
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".wmv", ".flv", ".m4v", ".ts"}


THEME_KEYWORDS = {
    "announcement": ["公告", "信息", "消息"],
    "watch_tape": ["看盘", "盘中", "异动", "盘口"],
    "leader_hotspot": ["龙头", "热点", "板块", "主线"],
    "entry_setup": ["低吸", "买入", "建仓", "拉升", "共振", "针尖"],
    "exit_risk": ["卖出", "出货", "止损", "仓位", "纪律", "回撤"],
    "mindset_review": ["情绪", "复盘", "生存法则", "原则"],
}


def probe_video(path: Path) -> dict:
    if not FFPROBE.exists():
        return {"duration_seconds": 0, "width": 0, "height": 0, "probe_error": "ffprobe_missing"}
    cmd = [
        str(FFPROBE),
        "-v", "error",
        "-show_entries", "format=duration:stream=width,height,codec_type",
        "-of", "json",
        str(path),
    ]
    try:
        raw = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=40)
        info = json.loads(raw.decode("utf-8", errors="ignore") or "{}")
        streams = info.get("streams") or []
        video = next((s for s in streams if s.get("codec_type") == "video"), {})
        return {
            "duration_seconds": round(float((info.get("format") or {}).get("duration") or 0), 2),
            "width": int(video.get("width") or 0),
            "height": int(video.get("height") or 0),
            "probe_error": "",
        }
    except Exception as exc:
        return {"duration_seconds": 0, "width": 0, "height": 0, "probe_error": str(exc)[:180]}


def classify_theme(text: str) -> tuple[list[str], int]:
    themes: list[str] = []
    score = 0
    for theme, words in THEME_KEYWORDS.items():
        hits = sum(1 for word in words if word in text)
        if hits:
            themes.append(theme)
            score += hits * 10
    if any(key in text for key in ["公告战法", "看盘", "龙头", "低吸", "仓位", "止损", "出货"]):
        score += 25
    if any(key in text for key in ["音频", "赠品"]):
        score -= 4
    return themes or ["general"], max(0, score)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in SOURCE_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTS:
            continue
        rel = str(path.relative_to(SOURCE_ROOT))
        themes, priority = classify_theme(rel)
        meta = probe_video(path)
        rows.append({
            "video_id": f"video-{len(rows)+1:04d}",
            "relative_path": rel,
            "extension": path.suffix.lower(),
            "size_mb": round(path.stat().st_size / 1024 / 1024, 2),
            "duration_seconds": meta["duration_seconds"],
            "duration_minutes": round(meta["duration_seconds"] / 60, 2),
            "width": meta["width"],
            "height": meta["height"],
            "themes": " | ".join(themes),
            "priority_score": priority,
            "probe_error": meta["probe_error"],
        })
    rows.sort(key=lambda r: (r["priority_score"], r["size_mb"]), reverse=True)
    payload = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_root": str(SOURCE_ROOT),
        "video_count": len(rows),
        "ffprobe": str(FFPROBE),
        "rows": rows,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = list(rows[0].keys()) if rows else ["video_id", "relative_path"]
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(json.dumps({"json": str(OUT_JSON), "csv": str(OUT_CSV), "video_count": len(rows), "top": rows[:8]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
