"""Analyze a recorded session: click stats, scene segmentation, contact sheets.

Usage: python analyze_session.py <session_dir> [--out DIR] [--threshold 12]
Outputs (to out dir):
  stats.json      click timeline + position clusters
  scenes.json     scene table (frame ranges, durations, clicks, rep frame)
  diffs.jsonl     per-frame mean abs diff vs previous frame
  sheets/sheetNN.png  contact sheets of scene representative frames
Console output: English ASCII.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

THUMB_W, THUMB_H = 480, 270
GRID_COLS, GRID_ROWS = 4, 3  # 12 scenes per sheet


def load_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def click_stats(clicks, t0):
    downs = [c for c in clicks if c["event"] == "down"]
    per_min = Counter(int((c["t"] - t0) // 60) for c in downs)
    grid = Counter((c["x"] // 80 * 80, c["y"] // 80 * 80) for c in downs)
    return {
        "total_events": len(clicks),
        "total_clicks": len(downs),
        "per_minute": {str(k): v for k, v in sorted(per_min.items())},
        "top_positions_80px_grid": [
            {"x": x, "y": y, "n": n} for (x, y), n in grid.most_common(25)
        ],
    }


def segment(frames, threshold):
    prev = None
    diffs = []
    cuts = [1]  # frame numbers 1-based throughout (single caliber with hud.jsonl)
    for idx, fr in enumerate(frames):
        img = Image.open(fr["file"]).convert("L").resize((160, 90))
        arr = np.asarray(img, dtype=np.float32)
        d = float(np.abs(arr - prev).mean()) if prev is not None else 0.0
        diffs.append(d)
        if idx > 0 and d >= threshold:
            cuts.append(idx + 1)
        prev = arr
    cuts.append(len(frames) + 1)
    scenes = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        if b - a < 2 and scenes:
            scenes[-1]["end"] = b - 1
            continue
        scenes.append({"start": a, "end": b - 1})
    return scenes, diffs


def enrich(scenes, frames, clicks, t0):
    downs = [c for c in clicks if c["event"] == "down"]
    for s in scenes:
        a, b = s["start"] - 1, s["end"] - 1  # scenes carry 1-based frame numbers
        s["n_frames"] = b - a + 1
        s["t_start"] = round(frames[a]["t"] - t0, 1)
        s["t_end"] = round(frames[b]["t"] - t0, 1)
        s["duration_s"] = s["n_frames"]
        s["rep"] = (a + b) // 2 + 1
        s["rep_file"] = frames[s["rep"] - 1]["file"]
        ta, tb = frames[a]["t"], frames[b]["t"] + 1.0
        s["clicks"] = sum(1 for c in downs if ta <= c["t"] < tb)
    return scenes


def make_sheets(scenes, out_dir):
    sheets_dir = out_dir / "sheets"
    sheets_dir.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    paths = []
    per_sheet = GRID_COLS * GRID_ROWS
    for si in range(0, len(scenes), per_sheet):
        chunk = scenes[si:si + per_sheet]
        sheet = Image.new("RGB", (GRID_COLS * THUMB_W, GRID_ROWS * (THUMB_H + 30)), (24, 24, 24))
        draw = ImageDraw.Draw(sheet)
        for j, s in enumerate(chunk):
            col, row = j % GRID_COLS, j // GRID_COLS
            x, y = col * THUMB_W, row * (THUMB_H + 30)
            thumb = Image.open(s["rep_file"]).convert("RGB").resize((THUMB_W, THUMB_H))
            sheet.paste(thumb, (x, y + 30))
            label = f"#{si + j}  f{s['start']}-{s['end']}  t={s['t_start']:.0f}s  clicks={s['clicks']}"
            draw.text((x + 6, y + 4), label, fill=(255, 220, 80), font=font)
        p = sheets_dir / f"sheet{si // per_sheet:02d}.png"
        sheet.save(p)
        paths.append(str(p))
    return paths


def main():
    sys.stdout.reconfigure(errors="replace", line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("session_dir")
    ap.add_argument("--out", default=None)
    ap.add_argument("--threshold", type=float, default=12.0)
    args = ap.parse_args()

    sess = Path(args.session_dir)
    out = Path(args.out) if args.out else Path("E:/garrison-ai/data/analysis") / sess.name
    out.mkdir(parents=True, exist_ok=True)

    meta = json.loads((sess / "meta.json").read_text(encoding="utf-8"))
    frames = load_jsonl(sess / "frames.jsonl")
    clicks = load_jsonl(sess / "clicks.jsonl")
    for fr in frames:
        fr["file"] = str(sess / fr["file"]) if not Path(fr["file"]).is_absolute() else fr["file"]
    t0 = meta["start"]
    print(f"[load] frames={len(frames)} clicks={len(clicks)} duration={meta.get('end', 0) - t0:.0f}s")

    stats = click_stats(clicks, t0)
    (out / "stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    print(f"[clicks] {stats['total_clicks']} clicks; per-minute: {stats['per_minute']}")

    print("[segment] computing frame diffs ...")
    scenes, diffs = segment(frames, args.threshold)
    with open(out / "diffs.jsonl", "w", encoding="utf-8") as f:
        for i, d in enumerate(diffs):
            f.write(json.dumps({"i": i + 1, "diff": round(d, 2)}) + "\n")
    scenes = enrich(scenes, frames, clicks, t0)
    (out / "scenes.json").write_text(json.dumps(scenes, indent=1), encoding="utf-8")
    print(f"[segment] {len(scenes)} scenes at threshold={args.threshold}")
    for i, s in enumerate(scenes):
        print(f"  scene {i:3d}: f{s['start']:4d}-{s['end']:4d} t={s['t_start']:6.0f}-{s['t_end']:6.0f}s clicks={s['clicks']:3d}")

    print("[sheets] building contact sheets ...")
    paths = make_sheets(scenes, out)
    for p in paths:
        print(f"  {p}")
    print(f"[done] analysis dir: {out}")


if __name__ == "__main__":
    main()