"""Re-section + re-stitch rule-book OCR results (no re-OCR).

Reads ocr.jsonl produced by ocr_rules.py, gates rule-book presence on the
left-nav text (teal highlights alone false-positive on Qoder sidebar /
menu icons), detects the active tab via the teal band inside the tab
zone, merges identical screens and stitches scroll overlaps.

Usage:
    python restitch_rules.py --session E:/garrison-ai/data/raw/session-XXXX
"""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

TAB_NAMES = ("基础规则", "模拟细则", "战斗细则", "协议规则")
TAB_CENTERS = [("基础规则", 313), ("模拟细则", 441), ("战斗细则", 568), ("协议规则", 696)]
CROP_TOP = 85


def section_of(img, nav):
    if sum(n.strip() in TAB_NAMES for n in nav) >= 3:
        a = np.asarray(img.convert("RGB")).astype(int)
        r, g, b = a[..., 0], a[..., 1], a[..., 2]
        mask = (g > 140) & (b > 100) & (r < 120) & ((g - r) > 60)
        rows = mask[250 - CROP_TOP:760 - CROP_TOP, 20:420].sum(axis=1)
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
        cy = (big[0][0] + big[0][1]) / 2 + 250
        return min(TAB_CENTERS, key=lambda tc: abs(tc[1] - cy))[0]
    if any("协议开放" in n for n in nav):
        return "更新日志"
    return "other"


def stitch(screens):
    cur = [l["text"].strip() for l in screens[0]["lines"]]
    for s in screens[1:]:
        nxt = [l["text"].strip() for l in s["lines"]]
        joined = False
        for skip_prev, skip_next in ((0, 0), (0, 1), (1, 0)):
            a = cur[:-1] if skip_prev else cur
            for o in range(min(len(a), len(nxt) - skip_next), 1, -1):
                if a[-o:] == nxt[skip_next:skip_next + o]:
                    cur = (cur[:-1] if skip_prev else cur) + nxt[skip_next + o:]
                    joined = True
                    break
            if joined:
                break
        if not joined:
            cur = cur + ["── 滚动跳变 ──"] + nxt
    return cur


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--session", required=True)
    p.add_argument("--out", default=None)
    args = p.parse_args()
    sess = Path(args.session)
    out = Path(args.out) if args.out else Path(r"E:/garrison-ai/data/analysis") / sess.name

    rows = []
    for l in open(out / "ocr.jsonl", encoding="utf-8"):
        try:
            rows.append(json.loads(l))
        except json.JSONDecodeError:
            pass  # tail line still being written by a concurrent OCR run
    screens = []
    for r in rows:
        img = Image.open(sess / f"frames/f{r['i']:06d}.png").crop((90, 85, 1840, 1040))
        sec = section_of(img, r["nav"])
        key = tuple(l["text"] for l in r["lines"])
        if screens and screens[-1]["key"] == key and screens[-1]["section"] == sec:
            screens[-1]["end"] = r["i"]
        else:
            screens.append({"start": r["i"], "end": r["i"], "section": sec,
                            "key": key, "lines": r["lines"]})

    runs = []
    for s in screens:
        if s["section"] in ("other", "?"):
            continue
        if runs and runs[-1]["section"] == s["section"]:
            runs[-1]["screens"].append(s)
            runs[-1]["end"] = s["end"]
        else:
            runs.append({"section": s["section"], "start": s["start"],
                         "end": s["end"], "screens": [s]})

    with open(out / "stitched.md", "w", encoding="utf-8") as f:
        for run in runs:
            f.write(f"\n# {run['section']}  f{run['start']:03d}-f{run['end']:03d}  "
                    f"({len(run['screens'])} screens)\n")
            for line in stitch(run["screens"]):
                f.write(line + "\n")
    with open(out / "screens2.md", "w", encoding="utf-8") as f:
        for k, s in enumerate(screens):
            f.write(f"\n## screen {k:03d}  f{s['start']:03d}-f{s['end']:03d}  section={s['section']}\n")
            for l in s["lines"]:
                f.write(f"- {l['text']}\n")
    print(f"[done] {len(rows)} frames -> {len(screens)} screens -> {len(runs)} runs")
    for run in runs:
        print(f"  {run['section']}: f{run['start']:03d}-f{run['end']:03d} ({len(run['screens'])} screens)")
    print(f"[done] {out / 'stitched.md'}")


if __name__ == "__main__":
    main()