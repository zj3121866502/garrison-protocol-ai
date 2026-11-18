"""Live trial-run advisor watcher (形态A 休整期决策助手, M1 验收载体).

Reuses passive recording as the live frame source -- NO new capture, ZERO input
injection. The user double-clicks the recording bat (recorder writes frames
~1fps); this watcher tails the latest frame, calls the existing single-frame OCR
entries (ocr_hud.ocr_frame / ocr_shop.read_shop_frame -- algorithms unchanged),
assembles State via the canonical model path (State.from_curves_row +
replay._apply_shop), calls advise, and atomically writes data/feedback/latest.json
for advisor_gui (A lane) to display + collect ratings.

Red lines: recording user-started only; main account passive zero-injection;
bot never co-op (advise gates coop -> None); trial-run = user manual solo game.
Boundary (交接 §0.1): build -> user trial-run acceptance -> stop, no backlog churn.
Extreme gameplay removed from model (user 2026-11-18): recommendations normal-only.

Usage:
  python analysis/live_advisor.py                      # live tail latest raw session
  python analysis/live_advisor.py --session RAW_DIR    # tail a specific session
  python analysis/live_advisor.py --session RAW --once # replay-style integration check
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent          # analysis/
ROOT = HERE.parent                               # project root (for model import)
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from PIL import Image
from rapidocr_onnxruntime import RapidOCR

from ocr_hud import ocr_frame
from ocr_shop import read_shop_frame
from parse_hud import parse_row
from model.state import State
from model.kb import KB
from model.advisor import advise
from model.replay import _apply_shop

DATA_ROOT = Path("E:/garrison-ai/data")
POLL = 1.0


def latest_session(raw):
    dirs = [d for d in raw.glob("session-*") if (d / "frames").is_dir()]
    return max(dirs, key=lambda d: d.stat().st_mtime) if dirs else None


def atomic_write_json(path, obj):
    """tmp + rename so the GUI never reads a half-written latest.json."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def load_difficulty(feedback):
    """difficulty band key set by the GUI (config.json); None -> degrade."""
    cfg = feedback / "config.json"
    if cfg.exists():
        try:
            return json.loads(cfg.read_text(encoding="utf-8")).get("difficulty")
        except json.JSONDecodeError:
            return None
    return None


