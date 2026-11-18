"""Offline batch weight calibration + drift report (feedback-loop note).

Fits shop_score weights on (rec parts, user rating / correction) pairs,
outcome-filtered. NEVER silent: default run only writes a drift report for
user review; --apply writes model/weights.json (advisor loads it next run)
and requires >= MIN_SAMPLES rated pairs. Hard-floor checklist thresholds
are out of scope here -- ratings can never override them.
risk_flag recs are bucketed separately (learning risk preference, not quality).
"""
import argparse
import json
from pathlib import Path

import numpy as np

from .shop_score import DEFAULT_W

MIN_SAMPLES = 20
PART_KEYS = ["cov", "combat", "econ", "pool", "promote"]
ROOT = Path(__file__).resolve().parent.parent


def load_pairs(recs_path, ratings_path):
    recs = {}
    for l in open(recs_path, encoding="utf-8"):
        r = json.loads(l)
        recs[r["rec_id"]] = r
    pairs = []
    for l in open(ratings_path, encoding="utf-8"):
        rt = json.loads(l)
        rec = recs.get(rt["rec_id"])
        if not rec or rt.get("score") is None:
            continue
        for opt in rec["options"]:
            if "parts" not in opt:
                continue
            pairs.append({"parts": opt["parts"], "rating": rt["score"],
                          "followed": rt.get("followed"), "risk": rt.get("risk_flag", False),
                          "correction": rt.get("correction")})
    return pairs


def fit(pairs):
    """Least-squares parts -> rating/10 target. Returns (weights, n, report)."""
    usable = [p for p in pairs if not p["risk"]]
    risky = [p for p in pairs if p["risk"]]
    n = len(usable)
    report = {"n_usable": n, "n_risk_bucket": len(risky),
              "n_corrections": sum(1 for p in usable if p["correction"])}
    if n < 3:
        report["warning"] = "样本过少，不拟合"
        return dict(DEFAULT_W), n, report
    X = np.array([[p["parts"].get(k, 0.0) for k in PART_KEYS] for p in usable])
    y = np.array([p["rating"] / 10.0 for p in usable])
    # corrections are stronger supervision: upweight rows carrying one
    wrows = np.array([2.0 if p["correction"] else 1.0 for p in usable])
    Xw = X * wrows[:, None]
    yw = y * wrows
    coef, *_ = np.linalg.lstsq(Xw, yw, rcond=None)
    coef = np.clip(coef, 0.0, None)  # negative contribution weights are nonsensical v0
    new = {k: round(float(c), 4) for k, c in zip(PART_KEYS, coef)}
    report["drift"] = {k: {"old": DEFAULT_W[k], "new": new[k],
                           "delta_pct": round((new[k] - DEFAULT_W[k]) / DEFAULT_W[k] * 100, 1)}
                       for k in PART_KEYS}
    if n < MIN_SAMPLES:
        report["warning"] = f"样本 {n} < {MIN_SAMPLES}，仅报告不应用"
    return new, n, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recs", default=str(ROOT / "data" / "feedback" / "recs.jsonl"))
    ap.add_argument("--ratings", default=str(ROOT / "data" / "feedback" / "ratings.jsonl"))
    ap.add_argument("--apply", action="store_true",
                    help="write model/weights.json (requires >= MIN_SAMPLES; user-reviewed)")
    args = ap.parse_args()
    pairs = load_pairs(args.recs, args.ratings)
    new, n, report = fit(pairs)
    out = ROOT / "data" / "feedback" / "weight_drift_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[calibrate] pairs={len(pairs)} usable={n} report -> {out}")
    for k, d in report.get("drift", {}).items():
        print(f"  {k}: {d['old']} -> {d['new']} ({d['delta_pct']:+.1f}%)")
    if report.get("warning"):
        print(f"[calibrate] {report['warning']}")
    if args.apply:
        if n < MIN_SAMPLES:
            print("[calibrate] REFUSED: not enough samples; report only")
            return
        wp = ROOT / "model" / "weights.json"
        wp.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[calibrate] applied -> {wp} (user-reviewed drift report assumed)")


if __name__ == "__main__":
    main()