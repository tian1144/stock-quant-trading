"""
Extract key frames from high-priority youzi videos for OCR.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = Path(r"E:\迅雷\下载目录\游资交割单")
VIDEO_INDEX = ROOT / "backend" / "data" / "ai" / "youzi_trade_notes" / "video" / "video_index.json"
OUT_DIR = ROOT / "backend" / "data" / "ai" / "youzi_trade_notes" / "video" / "frames"
REPORT = ROOT / "backend" / "data" / "ai" / "youzi_trade_notes" / "video" / "video_frame_report.json"
FFMPEG = Path(r"E:\ffmpeg\ffmpeg-n7.1-latest-win64-gpl-shared-7.1\bin\ffmpeg.exe")


def frame_times(duration: float) -> list[float]:
    if duration <= 0:
        return [5, 20, 45]
    if duration <= 600:
        ratios = [0.12, 0.28, 0.45, 0.62, 0.78, 0.9]
    else:
        ratios = [0.04, 0.12, 0.22, 0.35, 0.5, 0.65, 0.78, 0.9]
    return sorted({max(2.0, min(duration - 2.0, round(duration * r, 2))) for r in ratios})


def extract_frame(video_path: Path, out_path: Path, second: float) -> str:
    cmd = [
        str(FFMPEG),
        "-y",
        "-ss",
        str(second),
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        "scale=1600:-1",
        "-q:v",
        "2",
        str(out_path),
    ]
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=60)
        return ""
    except subprocess.CalledProcessError as exc:
        return exc.output.decode("utf-8", errors="ignore")[-500:]
    except Exception as exc:
        return str(exc)


def main(limit: int = 8) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index = json.loads(VIDEO_INDEX.read_text(encoding="utf-8"))
    videos = index.get("rows", [])[:limit]
    rows = []
    for video in videos:
        video_path = SOURCE_ROOT / video["relative_path"]
        folder = OUT_DIR / video["video_id"]
        folder.mkdir(parents=True, exist_ok=True)
        generated = []
        errors = []
        for second in frame_times(float(video.get("duration_seconds") or 0)):
            frame_name = f"{video['video_id']}_{int(second):06d}.jpg"
            out_path = folder / frame_name
            err = extract_frame(video_path, out_path, second)
            if err:
                errors.append({"second": second, "error": err})
            else:
                generated.append({"second": second, "path": str(out_path)})
        rows.append({
            "video_id": video["video_id"],
            "relative_path": video["relative_path"],
            "themes": video.get("themes", ""),
            "priority_score": video.get("priority_score", 0),
            "frame_count": len(generated),
            "frames": generated,
            "errors": errors,
        })
    REPORT.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(REPORT), "videos": len(rows), "frames": sum(r["frame_count"] for r in rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
