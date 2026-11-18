"""Parse hud.jsonl (aligned OCR) into per-frame state rows + per-round summary.

Usage: python parse_hud.py <analysis_dir>
Output: curves.jsonl   {i,t,round,phase,enemy_num,enemy_total,life,life_incoming,covenants}
        rounds.json    [{round,life_start,life_end,enemy_total,counters_end,clicks,drops}]
HUD layout (crop coords, crop=(500,0,1450,200)):
  round number x~270 y~46; rest banner '休息一下' x~488 y~45 (rest phase only);
  enemy counter 'a/b' x~496 y~40 (combat phase only, enemy-head icon NOT money;
    b=round enemy total; a semantics spawn-vs-kill still open);
  life x~680-720 y~46; incoming damage preview '-M' as separate token x~740 y~45
    (combat-end settlement banner '作战结束/生命值减少M' confirms it);
  covenant layer numbers y~145 paired with names y~166 by nearest x.
Co-op gates (mode_tag=coop only): joint-defense frames (HUD text contains
  叠加+禁用) carry own leak remaining in a/b -> leak_num/leak_total, covenant
  row belongs to the defended player -> dropped; spectate frames (teal name
  banner bottom-center, pixel gate >=0.3) drop enemy/life/covenants (ownership
  unknown); round-14 combat = leader round -> merged team life/enemies kept
  in merged_* fields, own curves untouched. Solo sessions parse unchanged.
"""
import argparse
import bisect
import io
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

NUM = re.compile(r"^\d+$")
FUNDS = re.compile(r"^(\d+)/(\d+)$")
MERGED = re.compile(r"^(\d+)([一-鿿]{1,4})$")
# covenant names seen in HUD + faction covenants from the rule book;
# extend when a new covenant shows up (OCR fragments like '奇证' are rejected)
# 26 = 10 core + 16 addon (KB v1 §7.1/§7.2, repo bonds.json cross-checked)
COVENANTS = {"炎", "奇迹", "灵巧", "远见", "绝技", "精准", "投资人", "聚合",
             "伊比利亚", "维多利亚", "阿戈尔", "乌萨斯", "莱塔尼亚", "谢拉格",
             "卡西米尔", "叙拉古", "萨尔贡", "坚守", "奥术",
             "迅捷", "助力", "突袭", "不屈", "调和", "协防干员", "独行"}
# spectate name banner region (full-frame coords); calibrated on coop session
# 20261117-200142: spectate f900 teal_frac=0.747, own/menu/leader frames <=0.005
SPEC_BOX = (750, 915, 1170, 980)
_SPEC_CACHE = {}


def spectate_frac(fp):
    key = str(fp)
    if key not in _SPEC_CACHE:
        im = np.asarray(Image.open(fp).convert("RGB").crop(SPEC_BOX), dtype=np.int16)
        r, g, b = im[..., 0], im[..., 1], im[..., 2]
        teal = (g > 90) & (b > 90) & (r < 80) & (g > r + 40) & (b > r + 40)
        _SPEC_CACHE[key] = float(teal.mean())
    return _SPEC_CACHE[key]


