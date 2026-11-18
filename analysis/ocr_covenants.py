"""P1 increment: covenant banner reader -> covenants_temp (乌萨斯 only).

KB v1.3 grounded design (协作A 核问 notes/20261118-covenants_temp基线KB核问.md):
  - ONLY 乌萨斯 has temp layers (kill-stacked, cleared at round end). The other 25
    covenants have NO temp mechanism -> banner>baseline diff is permanent increment
    or baseline OCR-miss, NOT temp. noStack four (调和/协防干员/独行/绝技) have no
    layer concept at all (HUD digit != layer) -> excluded.
  - permanent layers are monotonic non-decreasing (no consumption mechanism; 灵巧
    is NOT spendable). Baseline = per-name ENVELOPE max over all rest rows <= i
    (immune to single-frame OCR truncation spikes; beats single nearest rest which
    underestimates permanent due to 助力 rest-end grant timing + intermittent misses).
  - rest banner == permanent (temp cleared at round end, B-level sample evidence).
    combat banner = permanent + 乌萨斯 temp + in-combat permanent increment, so
    乌萨斯 temp = combat - envelope is a slight OVERestimate (honest label).
  - temp layers have NO cap (KB v1.3 erratum: '乌萨斯上限4' was a misread; 4 = per-kill
    stack count after 6 crew, sample temp peak ~158 falsifies a cap of 4).

Banner geometry: names y~166 read from full-banner 2x; counts read PER-CELL 8x above
each name (single full-banner pass misses small early counts, reads tier badges).
QC invariant: a REST frame should yield 乌萨斯 temp ~ 0; large rest temp = baseline miss.

Usage: python analysis/ocr_covenants.py <analysis_dir> --frames 457,470,2185
Output: <analysis_dir>/covenants_temp.json
"""
import argparse
import io
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_hud import COVENANTS

BANNER_BOX = (0, 110, 1920, 210)
SCALE = 2
CELL_SCALE = 8          # early-game counts are tiny; per-cell 8x resolves them
CELL_BOX = (-32, 126, 32, 158)   # count cell above a name, relative to name x
NUM = re.compile(r"^\d+$")

TEMP_BOND = "乌萨斯"                       # only covenant with temp layers (KB v1.3)
NO_STACK = {"调和", "协防干员", "独行", "绝技"}   # no layer concept; HUD digit != layer


def read_banner(img, ocr):
    """Names from a full-banner 2x pass (reliable); counts read PER-CELL at 8x
    above each name. A single full-banner pass misses the small early-game count
    digits (reads tier badges I/II/III instead) -- calibrated on 224824 f457
    (迅捷11/不屈2/坚守1) vs f2185 (258/166/67)."""
    crop = img.crop(BANNER_BOX)
    crop = crop.resize((crop.width * SCALE, crop.height * SCALE), Image.LANCZOS)
    res, _ = ocr(np.asarray(crop))
    names = {}
    for box, text, score in res or []:
        x = sum(p[0] for p in box) / 4 / SCALE
        y = sum(p[1] for p in box) / 4 / SCALE + BANNER_BOX[1]
        if not (155 <= y <= 180):
            continue
        # early-game tokens merge count/tier with the name ('1不屈','I迅捷','远见三');
        # accept the longest whitelist name contained in the token, dedupe by name
        hits = [nm for nm in COVENANTS if nm in text]
        if hits:
            nm = max(hits, key=len)
            names.setdefault(nm, x)
    cov = {}
    for nm, x in names.items():
        cx = int(x)
        cell = img.crop((cx + CELL_BOX[0], CELL_BOX[1], cx + CELL_BOX[2], CELL_BOX[3]))
        cell = cell.resize((cell.width * CELL_SCALE, cell.height * CELL_SCALE), Image.LANCZOS)
        r, _ = ocr(np.asarray(cell))
        digits = [t for _, t, _ in (r or []) if NUM.match(t)]
        if digits:
            cov[nm] = int(max(digits, key=len))   # longest digit run = the count
    return cov


def envelope_at(rest, i):
    """Per-name permanent envelope = max layer over all rest rows <= i.
    Monotonic permanent (KB v1.3) makes max legal; immune to low OCR-truncation spikes."""
    env = {}
    for r in rest:
        if r["i"] <= i:
            for nm, v in (r.get("covenants") or {}).items():
                if v > env.get(nm, 0):
                    env[nm] = v
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("analysis_dir")
    ap.add_argument("--frames", default="")
    args = ap.parse_args()
    out = Path(args.analysis_dir)
    sess = out.parent.parent / "raw" / out.name
    rows = [json.loads(l) for l in io.open(out / "curves.jsonl", encoding="utf-8") if l.strip()]
    # own-state rest rows only: coop spectate/joint_defense/leader/hidden rows carry
    # other-player or merged covenants and must not feed the permanent envelope
    rest = [r for r in rows if r.get("phase") == "rest" and r.get("covenants")
            and r.get("gate") in (None, "own")]
    phase_by_i = {r["i"]: r.get("phase") for r in rows}
    frames = [int(x) for x in args.frames.split(",") if x.strip()]
    ocr = RapidOCR(det_use_dml=True, rec_use_dml=True, use_cls=False)
    result = []
    for i in frames:
        img = Image.open(sess / "frames" / f"f{i:06d}.png").convert("RGB")
        banner = read_banner(img, ocr)
        env = envelope_at(rest, i)
        phase = phase_by_i.get(i)
        temp, flags = {}, {}
        for nm, v in banner.items():
            if nm in NO_STACK:
                flags[nm] = "no_stack_excluded"      # HUD digit != layer; skip
                continue
            if nm == TEMP_BOND:
                # combat banner includes in-combat permanent increment -> slight overestimate
                temp[nm] = max(0, v - env.get(nm, 0))
            elif v > env.get(nm, 0):
                # no temp mechanism: diff is permanent gain or baseline OCR-miss, NOT temp
                flags[nm] = "perm_increment_or_baseline_miss"
        # QC invariant: rest banner == permanent -> 乌萨斯 temp should be ~0
        qc_rest_temp = (phase == "rest" and temp.get(TEMP_BOND, 0) > 0)
        result.append({"frame": i, "phase": phase, "banner": banner, "envelope": env,
                       "covenants_temp": temp, "flags": flags,
                       "temp_note": "乌萨斯 only; combat temp slight overestimate (incl in-combat permanent gain)"
                       if temp else None,
                       "qc_rest_temp_nonzero": qc_rest_temp})
        print(f"[cov] f{i}({phase}): banner={banner} env={env} temp={temp} "
              f"flags={flags} qc_rest_temp={qc_rest_temp}")
    (out / "covenants_temp.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    print(f"[done] {out / 'covenants_temp.json'}")


if __name__ == "__main__":
    main()