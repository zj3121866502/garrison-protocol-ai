"""Offline replay: run the advisor over recorded sessions for USER judgment.

Eats analysis/<session>/curves.jsonl + rounds.json (HUD-only partial state).
Optional --mock-shop JSON supplies shop/roster/funds for development before
P1 shop OCR lands; mock input is labeled MOCK in every emitted record.
No self-acceptance: output is a review packet, the user judges reasonableness
(plan §6 step 4). Realtime recommendations wait for P1 (plan §6 note).
"""
import argparse
import json
from pathlib import Path

from .state import State, ShopSlot, Unit
from .kb import KB
from .advisor import advise


def _load_mock(path):
    m = json.loads(Path(path).read_text(encoding="utf-8"))
    return m


def _apply_mock(state, mock, round_no):
    """Mock keyed by round number; missing round -> leave fields null."""
    r = (mock.get("rounds") or {}).get(str(round_no))
    if not r:
        return False
    state.funds = r.get("funds")
    state.center_level = r.get("center_level")
    state.shop = [ShopSlot(**s) for s in r.get("shop", [])]
    state.bench = [Unit(**u) for u in r.get("bench", [])]
    state.field_units = [Unit(**u) for u in r.get("field", [])]
    state.special_types = r.get("special_types", state.special_types)
    state.banned_addons = r.get("banned_addons", state.banned_addons)
    state.core_group = r.get("core_group", state.core_group)
    return True


def normalize_name(ocr_name, operators, tags=()):
    """Map an OCR shop-card name to a canonical operator name.

    OCR truncates artistic banners (e.g. '折' for '折桠'). Exact match first,
    then a UNIQUE substring match either direction. When several operators
    share the fragment ('折' -> 折桠/折光), disambiguate by the card's OCR'd
    covenant tags vs operator bonds (unique best overlap > 0 wins). Ambiguous
    or equipment cards (卫戌推荐信, absent from operators) -> None (honest skip).
    """
    if not ocr_name:
        return None
    if ocr_name in operators:
        return ocr_name
    cand = [n for n in operators if ocr_name in n or n in ocr_name]
    if len(cand) == 1:
        return cand[0]
    if len(cand) > 1 and tags:
        tagset = set(tags)
        scored = [(len(tagset & set(operators[n].get("bonds") or [])), n) for n in cand]
        best = max(s for s, _ in scored)
        winners = [n for s, n in scored if s == best]
        if best > 0 and len(winners) == 1:
            return winners[0]
    return None


def _load_shop(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _shop_for_round(shop_reads, round_frames, decision_i):
    """Clean shop read nearest the decision window (first rest frame) within
    the round's frame span. Shop persists through rest; nearest clean read is
    a coarse approximation (manual refresh may change it) -- labeled SHOP-NAME."""
    cand = [s for s in shop_reads if s.get("shop_state") == "clean"
            and round_frames and round_frames[0] <= s["frame"] <= round_frames[-1]]
    if not cand:
        return None
    return min(cand, key=lambda s: (abs(s["frame"] - decision_i), s["frame"]))


def _apply_shop(state, shop_rec, kb):
    """Fill shop slots (normalized names) + funds from one OCR read.
    price/tier stay null -> score_shop falls back to KB (provisional)."""
    if not shop_rec:
        return False
    state.funds = shop_rec.get("funds")
    named = 0
    slots = []
    for s in shop_rec.get("slots", []):
        canon = normalize_name(s.get("name"), kb.operators, s.get("tags") or [])
        if canon:
            named += 1
        slots.append(ShopSlot(name=canon, tier=s.get("tier"), price=s.get("price"),
                              frozen=s.get("frozen", False), sold=s.get("sold", False)))
    state.shop = slots
    return named > 0


def replay(analysis_dir, difficulty, mock_path=None, out_path=None, shop_path=None):
    analysis_dir = Path(analysis_dir)
    session = analysis_dir.name
    kb = KB()
    mock = _load_mock(mock_path) if mock_path else None
    shop_reads = _load_shop(shop_path) if shop_path else None
    # mode_tag from raw meta.json (same dir convention as parse_settlement).
    # Without this, from_curves_row defaults solo and coop sessions would
    # bypass the v0 solo-only gate in advise() (B3 review finding, 2026-11-18).
    meta_p = analysis_dir.parent.parent / "raw" / session / "meta.json"
    mode_tag = "solo"
    if meta_p.exists():
        mode_tag = json.loads(meta_p.read_text(encoding="utf-8")).get("mode_tag") or "solo"
    rows = [json.loads(l) for l in open(analysis_dir / "curves.jsonl", encoding="utf-8")]
    rounds = json.loads((analysis_dir / "rounds.json").read_text(encoding="utf-8"))
    clicks_by_round = {g["round"]: g.get("clicks", 0) for g in rounds}
    # one recommendation per round: first rest-phase row (decision window)
    first_rest = {}
    frames_by_round = {}
    for r in rows:
        rn = r.get("round")
        if rn is None:
            continue
        frames_by_round.setdefault(rn, []).append(r["i"])
        if r.get("phase") == "rest" and rn not in first_rest:
            first_rest[rn] = r
    for rn in frames_by_round:
        frames_by_round[rn].sort()
    recs, degraded = [], []
    for rn in sorted(first_rest):
        st = State.from_curves_row(first_rest[rn], session=session,
                                   mode_tag=mode_tag, difficulty=difficulty)
        mocked = _apply_mock(st, mock, rn) if mock else False
        shop_applied = False
        if shop_reads and not mocked:
            shop_rec = _shop_for_round(shop_reads, frames_by_round.get(rn, []),
                                       first_rest[rn]["i"])
            shop_applied = _apply_shop(st, shop_rec, kb)
        rec = advise(st, kb, log_path=False)
        if rec is None:
            continue
        rec["input"] = "MOCK" if mocked else ("SHOP-NAME" if shop_applied else "HUD-only")
        rec["user_clicks_in_round"] = clicks_by_round.get(rn)
        if not mocked and not shop_applied:
            degraded.append(rn)
        recs.append(rec)
    out = Path(out_path) if out_path else analysis_dir / "replay_recs.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for rec in recs:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    n_shop = sum(1 for r in recs if r["input"] == "SHOP-NAME")
    print(f"[replay] {session}: rounds={len(recs)} shop-name={n_shop} -> {out}")
    if mode_tag == "coop":
        print("[replay] coop session: v0 solo-only gate active, 0 recs "
              "(coop recommendations deferred)")
    if degraded:
        print(f"[replay] HUD-only degraded rounds (no shop/roster): {degraded}")
    print("[replay] review packet for USER judgment; not an acceptance test")
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("analysis_dir")
    ap.add_argument("--difficulty", required=True,
                    help="band key, e.g. solo_regulation_1_4 / coop_peril")
    ap.add_argument("--mock-shop", default=None, help="MOCK shop/roster JSON (dev only)")
    ap.add_argument("--shop-ocr", default=None,
                    help="shop.json from analysis/ocr_shop.py (names+funds; price/tier KB-fallback)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    replay(args.analysis_dir, args.difficulty, args.mock_shop, args.out, args.shop_ocr)


if __name__ == "__main__":
    main()