def parse_row(r):
    ls = r["lines"]
    round_no = None
    phase = "other"
    enemy_num = enemy_total = None
    life = incoming = None
    jd = False
    settle = False
    hidden = False
    for l in ls:
        t, x, y = l["text"], l["x"], l["y"]
        if "叠加" in t and "禁用" in t:
            jd = True
        if "模拟完成" in t or "返回主页" in t:
            settle = True
        if 35 <= y <= 55 and 250 <= x <= 295 and NUM.match(t):
            round_no = int(t)
        if 35 <= y <= 55 and 250 <= x <= 295 and ("?" in t or "？" in t):
            hidden = True  # hidden round (R15) shows 回合 ?? instead of a digit
        m3 = re.match(r"^回合(\d+)$", t)
        if m3:
            round_no = int(m3.group(1))
        if re.match(r"^回合[?？]+$", t):
            hidden = True
        if "休息一下" in t:
            phase = "rest"
        m = FUNDS.match(t)
        if m and 30 <= y <= 55 and 440 <= x <= 570:
            enemy_num, enemy_total = int(m.group(1)), int(m.group(2))
        if 35 <= y <= 60 and 640 <= x <= 790:
            m2 = re.match(r"^(\d+)(?:\s*-(\d+))?$", t)
            if m2:
                life = int(m2.group(1))
                if m2.group(2):
                    incoming = int(m2.group(2))
        m4 = re.match(r"^-(\d+)$", t)
        if m4 and 30 <= y <= 60 and 700 <= x <= 800:
            incoming = int(m4.group(1))
    if round_no is not None and phase == "other":
        phase = "combat"
    names = [l for l in ls if 155 <= l["y"] <= 180 and l["text"] in COVENANTS]
    nums = [l for l in ls if 125 <= l["y"] <= 155 and NUM.match(l["text"])]
    cov = {}
    pairs = []
    for n in nums:
        best = min(names, key=lambda nm: abs(nm["x"] - n["x"]), default=None)
        if best is not None and abs(best["x"] - n["x"]) < 45:
            pairs.append((best["text"], int(n["text"])))
    byname = {}
    for nm, v in pairs:
        byname.setdefault(nm, []).append(v)
    amb = []
    for nm, vals in byname.items():
        if len(vals) > 1:
            amb.append(nm)  # one name claimed by two numbers: do not guess (audit A3)
        else:
            cov[nm] = vals[0]
    for l in ls:
        m = MERGED.match(l["text"])
        if m and 125 <= l["y"] <= 180 and m.group(2) in COVENANTS:
            if m.group(2) not in cov and m.group(2) not in amb:
                cov[m.group(2)] = int(m.group(1))
    out_row = {"i": r["i"], "t": r["t"], "round": round_no, "phase": phase, "_jd": jd,
               "_settle": settle, "_hidden": hidden,
               "enemy_num": enemy_num, "enemy_total": enemy_total, "life": life,
               "life_incoming": incoming, "covenants": cov}
    if hidden:
        # hidden-round life badge sits left of the HUD crop (unreadable); the
        # right-hand digit is NOT own life -> honest null, stash raw for later
        out_row["hidden_right_raw"] = life
        out_row["life"] = out_row["life_incoming"] = None
    if amb:
        out_row["cov_ambiguous"] = amb
    return out_row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("analysis_dir")
    args = ap.parse_args()
    out = Path(args.analysis_dir)
    rows = [parse_row(json.loads(l)) for l in io.open(out / "hud.jsonl", encoding="utf-8")]
    fp = out / "rounds_fix.jsonl"
    if fp.exists():
        fix = {json.loads(l)["i"]: json.loads(l)["round"] for l in io.open(fp, encoding="utf-8")}
        for r in rows:
            if r["round"] is None and r["i"] in fix:
                r["round"] = fix[r["i"]]
    rows.sort(key=lambda r: r["i"])
    # round numbers are plateaus lasting tens of frames and advance by exactly
    # +1; isolated jumps and short bursts (folder tab read as '1' -> '16') are
    # misreads. A new value is accepted only if it is last+1 and persists in
    # >=3 of the next 5 readings.
    seq = [(r["i"], r["round"]) for r in rows if r["round"] is not None]
    clean = {}
    last_clean = None
    prev_i = None
    for k, (i, v) in enumerate(seq):
        window = [w for _, w in seq[k:k + 5]]
        if last_clean is None:
            last_clean = v
        elif (v == 1 and last_clean >= 2 and prev_i is not None
              and i - prev_i >= 20 and window.count(1) >= 3
              and any(rr.get("_settle") for rr in rows
                      if prev_i < rr["i"] < i and rr["round"] is None)):
            last_clean = 1  # restart proven by settlement/menu evidence in the gap
        elif v == last_clean + 1 and window.count(v) >= 3:
            last_clean = v
        elif v != last_clean:
            v = last_clean
        clean[i] = v
        prev_i = i
    for r in rows:
        if r["i"] in clean:
            r["round"] = clean[r["i"]]
    # co-op contamination gates: spectated / joint-defense / leader readings
    # are not the recorder's own state; keep them in separate fields
    sess = out.parent.parent / "raw" / out.name
    mode = "solo"
    mp = sess / "meta.json"
    if mp.exists():
        mode = json.load(io.open(mp, encoding="utf-8")).get("mode_tag", "solo")
    gates = Counter()
    known = [r["round"] for r in rows if r["round"] is not None]
    hidden_round = (max(known) + 1) if known else None
    for r in rows:
        jd = r.pop("_jd", False)
        r.pop("_settle", None)
        hid = r.pop("_hidden", False)
        if hid and hidden_round is not None:
            # hidden R15: 回合 ?? carries no digit; attribute to max+1 and keep
            # the row (covenants readable); life unreadable -> null (see parse_row)
            r["round"] = hidden_round
            r["gate"] = "hidden"
            gates["hidden"] += 1
            continue
        if mode != "coop" or r["round"] is None:
            continue
        if jd:
            r["gate"] = "joint_defense"
            r["phase"] = "joint_defense"
            r["leak_num"], r["leak_total"] = r["enemy_num"], r["enemy_total"]
            r["enemy_num"] = r["enemy_total"] = None
            r["covenants"] = {}
        elif r["phase"] == "combat" and spectate_frac(sess / "frames" / f"f{r['i']:06d}.png") >= 0.3:
            r["gate"] = "spectate"
            r["phase"] = "spectate"
            r["enemy_num"] = r["enemy_total"] = None
            r["life"] = r["life_incoming"] = None
            r["covenants"] = {}
        elif r["round"] == 14:
            # merged team life is displayed from R14 rest onward (canon evidence)
            r["gate"] = "leader"
            r["merged_life"] = r["life"]
            r["merged_enemy_num"], r["merged_enemy_total"] = r["enemy_num"], r["enemy_total"]
            r["life"] = r["life_incoming"] = None
            r["enemy_num"] = r["enemy_total"] = None
        gates[r.get("gate", "own")] += 1
    # life only changes at round boundaries (combat end), so the rest-phase
    # reading majority is canonical; stray OCR digits get snapped to it
    canon = {}
    for rn in sorted({r["round"] for r in rows if r["round"] is not None}):
        vals = [r["life"] for r in rows if r["round"] == rn and r["phase"] == "rest"
                and r["life"] is not None]
        if not vals:
            vals = [r["life"] for r in rows if r["round"] == rn and r["life"] is not None]
        if vals:
            canon[rn] = Counter(vals).most_common(1)[0][0]
    for r in rows:
        if r["round"] in canon and r["life"] is not None and r["life"] != canon[r["round"]]:
            r["life_raw"] = r["life"]
            r["life"] = canon[r["round"]]
    # enemy denominator b is constant within a round: same majority treatment
    # as life, so a stray OCR misread cannot silently overwrite it (audit A3)
    ecanon = {}
    for rn in sorted({r["round"] for r in rows if r["round"] is not None}):
        vals = [r["enemy_total"] for r in rows if r["round"] == rn and r["enemy_total"] is not None]
        if vals:
            ecanon[rn] = Counter(vals).most_common(1)[0][0]
    for r in rows:
        if r["round"] in ecanon and r["enemy_total"] is not None and r["enemy_total"] != ecanon[r["round"]]:
            r["enemy_total_raw"] = r["enemy_total"]
            r["enemy_total"] = ecanon[r["round"]]
    # curves.jsonl is P3 input: in-round rows only. Menu/strategy/settlement
    # frames (round=None) are excluded; settlement counters belong to
    # parse_settlement (audit A2: f2193 settlement covenant row leaked before)
    with io.open(out / "curves.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            if r["round"] is None:
                continue
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    sess = out.parent.parent / "raw" / out.name
    clicks = []
    cp = sess / "clicks.jsonl"
    if cp.exists():
        start = json.load(io.open(sess / "meta.json", encoding="utf-8"))["start"]
        fts = None
        fj = sess / "frames.jsonl"
        if fj.exists():
            fts = [json.loads(l)["t"] for l in io.open(fj, encoding="utf-8") if l.strip()]
        for e in (json.loads(l) for l in io.open(cp, encoding="utf-8") if l.strip()):
            if e.get("event") != "down":
                continue
            if fts:
                c = min(max(bisect.bisect_right(fts, e["t"]), 1), len(fts))
            else:
                c = int(e["t"] - start) + 1
            clicks.append(c)

    rounds = {}
    prev_canon = None
    for r in rows:
        if r["round"] is None:
            continue
        g = rounds.setdefault(r["round"], {"round": r["round"], "frames": [],
                                           "life_start": None, "life_end": None,
                                           "enemy_total": None, "counters_end": {},
                                           "clicks": 0, "drops": []})
        g["frames"].append(r["i"])
        if r["round"] in canon:
            g["life_start"] = g["life_end"] = canon[r["round"]]
            if prev_canon is not None and canon[r["round"]] < prev_canon and not g["drops"]:
                g["drops"].append({"i": r["i"], "from": prev_canon,
                                   "to": canon[r["round"]], "cause_round": r["round"] - 1})
            prev_canon = canon[r["round"]]
        elif prev_canon is not None and g["life_start"] is None:
            # leader round shows merged life only; own life carries over
            g["life_start"] = g["life_end"] = prev_canon
        if r["enemy_total"] is not None:
            g["enemy_total"] = r["enemy_total"]
        if r["covenants"]:
            for name, v in r["covenants"].items():
                g.setdefault("cov_counts", {}).setdefault(name, Counter())[v] += 1
                g.setdefault("cov_seq", {}).setdefault(name, []).append(v)
        if r.get("leak_num") is not None:
            g.setdefault("leak_seq", []).append([r["i"], r["leak_num"], r["leak_total"]])
        if r.get("merged_life") is not None:
            g.setdefault("merged_life_seq", []).append([r["i"], r["merged_life"]])
    for g in rounds.values():
        a, b = g["frames"][0], g["frames"][-1]
        g["clicks"] = sum(1 for c in clicks if a <= c <= b)
        g["n_frames"] = len(g["frames"])
        # permanent covenant layers are monotonic non-decreasing (KB v1.3: no
        # consumption mechanism, 灵巧 is NOT spendable -- prior 'spendable' note was
        # a misinference); apparent drops are single-frame OCR truncation spikes.
        # Take the last reading occurring >=2 times in the round (rejects one-off
        # spikes). noStack four (调和/协防干员/独行/绝技) HUD digit != layer.
        seqs = g.pop("cov_seq", {})
        for name, cnt in g.pop("cov_counts", {}).items():
            seq = seqs[name]
            g["counters_end"][name] = next((v for v in reversed(seq) if cnt[v] >= 2), seq[-1])
        del g["frames"]
    rl = sorted(rounds.values(), key=lambda g: g["round"])
    with io.open(out / "rounds.json", "w", encoding="utf-8") as f:
        json.dump(rl, f, ensure_ascii=False, indent=1)
    ing = sum(1 for r in rows if r["round"] is not None)
    print(f"[parse] {out.name}: rows={len(rows)} in_game={ing} rounds={len(rl)}")
    if gates:
        print(f"[parse] coop gates: {dict(gates)}")
    for g in rl:
        top = sorted(g["counters_end"].items(), key=lambda kv: -kv[1])[:3]
        print(f"  R{g['round']:02d} life {g['life_start']}->{g['life_end']} "
              f"enemy_total={g['enemy_total']} clicks={g['clicks']} "
              f"drops={len(g['drops'])} top={top}")


if __name__ == "__main__":
    main()