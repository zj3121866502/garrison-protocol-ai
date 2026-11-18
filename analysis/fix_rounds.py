"""Re-read round numbers the main OCR missed (black digit on cyan folder icon).

Usage: python fix_rounds.py <analysis_dir>
Scans hud.jsonl for in-game rows (has '回合') with no round digit, binarizes
the cyan folder zone to black-on-white, upscales and OCRs it (rec only).
Output: rounds_fix.jsonl {i, round}  -- merged by parse_hud.py, hud.jsonl untouched.
"""
import argparse
import io
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

ZONE = (740, 25, 830, 65)  # full-frame coords around the folder icon


def folder_digit(img, ocr):
    a = np.asarray(img.convert("RGB")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    cyan = (g > 140) & (b > 100) & (r < 120) & ((g - r) > 60)
    ys, xs = np.where(cyan)
    if len(xs) < 50:
        return None
    x0, x1 = max(xs.min() - 2, 0), min(xs.max() + 3, a.shape[1])
    y0, y1 = max(ys.min() - 2, 0), min(ys.max() + 3, a.shape[0])
    sub = cyan[y0:y1, x0:x1]
    bw = np.where(sub, 255, 0).astype(np.uint8)
    im = Image.fromarray(bw).resize(((x1 - x0) * 4, (y1 - y0) * 4), Image.NEAREST)
    res, _ = ocr(im)
    if not res:
        return None
    txt = "".join(item[1] if len(item) == 3 else item[0] for item in res)
    m = re.search(r"\d+", txt)
    return int(m.group(0)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("analysis_dir")
    args = ap.parse_args()
    out = Path(args.analysis_dir)
    sess = out.parent.parent / "raw" / out.name
    rows = [json.loads(l) for l in io.open(out / "hud.jsonl", encoding="utf-8")]
    todo = []
    for r in rows:
        has_tag = any("回合" in l["text"] for l in r["lines"])
        has_num = any(re.match(r"^\d+$", l["text"]) and 250 <= l["x"] <= 295
                      and 35 <= l["y"] <= 55 for l in r["lines"])
        merged = any(re.match(r"^回合\d+$", l["text"]) for l in r["lines"])
        if has_tag and not has_num and not merged:
            todo.append(r["i"])
    ocr = RapidOCR(det_use_dml=True, rec_use_dml=True, use_cls=False, use_det=False)
    fixed = {}
    for i in todo:
        img = Image.open(sess / "frames" / f"f{i:06d}.png").crop(ZONE)
        d = folder_digit(img, ocr)
        if d is not None:
            fixed[i] = d
    with io.open(out / "rounds_fix.jsonl", "w", encoding="utf-8") as f:
        for i, d in sorted(fixed.items()):
            f.write(json.dumps({"i": i, "round": d}) + "\n")
    vals = sorted(set(fixed.values()))
    print(f"[fix] {out.name}: missing={len(todo)} recovered={len(fixed)} rounds={vals}")


if __name__ == "__main__":
    main()