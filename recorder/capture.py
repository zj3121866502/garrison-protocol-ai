"""Garrison Protocol passive recorder.

Captures the Arknights PC client window at ~1 fps and logs mouse clicks
(window-client coordinates) via a low-level hook. Pure observation:
no input is ever injected into the game.

Capture uses mss (on-screen region grab): BitBlt from the window DC
freezes on Unity/D3D clients, returning the first frame forever.
The game window must be visible on screen (not minimized/covered).

Usage:
    python capture.py --list
    python capture.py --record [--fps 1.0] [--mode solo|coop] [--title SUBSTR] [--out DIR]
"""

import argparse
import ctypes
import hashlib
import json
import shutil
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import mss
import win32gui
from PIL import Image

GAME_TITLE_HINTS = ("明日方舟", "arknights")
GAME_CLASS_HINTS = ("UnityWndClass",)
DEFAULT_OUT = Path(r"E:\garrison-ai\data\raw")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_MOUSE_LL = 14
WM_QUIT = 0x0012
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205


def set_dpi_aware():
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def enum_windows():
    out = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            out.append(
                (
                    hwnd,
                    win32gui.GetClassName(hwnd),
                    win32gui.GetWindowText(hwnd),
                    win32gui.GetWindowRect(hwnd),
                )
            )
        return True

    win32gui.EnumWindows(cb, None)
    return out


def find_game(title_override=None):
    cands = []
    for hwnd, cls, title, rect in enum_windows():
        t = title.lower()
        if title_override:
            if title_override.lower() in t:
                cands.append((2, hwnd, cls, title, rect))
        else:
            if any(h.lower() in t for h in GAME_TITLE_HINTS):
                cands.append((2, hwnd, cls, title, rect))
            elif cls in GAME_CLASS_HINTS:
                cands.append((1, hwnd, cls, title, rect))
    if not cands:
        return None
    cands.sort(
        key=lambda c: (c[0], (c[4][2] - c[4][0]) * (c[4][3] - c[4][1])),
        reverse=True,
    )
    return cands[0][1:]


class Capturer:
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self._mss = mss.MSS()

    def grab(self):
        hwnd = self.hwnd
        _, _, cw, ch = win32gui.GetClientRect(hwnd)
        if cw <= 0 or ch <= 0:
            raise RuntimeError("empty client rect")
        cl, ct = win32gui.ClientToScreen(hwnd, (0, 0))
        shot = self._mss.grab(
            {"left": cl, "top": ct, "width": cw, "height": ch}
        )
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        return img, "mss", cw, ch


