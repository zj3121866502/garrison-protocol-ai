"""P1 step-1 first increment: shop-region OCR from rest-phase frames.

Usage:
  python ocr_shop.py <analysis_dir> --frames 457,484
  python ocr_shop.py <analysis_dir> --auto 6        # sample N rest frames from curves

Contract = model/state.py ShopSlot / State.funds (read-only anchor, peer-owned).
This increment extracts: funds + 5 shop slots (name + covenant tags + price best
effort) with scene gating. tier / center_level / upgrade_price precise geometry
= next increment (null here, degrade not guess).

Measured geometry (224824 f457, 1920x1080; see notes/20261118-P1商店OCR方案.md §10):
  shop 5 slot x-centers ~ [691, 873, 1092, 1310, 1529]
  name banner y~1021, covenant tags y~963/987, price red badge bottom-left y~1055
  funds gold badge x~1810 y~822; refresh x1835 y728 / freeze x1634 y729 / upgrade x496 y997
Scene gate: clean shop = 刷新 + 升级 present AND no operator-detail panel
(攻击/防御/法抗 text absent). f484 has the detail panel -> skipped.

Price digits are RED on a blue ticket badge -> plain OCR weak; use red-channel
enhancement (R as grayscale) then rec-only OCR. Unreadable -> null.

Output: shop.json (list per frame) + shop/f{i}_card{n}.png crops for user check.
Main-agent lane (P1). Offline read-only: never injects input.
"""
import argparse
import io
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

SLOT_X = [691, 873, 1092, 1310, 1529]
NAME_Y = (1005, 1040)
TAG_Y = (950, 1000)
FUNDS_BOX = (1780, 800, 1845, 845)
GARBAGE = re.compile(r"CLOS|SOPL|SYSTEM|RHODES|^[A-Z]{1,2}$", re.I)


def lines_of(res):
    return [{"text": t, "x": round(sum(p[0] for p in b) / 4, 1),
             "y": round(sum(p[1] for p in b) / 4, 1)} for b, t, _ in res]


def clean_shop(ls):
    joined = "|".join(l["text"] for l in ls)
    has_btn = ("刷新" in joined) and ("升级" in joined)
    detail = ("攻击" in joined) and ("防御" in joined)
    return has_btn and not detail


def red_digit(img, box, rec):
    """Red-channel emphasis for the red price digit on blue badge."""
    a = np.asarray(img.crop(box).convert("RGB")).astype(int)
    r = np.clip(a[:, :, 0] * 2 - a[:, :, 1] - a[:, :, 2], 0, 255).astype(np.uint8)
    im = Image.fromarray(r).resize(((box[2] - box[0]) * 4, (box[3] - box[1]) * 4), Image.NEAREST)
    res, _ = rec(im)
    txt = "".join(item[1] if len(item) == 3 else item[0] for item in (res or [])).strip()
    m = re.fullmatch(r"\d{1,2}", txt)
    return int(m.group(0)) if m else None


def extract(img, ls, i, out, rec):
    rec_out = {"frame": i, "shop_state": "clean", "funds": None,
               "center_level": None, "upgrade_price": None, "slots": []}
    for l in ls:
        if not (FUNDS_BOX[0] <= l["x"] <= FUNDS_BOX[2]
                and FUNDS_BOX[1] <= l["y"] <= FUNDS_BOX[3]):
            continue
        # Gold-badge 0 is frequently OCR'd as letter O/o (trial 2026-11-18: funds=0
        # read as "O" -> null -> model recommended buys at zero funds). Normalize
        # O/o->0 before the digit match so a zero balance is perceived as 0.
        txt = l["text"].strip().replace("O", "0").replace("o", "0")
        if re.fullmatch(r"\d{1,3}", txt):
            rec_out["funds"] = int(txt)
    if out is not None:
        (out / "shop").mkdir(exist_ok=True)
    names = [l for l in ls if NAME_Y[0] <= l["y"] <= NAME_Y[1] and not GARBAGE.search(l["text"])]
    for n, cx in enumerate(SLOT_X, 1):
        nm = [l for l in names if abs(l["x"] - cx) <= 80]
        name = min(nm, key=lambda l: abs(l["x"] - cx))["text"] if nm else None
        tags = [l["text"] for l in ls if TAG_Y[0] <= l["y"] <= TAG_Y[1]
                and abs(l["x"] - cx) <= 80 and not GARBAGE.search(l["text"])]
        # Price red-badge digit is small/stylized; plain+red-enhanced OCR proved
        # unreliable (stray 0/5). Degrade to null this increment; dedicated digit
        # calibration (template glyphs / better enhancement) = next increment.
        price = None
        if out is not None:
            img.crop((cx - 100, 935, cx + 100, 1075)).save(out / "shop" / f"f{i}_card{n}.png")
        rec_out["slots"].append({"slot": n, "x": cx, "name": name, "tags": tags,
                                 "price": price, "tier": None,
                                 "frozen": False, "sold": False})
    return rec_out


def read_shop_frame(img, ocr, rec, i=0, out=None):
    """Single-frame shop OCR -> rec_out dict, or {"shop_state":"obscured_or_not_rest"}
    when the scene gate fails (detail panel / not clean shop). Shared by batch
    main() and the live trial-run watcher. out=None skips card-crop saving (live
    mode reads on demand, no disk crops). OCR algorithm unchanged."""
    res, _ = ocr(img)
    ls = lines_of(res or [])
    if not clean_shop(ls):
        return {"frame": i, "shop_state": "obscured_or_not_rest"}
    return extract(img, ls, i, out, rec)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("analysis_dir")
    ap.add_argument("--frames", default="")
    ap.add_argument("--auto", type=int, default=0)
    args = ap.parse_args()
    out = Path(args.analysis_dir)
    sess = out.parent.parent / "raw" / out.name
    ocr = RapidOCR(det_use_dml=True, rec_use_dml=True, use_cls=False)
    rec = RapidOCR(rec_use_dml=True, use_cls=False, use_det=False)

    if args.frames:
        idx = [int(x) for x in args.frames.split(",") if x.strip()]
    elif args.auto:
        rows = [json.loads(l) for l in (out / "curves.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        rest = [r["i"] for r in rows if r.get("phase") == "rest" and r.get("round") is not None]
        step = max(1, len(rest) // args.auto)
        idx = rest[::step][:args.auto]
    else:
        print("[shop] give --frames or --auto")
        return

    results = []
    for i in idx:
        fp = sess / "frames" / f"f{i:06d}.png"
        if not fp.exists():
            continue
        img = Image.open(fp)
        r = read_shop_frame(img, ocr, rec, i, out)
        results.append(r)
        if r.get("shop_state") != "clean":
            print(f"[shop] f{i}: skipped (detail panel / not clean shop)")
            continue
        ss = ", ".join(f"s{s['slot']}={s['name']}/{s['price']}" for s in r["slots"])
        print(f"[shop] f{i}: funds={r['funds']} | {ss}")
    with io.open(out / "shop.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print(f"[shop] wrote {out / 'shop.json'} ({len(results)} frames)")


if __name__ == "__main__":
    main()