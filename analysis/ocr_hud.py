"""Extract top HUD strip (round / funds / life / covenant layer counters) per frame via OCR.

Usage: python ocr_hud.py <session_dir> --out <analysis_dir> [--aligned]
Output: hud.jsonl  {i, t, lines:[{text,x,y,score}]}  (crop coords)
--aligned: OCR only the frames a training sample actually needs -- the last
frame captured at or before each click (bisect on frames.jsonl timestamps;
frame numbers are 1-based), scene-boundary frames (diff>=25: round
banners / phase switches / panel opens), and the first/last frames (settlement).
Already-extracted lines in hud.jsonl are reused; only missing needed frames run.
Parse covenant counters later by name proximity; parse_hud keeps only
in-round rows (round != None) in curves.jsonl -- menu/strategy/settlement
frames are excluded there (settlement counters belong to parse_settlement).
hud rows carry synthetic t=start+i for continuity plus t_real (frames.jsonl
timestamp) when available; frames.jsonl remains the P3 time authority.
"""
import argparse
import bisect
import io
import json
import sys
from pathlib import Path

from PIL import Image
from rapidocr_onnxruntime import RapidOCR

CROP = (500, 0, 1450, 200)


def ocr_frame(img, ocr):
    """Single-frame HUD OCR -> lines [{text,x,y,score}] in CROP-relative coords.
    img = full-frame PIL Image. Shared by batch main() and the live trial-run
    watcher (analysis/live_advisor.py); algorithm unchanged, just callable per
    frame on demand. Coords stay CROP-relative so parse_hud.parse_row applies."""
    res, _ = ocr(img.crop(CROP))
    lines = []
    if res:
        for box, text, score in res:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            lines.append({"text": text, "x": round(sum(xs) / 4, 1),
                          "y": round(sum(ys) / 4, 1), "score": round(float(score), 3)})
    lines.sort(key=lambda l: (l["y"], l["x"]))
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session_dir")
    ap.add_argument("--out", default=None)
    ap.add_argument("--aligned", action="store_true",
                    help="OCR only pre-click + scene-boundary + settlement frames")
    args = ap.parse_args()
    sess = Path(args.session_dir)
    out = Path(args.out) if args.out else sess.parent.parent / "analysis" / sess.name
    out.mkdir(parents=True, exist_ok=True)

    meta = json.load(io.open(sess / "meta.json", encoding="utf-8"))
    start = meta["start"]
    ocr = RapidOCR(det_use_dml=True, cls_use_dml=True, rec_use_dml=True, use_cls=False)
    frames = sorted((sess / "frames").glob("f*.png"))
    hp = out / "hud.jsonl"
    done = set()
    if hp.exists():
        good = []
        for line in io.open(hp, encoding="utf-8"):
            try:
                done.add(json.loads(line)["i"])
            except json.JSONDecodeError:
                continue
            good.append(line.rstrip("\n"))
        with io.open(hp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(good) + ("\n" if good else ""))
    fts = None
    fj = sess / "frames.jsonl"
    if fj.exists():
        fts = [json.loads(l)["t"] for l in io.open(fj, encoding="utf-8") if l.strip()]
    needed = None
    if args.aligned:
        # frame numbers are 1-based (f000001 = first capture); true last frame = N
        needed = {1, len(frames), max(len(frames) - 1, 1)}
        cp = sess / "clicks.jsonl"
        if cp.exists():
            for line in io.open(cp, encoding="utf-8"):
                if not line.strip():
                    continue
                e = json.loads(line)
                if e.get("event") == "down":
                    if fts:
                        k = bisect.bisect_right(fts, e["t"])
                    else:
                        k = int(e["t"] - start) + 1
                    needed.add(min(max(k, 1), len(frames)))
        dp = out / "diffs.jsonl"
        if dp.exists():
            for line in io.open(dp, encoding="utf-8"):
                d = json.loads(line)
                if d.get("diff", 0) >= 25:
                    needed.add(d["i"])
        else:
            sp = out / "scenes.json"
            if sp.exists():
                for s in json.load(io.open(sp, encoding="utf-8")):
                    needed.add(s["start"])
        needed = {i for i in needed if 1 <= i <= len(frames)}
    total = len(needed) if needed is not None else len(frames)
    reuse = len(done & needed) if needed is not None else len(done)
    print(f"[hud] session={sess.name} frames={len(frames)} resume_from={len(done)} "
          f"aligned={args.aligned} needed={total} reuse={reuse} topup={total - reuse}", flush=True)
    n = 0
    with io.open(hp, "a", encoding="utf-8") as fh:
        for fp in frames:
            i = int(fp.stem[1:])
            if i in done:
                continue
            if needed is not None and i not in needed:
                continue
            img = Image.open(fp)
            lines = ocr_frame(img, ocr)
            row = {"i": i, "t": round(start + i, 3), "lines": lines}
            if fts and 1 <= i <= len(fts):
                row["t_real"] = round(fts[i - 1], 3)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            n += 1
            if n % 100 == 0:
                print(f"[hud] {reuse + n}/{total}", flush=True)
    print(f"[hud] done -> {hp} (ocr_calls={n})", flush=True)


if __name__ == "__main__":
    sys.exit(main())