class VideoRecorder(threading.Thread):
    """Safety-net layer: continuous h264 video of the client region.

    Runs in its own thread with its own mss instance and ffmpeg process,
    so a stall in the 1fps frame path does not stop the video. The region
    is fixed at start: do not move/resize the game window while recording.
    """

    def __init__(self, hwnd, path, fps, log_path):
        super().__init__(daemon=True)
        self.hwnd = hwnd
        self.path = path
        self.fps = fps
        self.log_path = log_path
        self.ready = threading.Event()
        self.ok = False
        self.frames = 0
        self.start_t = None
        self.region = None
        self._stop_evt = threading.Event()
        self._proc = None
        self._log = None

    def run(self):
        exe = shutil.which("ffmpeg")
        if not exe:
            print("[warn] ffmpeg not found on PATH, video layer disabled")
            self.ready.set()
            return
        try:
            _, _, cw, ch = win32gui.GetClientRect(self.hwnd)
            cl, ct = win32gui.ClientToScreen(self.hwnd, (0, 0))
            if cw <= 0 or ch <= 0:
                raise RuntimeError("empty client rect")
            self.region = {"left": cl, "top": ct, "width": cw, "height": ch}
            self._log = open(self.log_path, "w", encoding="utf-8", errors="replace")
            self._proc = subprocess.Popen(
                [
                    exe, "-hide_banner", "-loglevel", "warning", "-y",
                    "-f", "rawvideo", "-pix_fmt", "bgra",
                    "-s", f"{cw}x{ch}", "-r", str(self.fps), "-i", "-",
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-pix_fmt", "yuv420p", str(self.path),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=self._log,
            )
            self._mss = mss.MSS()
        except Exception as e:
            print(f"[warn] video layer init failed: {e}")
            self.ready.set()
            return
        self.ok = True
        self.ready.set()
        interval = 1.0 / self.fps
        try:
            while not self._stop_evt.is_set():
                tick = time.time()
                try:
                    shot = self._mss.grab(self.region)
                    if self.start_t is None:
                        self.start_t = time.time()
                    self._proc.stdin.write(shot.bgra)
                    self.frames += 1
                except (BrokenPipeError, OSError) as e:
                    print(f"[warn] video pipe broken, video layer stopped: {e}")
                    self.ok = False
                    break
                sleep = interval - (time.time() - tick)
                if sleep > 0:
                    self._stop_evt.wait(sleep)
        finally:
            try:
                if self._proc is not None:
                    if self._proc.stdin:
                        self._proc.stdin.close()
                    self._proc.wait(timeout=15)
            except Exception:
                if self._proc is not None:
                    self._proc.terminate()
            if self._log is not None:
                self._log.close()

    def stop(self):
        self._stop_evt.set()


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int,
    HOOKPROC,
    wintypes.HINSTANCE,
    wintypes.DWORD,
]
user32.SetWindowsHookExW.restype = wintypes.HANDLE
user32.CallNextHookEx.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.PostThreadMessageW.argtypes = [
    wintypes.DWORD,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]


class MouseHook(threading.Thread):
    def __init__(self, hwnd, path):
        super().__init__(daemon=True)
        self.hwnd = hwnd
        self.path = path
        self.ready = threading.Event()
        self.ok = False
        self.count = 0
        self.tid = None
        self._proc = None

    def run(self):
        self.tid = kernel32.GetCurrentThreadId()
        f = open(self.path, "a", encoding="utf-8")

        def cb(nCode, wParam, lParam):
            if nCode >= 0 and wParam in (
                WM_LBUTTONDOWN,
                WM_LBUTTONUP,
                WM_RBUTTONDOWN,
                WM_RBUTTONUP,
            ):
                try:
                    if win32gui.GetForegroundWindow() == self.hwnd:
                        info = ctypes.cast(
                            lParam, ctypes.POINTER(MSLLHOOKSTRUCT)
                        ).contents
                        sx, sy = info.pt.x, info.pt.y
                        cx, cy = win32gui.ScreenToClient(self.hwnd, (sx, sy))
                        rec = {
                            "t": time.time(),
                            "button": "left"
                            if wParam in (WM_LBUTTONDOWN, WM_LBUTTONUP)
                            else "right",
                            "event": "down"
                            if wParam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN)
                            else "up",
                            "x": cx,
                            "y": cy,
                            "sx": sx,
                            "sy": sy,
                        }
                        f.write(json.dumps(rec) + "\n")
                        f.flush()
                        self.count += 1
                except Exception as e:
                    self._hook_err = getattr(self, "_hook_err", 0) + 1
                    if self._hook_err == 1 or self._hook_err % 50 == 0:
                        print(f"[warn] mouse hook callback error x{self._hook_err}: {e!r}", flush=True)
            return user32.CallNextHookEx(None, nCode, wParam, lParam)

        self._proc = HOOKPROC(cb)
        hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        if not hook:
            print(f"[warn] SetWindowsHookEx failed, error={kernel32.GetLastError()}")
            f.close()
            self.ready.set()
            return
        self.ok = True
        self.ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(hook)
        f.close()

    def stop(self):
        if self.tid:
            user32.PostThreadMessageW(self.tid, WM_QUIT, 0, 0)


def list_windows():
    set_dpi_aware()
    wins = enum_windows()
    print(f"[list] {len(wins)} visible top-level windows:")
    for hwnd, cls, title, rect in wins:
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        mark = ""
        if any(hint.lower() in title.lower() for hint in GAME_TITLE_HINTS) or cls in GAME_CLASS_HINTS:
            mark = "  <-- GAME CANDIDATE"
        print(f"  hwnd={hwnd:<10} class={cls:<30} size={w}x{h} title={title!r}{mark}")
    return 0


