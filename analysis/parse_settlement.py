"""Extract outcome labels from the settlement page of a recorded run.

Usage: python parse_settlement.py <analysis_dir> --start 2215 --end 2219

A5 generalization (2026-11-18, main-agent lane; see notes/20261118-A5结算泛化设计.md).
Handles three variants measured from full-frame OCR of four sessions:
  - solo_win   (224824 f2219, banner 模拟完成)
  - solo_fail  (223918 f2268 血线崩 / 232000 f1056-1058 认输, banner 模拟中断)
  - coop       (200142 f2990, player-summary page, banner 模拟完成 bottom-left)
Solo win/fail share one layout; co-op is a different (player-summary) page.

Key fixes vs the 224824-only original:
  - rounds_passed anchored to the 通过回合 label (label x drifts 131->221 between
    win/fail; the old hard x<220 gate dropped the failure digit at x221.5).
  - merit / cert_cap given tight position windows to reject recorder-GUI overlay
    duplicates (232000 has the recorder window painted over the settlement page).
  - pollution detected + flagged; settlement elements use reference-anchored
    position windows so GUI text (x300-700 y246-898) falls outside and is dropped.
  - covenant counters: names are ICONS not text. Hardcoded COUNTER_NAMES removed.
    Values extracted by x-sorted slots; names assigned PROVISIONALLY by value-match
    to the curves last REST-phase permanent covenant map (settlement>=rest, min-delta
    greedy). All names flagged name_provisional; true naming awaits the P1 icon
    template library. Counter icon crops saved for that library.
  - co-op: extracts difficulty / alliance_rounds / per-player rounds+disconnect.
    The player-summary page has no roster cards / covenant counters -> flagged gap.

Output: settlement.json + settlement/card_r{row}c{col}.png + settlement/counter_s{n}.png
Schema change (counters dict->list, new variant/outcome/polluted/coop fields) is
subject to 协作A review per the audit relay (report->fix->review).
Grid measured from f002219 of session-20261116-224824 (1920x1080).
"""
import argparse
import hashlib
import io
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

# Solo roster grid (224824 f2219). Co-op player-summary page has no such grid.
ROWS = {1: (122, 341, [1193, 1343, 1488, 1633, 1778]),
        2: (396, 615, [1170, 1315, 1460, 1605, 1750])}
CARD_W = 112

POLLUTION_MARKERS = ("卫成协议录制器", "卫戍协议录制器", "开始录制", "结束录制",
                     "数据目录", "截图帧率", "视频帧率")
DIFF_LABELS = ("绝境模拟", "险境模拟", "标准模拟", "极速模拟")


def icon_hash(img):
    g = np.asarray(img.convert("L").resize((16, 16))).astype(float)
    g = (g > g.mean()).astype(np.uint8)
    return hashlib.md5(g.tobytes()).hexdigest()[:12]


def lines_of(res):
    return [{"text": t, "x": round(sum(p[0] for p in box) / 4, 1),
             "y": round(sum(p[1] for p in box) / 4, 1)} for box, t, _ in res]


def load_last_rest_covenants(analysis_dir):
    """Last REST-phase row carries the full permanent covenant map. The final
    curves row is usually combat phase (banner shows only the active combat
    covenant), so it must NOT be used for naming."""
    cp = analysis_dir / "curves.jsonl"
    if not cp.exists():
        return {}
    last = {}
    for line in cp.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("round") is not None and r.get("phase") == "rest":
            last = r.get("covenants") or {}
    return last


def name_counters(slots, rest_map):
    """Provisional greedy min-delta assignment. settlement permanent >= rest
    permanent, so only rest_val <= value are candidates. Each name used once."""
    pairs = []
    for s in slots:
        for name, rv in rest_map.items():
            if rv <= s["value"]:
                pairs.append((s["value"] - rv, s["slot"], name))
    pairs.sort()
    used, assigned = set(), {}
    for delta, slot, name in pairs:
        if slot in assigned or name in used:
            continue
        assigned[slot] = (name, delta)
        used.add(name)
    for s in slots:
        if s["slot"] in assigned:
            name, delta = assigned[s["slot"]]
            conf = "high" if delta <= 8 else ("medium" if delta <= 20 else "low")
            s.update(name=name, name_provisional=True,
                     match_delta=delta, match_confidence=conf)
        else:
            s.update(name=None, name_provisional=True,
                     match_delta=None, match_confidence="none")
    return slots


def find_settlement(sess, ocr, start, end):
    """Scan [start,end]; accept frames with a settlement banner + 返回主页, or
    (GUI-garbled banner) 返回主页 + 通过回合. Prefer clean over polluted, then
    banner present, then latest frame."""
    cands = []
    for i in range(end, start - 1, -1):
        fp = sess / "frames" / f"f{i:06d}.png"
        if not fp.exists():
            continue
        img = Image.open(fp)
        res, _ = ocr(img)
        if not res:
            continue
        ls = lines_of(res)
        joined = "|".join(l["text"] for l in ls)
        has_banner = ("模拟完成" in joined) or ("模拟中断" in joined)
        has_home = "返回主页" in joined
        has_rounds = "通过回合" in joined
        if not (has_home and (has_banner or has_rounds)):
            continue
        polluted = any(m in joined for m in POLLUTION_MARKERS)
        cands.append((polluted, not has_banner, -i, i, img, ls, joined))
    if not cands:
        return None
    cands.sort(key=lambda c: (c[0], c[1], c[2]))
    _, _, _, i, img, ls, joined = cands[0]
    return i, img, ls, joined