class Watcher:
    def __init__(self, sess, feedback, once=False):
        self.sess = sess
        self.frames = sess / "frames"
        self.feedback = feedback
        self.session = sess.name
        self.mode_tag = "solo"
        meta_p = sess / "meta.json"
        if meta_p.exists():
            self.mode_tag = json.loads(meta_p.read_text(encoding="utf-8")).get("mode_tag") or "solo"
        # OCR engines loaded once, reused per frame (resident, ~3s startup)
        self.ocr = RapidOCR(det_use_dml=True, rec_use_dml=True, use_cls=False)
        self.rec = RapidOCR(rec_use_dml=True, use_cls=False, use_det=False)
        self.kb = KB()
        self.last_round = None      # monotonic carry-forward (HUD digit intermittent)
        self.cov_env = {}           # permanent covenant envelope (stable vs OCR miss)
        self.last_key = None        # debounce: round + shop names + funds
        self.last_rec = None        # cached advise bundle (avoid recs.jsonl dup spam)
        self.last_rest_ctx = None   # last clean-rest {funds, shop_names}: kept on
        #                             non-rest/obscured frames so GUI doesn't blank
        #                             on screen-switch / combat (trial feedback 2026-11-18)
        # --once writes a separate recs log so integration tests don't pollute
        # the user's real feedback recs.jsonl
        self.recs_path = feedback / ("recs_once.jsonl" if once else "recs.jsonl")

    def process(self, fp):
        i = int(fp.stem[1:])
        img = Image.open(fp)
        row = parse_row({"i": i, "t": 0.0, "lines": ocr_frame(img, self.ocr)})
        # round carry-forward: digit read -> update (monotonic); missed -> reuse.
        rn = row.get("round")
        if rn is not None and (self.last_round is None or rn >= self.last_round):
            self.last_round = rn
        eff_round = self.last_round
        if row.get("_hidden") and self.last_round is not None:
            eff_round = self.last_round + 1   # hidden round HUD '??' = last+1; don't mutate last_round
        phase = row.get("phase")
        if phase == "rest":
            for nm, v in (row.get("covenants") or {}).items():
                if v > self.cov_env.get(nm, 0):
                    self.cov_env[nm] = v
        difficulty = load_difficulty(self.feedback)
        rec = None
        funds = None
        shop_names = []
        stale = True
        if phase == "rest":
            shop_rec = read_shop_frame(img, self.ocr, self.rec, i, None)
            if shop_rec.get("shop_state") == "clean":
                row["round"] = eff_round
                state = State.from_curves_row(row, session=self.session,
                                              mode_tag=self.mode_tag, difficulty=difficulty)
                _apply_shop(state, shop_rec, self.kb)   # canonical: funds + normalized shop
                state.covenants_rest = dict(self.cov_env)
                funds = state.funds
                shop_names = [s.name for s in state.shop]
                key = (eff_round, tuple(shop_names), funds)
                if key != self.last_key:
                    rec = advise(state, self.kb, top_k=3, log_path=self.recs_path)
                    self.last_key = key
                    self.last_rec = rec
                else:
                    rec = self.last_rec       # unchanged decision -> reuse (no recs.jsonl dup)
                self.last_rest_ctx = {"funds": funds, "shop_names": shop_names}
                stale = False
        if stale:
            # non-rest / obscured rest: retain the last clean-rest recommendation AND
            # its shop/funds so the GUI does not blank on screen-switch or combat
            # transitions (user trial feedback 2026-11-18 "切屏再切回去后不推荐了").
            # Do NOT reset last_key: returning to the same rest state reuses the cached
            # rec instead of re-logging a duplicate (fixes rec2/rec3 same-hash spam).
            rec = self.last_rec
            if self.last_rest_ctx:
                funds = self.last_rest_ctx["funds"]
                shop_names = self.last_rest_ctx["shop_names"]
        # ALWAYS write latest.json (contract with advisor_gui): nested rec (may be
        # null only before the first clean rest, or coop/round=None) + state_ctx.
        # stale=True marks a retained (non-current-phase) rec so the GUI can gray it.
        # GUI judges alive by updated_at; rec=null -> shows 局面 + 「暂无推荐」.
        latest = {
            "rec": rec,
            "state_ctx": {
                "funds": funds, "life": row.get("life"),
                "life_incoming": row.get("life_incoming"), "difficulty": difficulty,
                "shop_names": shop_names, "covenants_rest": dict(self.cov_env),
                "frame": i, "round": eff_round, "phase": phase,
                "hidden": bool(row.get("_hidden")), "stale": stale,
                "updated_at": round(time.time(), 3),
            },
        }
        atomic_write_json(self.feedback / "latest.json", latest)
        return rec

    def run_once(self, frame_list=None):
        if frame_list:
            frames = [self.frames / f"f{i:06d}.png" for i in frame_list]
            frames = [fp for fp in frames if fp.exists()]
        else:
            frames = sorted(self.frames.glob("f*.png"))
        n = 0
        for fp in frames:
            try:
                rec = self.process(fp)
            except Exception as e:
                print(f"[live] f{int(fp.stem[1:])} error: {e} (skip)", flush=True)
                continue
            if rec:
                n += 1
                tag = f"r{rec['round']} recs={len(rec['options'])} veto={rec['hard_veto']}"
            else:
                tag = "rec=null (state_ctx written)"
            print(f"[live] f{int(fp.stem[1:])} {tag} -> latest.json", flush=True)
        print(f"[live] --once done: {len(frames)} frames, {n} recommendations, "
              f"recs={self.recs_path.name}", flush=True)

    def run_live(self):
        print(f"[live] tailing {self.sess.name} mode={self.mode_tag} "
              f"poll={POLL}s (Ctrl+C to stop)", flush=True)
        if self.mode_tag == "coop":
            print("[live] WARNING: latest session is COOP. Bot never co-op -> all "
                  "recommendations gated (rec=null). Start a SOLO recording first, "
                  "then relaunch so the watcher tails your new solo session.", flush=True)
        last_i = 0
        while True:
            frames = sorted(self.frames.glob("f*.png"))
            if frames:
                fp = frames[-1]                 # latest frame only (real-time, drop lag)
                i = int(fp.stem[1:])
                if i > last_i:
                    last_i = i
                    try:
                        rec = self.process(fp)
                        if rec:
                            print(f"[live] f{i} r{rec['round']} "
                                  f"recs={len(rec['options'])} -> latest.json", flush=True)
                    except Exception as e:
                        print(f"[live] f{i} error: {e} (skip)", flush=True)
            time.sleep(POLL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=None, help="raw session dir (default: latest)")
    ap.add_argument("--data-root", default=str(DATA_ROOT))
    ap.add_argument("--once", action="store_true", help="replay-style integration check, then exit")
    ap.add_argument("--frames", default="", help="with --once: only these frame numbers (CSV)")
    args = ap.parse_args()
    data = Path(args.data_root)
    raw = data / "raw"                       # big frame store stays on E: (bulk)
    # feedback small json co-locates with the frozen model/GUI/calibrate anchor
    # (ROOT/data/feedback, project D:). advisor_gui FEEDBACK / advisor FEEDBACK_DIR
    # / calibrate / report all read here -- writing E: would split the feedback
    # loop (GUI never sees latest.json, recs/ratings join fails). A review 2026-11-18.
    feedback = ROOT / "data" / "feedback"
    sess = Path(args.session) if args.session else latest_session(raw)
    if sess is None or not (sess / "frames").is_dir():
        print("[live] no session frames found; start recording first (user bat)", flush=True)
        return
    w = Watcher(sess, feedback, once=args.once)
    if args.once:
        fl = [int(x) for x in args.frames.split(",") if x.strip()] or None
        w.run_once(fl)
    else:
        try:
            w.run_live()
        except KeyboardInterrupt:
            print("[live] stopped", flush=True)


if __name__ == "__main__":
    main()