class Recorder:
    """Core recording session shared by CLI and GUI.

    Runs 1fps frame capture + click hook + optional video in a worker
    thread; exposes live state (n, clicks, video_frames, last_img,
    warnings) for the GUI to poll.
    """

    def __init__(self, hwnd, cls, title, out_root, fps=1.0, video_fps=10.0, mode_tag="solo"):
        if mode_tag not in ("solo", "coop"):
            raise ValueError(f"mode_tag must be 'solo' or 'coop', got {mode_tag!r}")
        self.hwnd = hwnd
        self.cls = cls
        self.title = title
        self.out_root = Path(out_root)
        self.fps = fps
        self.video_fps = video_fps
        self.mode_tag = mode_tag
        self.session_dir = None
        self.running = False
        self.n = 0
        self.video_frames = 0
        self.t0 = None
        self.last_img = None
        self.last_method = None
        self.warnings = []
        self.hook = None
        self.video = None
        self.meta = None
        self._stop_evt = threading.Event()
        self._thread = None

    @property
    def clicks(self):
        return self.hook.count if self.hook else 0

    @property
    def elapsed(self):
        return time.time() - self.t0 if self.t0 else 0.0

    def _warn(self, msg):
        self.warnings.append(msg)
        print(f"[warn] {msg}")

    def _write_meta(self):
        (self.session_dir / "meta.json").write_text(
            json.dumps(self.meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def start(self):
        if self.running:
            return
        self.session_dir = self.out_root / datetime.now().strftime("session-%Y%m%d-%H%M%S")
        (self.session_dir / "frames").mkdir(parents=True, exist_ok=True)
        self.meta = {
            "start": time.time(),
            "start_local": datetime.now().isoformat(timespec="seconds"),
            "hwnd": self.hwnd,
            "class": self.cls,
            "title": self.title,
            "fps": self.fps,
            "mode": "passive-record",
            "mode_tag": self.mode_tag,
            "note": "human play, no input injection",
        }
        self._write_meta()

        self.hook = MouseHook(self.hwnd, self.session_dir / "clicks.jsonl")
        self.hook.start()
        self.hook.ready.wait(5)
        if self.hook.ok:
            print("[init] mouse hook installed (clicks -> clicks.jsonl)")
        else:
            self._warn("mouse hook unavailable, capture-only mode")

        if self.video_fps > 0:
            self.video = VideoRecorder(
                self.hwnd, self.session_dir / "video.mp4",
                self.video_fps, self.session_dir / "ffmpeg.log",
            )
            self.video.start()
            self.video.ready.wait(5)
            if self.video.ok:
                self.meta["video"] = {
                    "file": "video.mp4",
                    "fps": self.video_fps,
                    "region": self.video.region,
                }
                print(f"[init] video layer: {self.video_fps} fps h264 -> video.mp4 (region fixed, do not move/resize the game window)")
            else:
                self._warn("video layer unavailable, frames-only recording")
                self.video = None
        self._write_meta()

        self.t0 = time.time()
        self._stop_evt.clear()
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print(f"[rec] session dir: {self.session_dir}")
        print(f"[rec] capturing at {self.fps} fps, mode_tag={self.mode_tag}. Play your game. Ctrl+C to stop.")

    def _loop(self):
        cap = Capturer(self.hwnd)
        frames_f = open(self.session_dir / "frames.jsonl", "a", encoding="utf-8")
        interval = 1.0 / self.fps
        last_status = time.time()
        last_hash = None
        identical_run = 0
        try:
            while not self._stop_evt.is_set():
                tick = time.time()
                if not win32gui.IsWindow(self.hwnd):
                    self._warn("game window closed, stopping.")
                    break
                if win32gui.IsIconic(self.hwnd):
                    self._stop_evt.wait(1.0)
                    continue
                try:
                    img, method, cw, ch = cap.grab()
                except Exception as e:
                    self._warn(f"capture failed: {e}")
                    self._stop_evt.wait(1.0)
                    continue
                self.n += 1
                fname = f"f{self.n:06d}.png"
                img.save(self.session_dir / "frames" / fname)
                h = hashlib.md5(img.tobytes()).hexdigest()
                identical_run = identical_run + 1 if h == last_hash else 1
                last_hash = h
                if identical_run == 5 or (identical_run > 5 and (identical_run - 5) % 30 == 0):
                    self._warn(f"{identical_run} identical frames in a row. If you are actively playing, capture is frozen - keep the game window visible on screen.")
                self.last_img = img
                self.last_method = method
                fg = win32gui.GetForegroundWindow() == self.hwnd
                frames_f.write(
                    json.dumps(
                        {
                            "i": self.n,
                            "t": time.time(),
                            "file": f"frames/{fname}",
                            "w": cw,
                            "h": ch,
                            "method": method,
                            "fg": fg,
                            "hash": h,
                        }
                    )
                    + "\n"
                )
                frames_f.flush()
                if self.video is not None:
                    self.video_frames = self.video.frames
                now = time.time()
                if now - last_status >= 30:
                    print(f"[rec] frames={self.n} clicks={self.clicks} video={self.video_frames} elapsed={int(now - self.t0)}s")
                    last_status = now
                sleep = interval - (time.time() - tick)
                if sleep > 0:
                    self._stop_evt.wait(sleep)
        finally:
            self.hook.stop()
            self.hook.join(3)
            if self.video is not None:
                self.video.stop()
                self.video.join(20)
                self.meta["video"].update(
                    {"start": self.video.start_t, "frames": self.video.frames, "ok": self.video.ok}
                )
            frames_f.close()
            self.meta["end"] = time.time()
            self.meta["frames"] = self.n
            self.meta["clicks"] = self.clicks
            self._write_meta()
            print(f"[done] frames={self.n} clicks={self.clicks} duration={int(time.time() - self.t0)}s")
            print(f"[done] data dir: {self.session_dir}")
            self.running = False

    def stop(self):
        self._stop_evt.set()
        if self._thread is not None:
            self._thread.join(30)


def record(args):
    set_dpi_aware()
    if args.fps <= 0:
        print("[error] --fps must be > 0")
        return 1
    win = find_game(args.title)
    if win is None:
        print("[error] game window not found. Launch the Arknights PC client first.")
        print("[hint] use --list to see all windows, or --title <substring> to match manually.")
        return 1
    hwnd, cls, title, rect = win
    print(f"[init] game window: hwnd={hwnd} class={cls} title={title!r} rect={rect}")
    if win32gui.IsIconic(hwnd):
        print("[warn] window is minimized. Restore it before playing.")

    rec = Recorder(
        hwnd, cls, title, args.out,
        fps=args.fps,
        video_fps=0.0 if args.no_video else args.video_fps,
        mode_tag=args.mode,
    )
    rec.start()
    try:
        while rec.running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[rec] Ctrl+C received, stopping...")
        rec.stop()
    return 0


def main():
    try:
        sys.stdout.reconfigure(errors="replace", line_buffering=True)
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Garrison Protocol passive recorder")
    p.add_argument("--list", action="store_true", help="list visible windows")
    p.add_argument("--record", action="store_true", help="start recording")
    p.add_argument("--fps", type=float, default=1.0)
    p.add_argument("--mode", choices=["solo", "coop"], default="solo",
                   help="game mode tag written to meta.json: solo=independent sim, coop=alliance sim")
    p.add_argument("--video-fps", type=float, default=10.0, help="safety-net video framerate (0 or --no-video to disable)")
    p.add_argument("--no-video", action="store_true", help="disable the video layer")
    p.add_argument("--title", type=str, default=None, help="window title substring override")
    p.add_argument("--out", type=str, default=str(DEFAULT_OUT))
    args = p.parse_args()
    if args.list:
        return list_windows()
    if args.record:
        return record(args)
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())