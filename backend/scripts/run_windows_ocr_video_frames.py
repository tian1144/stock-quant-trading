"""
Run Windows OCR on extracted video frames.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRAME_REPORT = ROOT / "backend" / "data" / "ai" / "youzi_trade_notes" / "video" / "video_frame_report.json"
OUT_REPORT = ROOT / "backend" / "data" / "ai" / "youzi_trade_notes" / "video" / "video_frame_ocr_report.json"
OCR_PS1 = ROOT / "backend" / "scripts" / "ocr_image_winrt.ps1"


def run_ocr(path: str) -> dict:
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(OCR_PS1),
        "-ImagePath",
        path,
    ]
    try:
        raw = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=45)
        text = raw.decode("utf-8", errors="ignore").strip()
        if text.startswith("{"):
            return json.loads(text)
        return {"ok": False, "text": text, "error": "non_json_ocr_output"}
    except subprocess.CalledProcessError as exc:
        return {"ok": False, "error": exc.output.decode("utf-8", errors="ignore")[-500:]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main() -> None:
    report = json.loads(FRAME_REPORT.read_text(encoding="utf-8"))
    rows = []
    for video in report.get("rows", []):
        ocr_frames = []
        combined = []
        for frame in video.get("frames", []):
            result = run_ocr(frame["path"])
            text = (result.get("text") or result.get("Text") or "").strip()
            if text:
                combined.append(text)
            ocr_frames.append({
                "second": frame.get("second"),
                "path": frame.get("path"),
                "ok": result.get("ok", bool(text)),
                "char_count": len(text),
                "text": text[:1200],
                "error": result.get("error", ""),
            })
        rows.append({
            "video_id": video.get("video_id"),
            "relative_path": video.get("relative_path"),
            "themes": video.get("themes", ""),
            "priority_score": video.get("priority_score", 0),
            "frame_count": video.get("frame_count", 0),
            "ocr_char_count": sum(item["char_count"] for item in ocr_frames),
            "frames": ocr_frames,
            "combined_preview": "\n".join(combined)[:4000],
        })
    payload = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rows": rows,
        "usable_videos": sum(1 for row in rows if row["ocr_char_count"] >= 80),
        "total_chars": sum(row["ocr_char_count"] for row in rows),
    }
    OUT_REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(OUT_REPORT), "usable_videos": payload["usable_videos"], "total_chars": payload["total_chars"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
