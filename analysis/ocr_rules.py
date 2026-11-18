"""OCR the in-game rule book (卫戍协议[规程]) out of a recorded session.

Crops the rule-book panel from each 1fps frame, runs RapidOCR, detects
which left-nav section is active (teal highlight), merges consecutive
identical screens (scroll pauses) and writes a readable transcript.

Usage:
    python ocr_rules.py --session E:/garrison-ai/data/raw/session-XXXX
"""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

# frames are 1920x1080; panel crop in full-frame coordinates
CROP = (90, 85, 1840, 1040)
NAV_X = 430  # crop-x split: left nav column vs content column
# active-tab teal text band centers (full-frame y), measured from f000030
TAB_CENTERS = [("基础规则", 313), ("模拟细则", 441), ("战斗细则", 568), ("协议规则", 696)]


def active_section(img, nav_texts):
    if any("协议开放" in t for t in nav_texts):
        return "更新日志"
    a = np.asarray(img.convert("RGB")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mask = (g > 140) & (b > 100) & (r < 120) & ((g - r) > 60)
    # left nav column in crop coordinates
    rows = mask[:, 20:420].sum(axis=1)
    ys = np.where(rows > 3)[0]
    bands = []
    for y in ys:
        if bands and y - bands[-1][1] <= 5:
            bands[-1][1] = y
        else:
            bands.append([y, y])
    big = [bd for bd in bands if bd[1] - bd[0] >= 50]
    if not big:
        return "?"
    cy = (big[0][0] + big[0][1]) / 2 + CROP[1]
    return min(TAB_CENTERS, key=lambda tc: abs(tc[1] - cy))[0]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--session", required=True)
    p.add_argument("--out", default=None)
    args = p.parse_args()
    sess = Path(args.session)
    out = Path(args.out) if args.out else Path(r"E:/garrison-ai/data/analysis") / sess.name
    out.mkdir(parents=True, exist_ok=True)

    ocr = RapidOCR(det_use_dml=True, cls_use_dml=True, rec_use_dml=True)
    rows = [json.loads(l) for l in open(sess / "frames.jsonl", encoding="utf-8")]
    screens = []
    with open(out / "ocr.jsonl", "w", encoding="utf-8") as fj:
        for r in rows:
            img = Image.open(sess / r["file"]).crop(CROP)
            res, _ = ocr(img)
            lines = []
            if res:
                for box, text, score in res:
                    ys = [pt[1] for pt in box]
                    xs = [pt[0] for pt in box]
                    lines.append(
                        {"y": round(sum(ys) / 4, 1), "x": round(sum(xs) / 4, 1),
                         "text": text, "score": round(float(score), 3)}
                    )
            lines.sort(key=lambda l: (l["y"], l["x"]))
            nav = [l["text"] for l in lines if l["x"] < NAV_X]
            content = [l for l in lines if l["x"] >= NAV_X]
            section = active_section(img, nav)
            rec = {"i": r["i"], "t": round(r["t"], 1), "section": section,
                   "nav": nav, "lines": content}
            fj.write(json.dumps(rec, ensure_ascii=False) + "\n")
            key = tuple(l["text"] for l in content)
            if screens and screens[-1]["key"] == key and screens[-1]["section"] == section:
                screens[-1]["end"] = r["i"]
                screens[-1]["t_end"] = rec["t"]
            else:
                screens.append({"start": r["i"], "end": r["i"], "t_start": rec["t"],
                                "t_end": rec["t"], "section": section, "key": key,
                                "lines": content})
            if r["i"] % 20 == 0:
                print(f"[ocr] frame {r['i']}/{len(rows)} section={section} lines={len(content)}", flush=True)

    with open(out / "screens.md", "w", encoding="utf-8") as f:
        for k, s in enumerate(screens):
            f.write(f"\n## screen {k:02d}  f{s['start']:03d}-f{s['end']:03d}  "
                    f"t={s['t_start']:.0f}-{s['t_end']:.0f}s  section={s['section']}\n")
            for l in s["lines"]:
                f.write(f"- {l['text']}\n")

    # stitch scroll screens into continuous per-section text via overlap alignment
    runs = []
    for s in screens:
        if s["section"] == "?":
            continue
        if runs and runs[-1]["section"] == s["section"]:
            runs[-1]["screens"].append(s)
            runs[-1]["end"] = s["end"]
        else:
            runs.append({"section": s["section"], "start": s["start"],
                         "end": s["end"], "screens": [s]})
    with open(out / "stitched.md", "w", encoding="utf-8") as f:
        for run in runs:
            f.write(f"\n# {run['section']}  f{run['start']:03d}-f{run['end']:03d}\n")
            cur = [l["text"].strip() for l in run["screens"][0]["lines"]]
            for s in run["screens"][1:]:
                nxt = [l["text"].strip() for l in s["lines"]]
                joined = False
                for skip_prev, skip_next in ((0, 0), (0, 1), (1, 0)):
                    a = cur[:len(cur) - skip_prev] if skip_prev else cur
                    for o in range(min(len(a), len(nxt) - skip_next), 1, -1):
                        if a[-o:] == nxt[skip_next:skip_next + o]:
                            base = cur[:-1] if skip_prev else cur
                            cur = base + nxt[skip_next + o:]
                            joined = True
                            break
                    if joined:
                        break
                if not joined:
                    cur = cur + ["── 滚动跳变 ──"] + nxt
            for line in cur:
                f.write(line + "\n")
    print(f"[done] {len(rows)} frames -> {len(screens)} screens, {len(runs)} section runs")
    print(f"[done] transcript: {out / 'screens.md'}")
    print(f"[done] stitched:   {out / 'stitched.md'}")


if __name__ == "__main__":
    main()