def extract_solo(img, ls, joined, out, lab, ocr, ocr_rec, rest_map):
    lab["variant"] = "solo"
    lab["outcome"] = ("win" if "模拟完成" in joined
                      else "fail" if "模拟中断" in joined else "unknown")
    # rounds: anchor to 通过回合 label, digit directly below (x drifts win/fail)
    labels = [l for l in ls if "通过回合" in l["text"] and "同盟" not in l["text"]
              and 420 <= l["y"] <= 470]
    if labels:
        lb = min(labels, key=lambda l: l["y"])
        digs = [l for l in ls if re.match(r"^\d+$", l["text"])
                and lb["y"] + 50 <= l["y"] <= lb["y"] + 95
                and abs(l["x"] - lb["x"]) <= 70]
        if digs:
            lab["rounds_passed"] = int(min(digs, key=lambda l: abs(l["x"] - lb["x"]))["text"])
    m = re.search(r"(\d+)时(\d+)分(\d+)秒", joined)
    if m:
        lab["duration_s"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    # merit: tight window rejects GUI duplicates
    for l in ls:
        mm = re.match(r"^[xX](\d+)$", l["text"])
        if mm and 250 <= l["x"] <= 340 and 960 <= l["y"] <= 1000:
            lab["merit"] = int(mm.group(1))
    # cert cap: tight window
    for l in ls:
        mm = re.match(r"^(\d+)/(\d+)$", l["text"])
        if mm and 450 <= l["x"] <= 560 and 990 <= l["y"] <= 1020:
            lab["cert_cap"] = [int(mm.group(1)), int(mm.group(2))]
    # counters: x-sorted slots at y~785 x>1400; icon above each; provisional naming
    nums = sorted((l for l in ls if re.match(r"^\d+$", l["text"])
                   and 750 <= l["y"] <= 810 and l["x"] > 1400), key=lambda l: l["x"])
    (out / "settlement").mkdir(exist_ok=True)
    slots = []
    for n, l in enumerate(nums, 1):
        x = l["x"]
        ic = out / "settlement" / f"counter_s{n}.png"
        img.crop((int(x) - 28, 716, int(x) + 28, 772)).save(ic)
        slots.append({"slot": n, "x": x, "value": int(l["text"]), "icon": ic.name})
    lab["counters"] = name_counters(slots, rest_map)
    lab["counters_rest_ref"] = rest_map
    # roster grid + badges (unchanged logic from 224824 reference)
    def badge(box, with_det=False):
        im = img.crop(box)
        im = im.resize((im.width * 3, im.height * 3), Image.NEAREST)
        r, _ = (ocr if with_det else ocr_rec)(im)
        return "".join(item[1] if len(item) == 3 else item[0] for item in (r or []))

    def norm(tt):
        tt = tt.upper().replace("三", "III").replace("二", "II").replace("一", "I")
        m = re.search(r"[IVX]+", tt)
        return m.group(0) if m else None

    for row, (y0, y1, xs) in ROWS.items():
        for col, x in enumerate(xs, 1):
            card = img.crop((x - 25, y0, x + CARD_W, y1))
            cp = out / "settlement" / f"card_r{row}c{col}.png"
            card.save(cp)
            port = np.asarray(img.crop((x + 5, y0 + 30, x + 105, y0 + 150))
                              .convert("RGB")).astype(float)
            empty = bool(port.std() < 25)
            tier = level = None
            if not empty:
                tier = norm(badge((x - 25, y0 - 2, x + 35, y0 + 28)))
                if tier is None:
                    tier = norm(badge((x - 25, y0 - 2, x + 35, y0 + 28), with_det=True))
                lt = badge((x - 20, y0 + 78, x + 12, y0 + 112))
                m = re.search(r"\d+", lt)
                level = int(m.group(0)) if m else None
            equips = [icon_hash(img.crop((ex, y1 - 62, ex + 52, y1 - 8)))
                      for ex in (x + 2, x + 58)]
            lab["roster"].append({"slot": f"r{row}c{col}", "tier": tier,
                                  "level": level, "empty": empty,
                                  "portrait_std": round(float(port.std()), 1),
                                  "equip_hashes": equips, "crop": cp.name})


def extract_coop(img, ls, joined, lab):
    lab["variant"] = "coop"
    lab["outcome"] = ("win" if "模拟完成" in joined
                      else "fail" if "模拟中断" in joined else "unknown")
    for l in ls:
        if l["text"] in DIFF_LABELS:
            lab["difficulty"] = l["text"]
    # alliance rounds: 同盟通过回合 label + digit below
    al = [l for l in ls if "同盟通过回合" in l["text"]]
    if al:
        lb = al[0]
        digs = [l for l in ls if re.match(r"^\d+$", l["text"])
                and lb["y"] + 40 <= l["y"] <= lb["y"] + 95
                and abs(l["x"] - lb["x"]) <= 80]
        if digs:
            lab["alliance_rounds"] = int(min(digs, key=lambda l: abs(l["x"] - lb["x"]))["text"])
    m = re.search(r"(\d+)时(\d+)分(\d+)秒", joined)
    if m:
        lab["duration_s"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    # player columns anchored on 通过回合 badges (status row y600-660); names are arbitrary
    # text (no #digit required) read from the name banner row below each badge column.
    anchors = sorted((l for l in ls if 600 <= l["y"] <= 660
                      and ("通过回合" in l["text"] or "中断连接" in l["text"])),
                     key=lambda l: l["x"])
    players = []
    for an in anchors:
        ax = an["x"]
        col = sorted((l for l in ls if 600 <= l["y"] <= 660 and ax - 40 <= l["x"] <= ax + 200),
                     key=lambda l: l["x"])
        cj = "".join(l["text"] for l in col)
        disconnected = "中断连接" in cj
        rounds = None
        mm = re.search(r"通过回合(\d+)", cj)
        if mm:
            rounds = int(mm.group(1))
        nlines = sorted((l for l in ls if 690 <= l["y"] <= 745 and ax - 30 <= l["x"] <= ax + 200),
                        key=lambda l: l["x"])
        name = "".join(l["text"] for l in nlines) or None
        # badge hue: red = that player failed, green = passed (saturated pixels only)
        region = np.asarray(img.crop((int(ax), 600, int(ax) + 170, 655))
                            .convert("RGB")).astype(float)
        mx = region.max(axis=2)
        mn = region.min(axis=2)
        sat = (mx - mn) > 60
        failed = None
        if sat.sum() > 50:
            px = region[sat]
            failed = bool(px[:, 0].mean() > px[:, 1].mean())
        local = bool(name and "TunTun鼠" in name)
        players.append({"name": name, "x": ax, "rounds": rounds,
                        "disconnected": disconnected, "failed": failed, "local": local})
        if local:
            lab["local_player"] = name
    lab["players"] = players
    lab["roster"] = []
    lab["counters"] = []
    lab["gap"] = "coop player-summary page has no roster cards / covenant counters; that page not located in recording"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("analysis_dir")
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--end", type=int, required=True)
    args = ap.parse_args()
    out = Path(args.analysis_dir)
    sess = out.parent.parent / "raw" / out.name
    ocr = RapidOCR(det_use_dml=True, rec_use_dml=True, use_cls=False)

    found = find_settlement(sess, ocr, args.start, args.end)
    if found is None:
        print("[settle] no settlement frame in range")
        return
    i, img, ls, joined = found
    lab = {"frame": i, "variant": None, "outcome": None,
           "polluted": any(m in joined for m in POLLUTION_MARKERS),
           "rounds_passed": None, "duration_s": None, "merit": None,
           "cert_cap": None, "counters": [], "roster": []}
    # Co-op detection uses strong signals only. The old ">=2 通过回合" heuristic
    # false-positived on 232000: the recorder-GUI overlay duplicates the 通过回合
    # label. 同盟通过回合 / 继续搜寻 / >=2 player names (#\d+) are co-op-specific.
    player_names = [l for l in ls if 690 <= l["y"] <= 740 and re.search(r"#\d+", l["text"])]
    is_coop = ("同盟通过回合" in joined or "继续搜寻" in joined
               or len(player_names) >= 2)
    if is_coop:
        extract_coop(img, ls, joined, lab)
    else:
        ocr_rec = RapidOCR(rec_use_dml=True, use_cls=False, use_det=False)
        rest_map = load_last_rest_covenants(out)
        extract_solo(img, ls, joined, out, lab, ocr, ocr_rec, rest_map)

    with io.open(out / "settlement.json", "w", encoding="utf-8") as f:
        json.dump(lab, f, ensure_ascii=False, indent=1)
    print(f"[settle] f{i}: variant={lab['variant']} outcome={lab['outcome']} "
          f"polluted={lab['polluted']} rounds={lab.get('rounds_passed')} "
          f"duration={lab['duration_s']}s merit={lab.get('merit')} cap={lab.get('cert_cap')}")
    if lab["variant"] == "coop":
        print(f"[settle] coop difficulty={lab.get('difficulty')} "
              f"alliance_rounds={lab.get('alliance_rounds')} local={lab.get('local_player')}")
        for p in lab["players"]:
            print(f"[settle]   player {p['name']} rounds={p['rounds']} "
                  f"disconnected={p['disconnected']}{' (local)' if p['local'] else ''}")
    else:
        cs = ", ".join(f"s{c['slot']}={c['value']}"
                       f"({c['name']}/{c['match_confidence']})" for c in lab["counters"])
        print(f"[settle] counters(provisional): {cs}")
        filled = [r for r in lab["roster"] if not r["empty"]]
        print(f"[settle] roster {len(filled)} operators: "
              + ", ".join(f"{r['slot']}={r['tier']}/lv{r['level']}" for r in filled))


if __name__ == "__main__":
    main()