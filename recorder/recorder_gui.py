"""卫戍协议录制器 · 中文图形界面（tkinter，标准库零依赖）。

与命令行版共用 capture.Recorder 核心：1fps 截图 + 点击钩子 + 10fps 视频保底。
单显示器时开始录制后窗口自动最小化，避免遮挡全屏游戏画面（遮挡会被录进去）；
全局热键 F9 停止录制。检测到第二块显示器时窗口自动放过去，不最小化。
开录前可选对局模式（单机/联机），写入 meta.json 的 mode_tag 供分析分桶。
"""

import ctypes
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
from pathlib import Path

import mss
import win32gui
from PIL import ImageTk

import capture

PREVIEW_W, PREVIEW_H = 640, 360
VK_F9 = 0x78
POLL_MS = 200


class App:
    def __init__(self, root):
        capture.set_dpi_aware()
        self.root = root
        self.rec = None
        self._photo = None
        self._stopping = False
        self._idle_ticks = 0

        root.title("卫戍协议录制器")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        tk.Label(root, text="卫戍协议录制器（被动旁观 · 零输入注入）",
                 font=("Microsoft YaHei", 12, "bold")).pack(padx=12, pady=(10, 2), anchor="w")
        self.win_var = tk.StringVar(value="正在检测游戏窗口…")
        tk.Label(root, textvariable=self.win_var, fg="#555",
                 font=("Microsoft YaHei", 9)).pack(padx=12, anchor="w")

        preview_frame = tk.Frame(root, width=PREVIEW_W, height=PREVIEW_H, bg="#111")
        preview_frame.pack(padx=12, pady=6)
        preview_frame.pack_propagate(False)
        self.preview = tk.Label(preview_frame, bg="#111", fg="#888",
                                text="开始录制后，这里显示实际录到的画面",
                                font=("Microsoft YaHei", 10))
        self.preview.pack(fill="both", expand=True)

        self.count_var = tk.StringVar(value="帧数 0    点击 0    视频帧 0    时长 00:00")
        tk.Label(root, textvariable=self.count_var,
                 font=("Consolas", 11)).pack(padx=12, anchor="w")
        self.status_var = tk.StringVar(value="未开始")
        tk.Label(root, textvariable=self.status_var, fg="#0a7d32",
                 font=("Microsoft YaHei", 10, "bold")).pack(padx=12, anchor="w")
        self.warn_var = tk.StringVar(value="")
        tk.Label(root, textvariable=self.warn_var, fg="#c0392b", wraplength=PREVIEW_W,
                 font=("Microsoft YaHei", 9)).pack(padx=12, anchor="w")

        mode_frame = tk.Frame(root)
        mode_frame.pack(padx=12, pady=(0, 2), anchor="w")
        tk.Label(mode_frame, text="对局模式", font=("Microsoft YaHei", 9)).pack(side="left")
        self.mode_var = tk.StringVar(value="单机（独立模拟）")
        self.mode_box = ttk.Combobox(mode_frame, textvariable=self.mode_var, width=18,
                                     values=["单机（独立模拟）", "联机（同盟模拟）"], state="readonly")
        self.mode_box.pack(side="left", padx=(4, 8))
        tk.Label(mode_frame, text="开录前选对，写入样本标签 mode_tag", fg="#777",
                 font=("Microsoft YaHei", 8)).pack(side="left")

        bar = tk.Frame(root)
        bar.pack(padx=12, pady=8, anchor="w")
        self.btn_start = tk.Button(bar, text="开始录制", width=12, command=self.start,
                                   font=("Microsoft YaHei", 10))
        self.btn_start.pack(side="left", padx=(0, 8))
        self.btn_stop = tk.Button(bar, text="结束录制 (F9)", width=14, command=self.stop,
                                  state="disabled", font=("Microsoft YaHei", 10))
        self.btn_stop.pack(side="left", padx=(0, 8))
        tk.Button(bar, text="打开数据目录", width=12, command=self.open_dir,
                  font=("Microsoft YaHei", 10)).pack(side="left")

        settings = tk.Frame(root)
        settings.pack(padx=12, pady=(0, 6), anchor="w")
        tk.Label(settings, text="截图帧率", font=("Microsoft YaHei", 9)).pack(side="left")
        self.fps_var = tk.StringVar(value="1")
        self.fps_box = ttk.Combobox(settings, textvariable=self.fps_var, width=4,
                                    values=["0.5", "1", "2"], state="readonly")
        self.fps_box.pack(side="left", padx=(4, 12))
        tk.Label(settings, text="视频帧率", font=("Microsoft YaHei", 9)).pack(side="left")
        self.vfps_var = tk.StringVar(value="10")
        self.vfps_box = ttk.Combobox(settings, textvariable=self.vfps_var, width=4,
                                     values=["关", "5", "10", "15"], state="readonly")
        self.vfps_box.pack(side="left", padx=(4, 0))
        tk.Label(settings, text="（下次开始录制时生效）", fg="#777",
                 font=("Microsoft YaHei", 8)).pack(side="left", padx=(6, 0))

        self.dir_var = tk.StringVar(value="数据目录：E:\\garrison-ai\\data\\raw")
        tk.Label(root, textvariable=self.dir_var, fg="#777",
                 font=("Microsoft YaHei", 8)).pack(padx=12, anchor="w")
        tk.Label(root, text="提示：开始后请点回游戏窗口正常玩；单显示器时本窗口自动最小化防遮挡，F9 全局结束。视频 10fps 约 30MB/分钟，嫌大可降档或关。",
                 fg="#777", wraplength=PREVIEW_W,
                 font=("Microsoft YaHei", 8)).pack(padx=12, pady=(2, 10), anchor="w")

        mons = mss.MSS().monitors
        if len(mons) > 2:
            m = mons[2]
            root.geometry(f"+{m['left'] + 60}+{m['top'] + 60}")
            self.multi_mon = True
        else:
            self.multi_mon = False

        self.refresh_window_label()
        self.tick()

    def refresh_window_label(self):
        win = capture.find_game()
        if win is None:
            self.win_var.set("未找到游戏窗口：请先启动明日方舟 PC 客户端")
        else:
            hwnd, cls, title, rect = win
            w, h = rect[2] - rect[0], rect[3] - rect[1]
            self.win_var.set(f"游戏窗口：{title}（{w}x{h}）")

    def start(self):
        if self.rec is not None and self.rec.running:
            return
        win = capture.find_game()
        if win is None:
            self.warn_var.set("未找到游戏窗口：请先启动明日方舟 PC 客户端，再点开始")
            return
        hwnd, cls, title, rect = win
        if win32gui.IsIconic(hwnd):
            self.warn_var.set("游戏窗口最小化了：先恢复窗口再开始")
            return
        mode_tag = "coop" if self.mode_var.get().startswith("联机") else "solo"
        self.rec = capture.Recorder(hwnd, cls, title, capture.DEFAULT_OUT,
                                    fps=float(self.fps_var.get()),
                                    video_fps=0.0 if self.vfps_var.get() == "关" else float(self.vfps_var.get()),
                                    mode_tag=mode_tag)
        self.rec.start()
        self._stopping = False
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.fps_box.config(state="disabled")
        self.vfps_box.config(state="disabled")
        self.mode_box.config(state="disabled")
        self.dir_var.set(f"数据目录：{self.rec.session_dir}")
        self.warn_var.set("")
        if not self.multi_mon:
            self.root.iconify()

    def stop(self):
        if self.rec is None or not self.rec.running or self._stopping:
            return
        self._stopping = True
        self.btn_stop.config(state="disabled")
        self.status_var.set("正在结束…")
        threading.Thread(target=self.rec.stop, daemon=True).start()

    def open_dir(self):
        target = capture.DEFAULT_OUT
        if self.rec is not None and self.rec.session_dir is not None:
            target = self.rec.session_dir
        if Path(target).exists():
            os.startfile(str(target))

    def on_close(self):
        if self.rec is not None and self.rec.running:
            self.stop()
            self._wait_close()
        else:
            self.root.destroy()

    def _wait_close(self):
        if self.rec is not None and self.rec.running:
            self.root.after(200, self._wait_close)
        else:
            self.root.destroy()

    def tick(self):
        if self.rec is not None and self.rec.running and not self._stopping:
            if ctypes.windll.user32.GetAsyncKeyState(VK_F9) & 1:
                self.stop()
        if self.rec is not None:
            r = self.rec
            e = int(r.elapsed)
            self.count_var.set(
                f"帧数 {r.n}    点击 {r.clicks}    视频帧 {r.video_frames}    时长 {e // 60:02d}:{e % 60:02d}"
            )
            if r.warnings:
                self.warn_var.set(r.warnings[-1])
            if r.last_img is not None:
                self._photo = ImageTk.PhotoImage(r.last_img.resize((PREVIEW_W, PREVIEW_H)))
                self.preview.config(image=self._photo, text="")
            if r.running:
                mode_cn = "联机" if r.mode_tag == "coop" else "单机"
                self.status_var.set(f"录制中（{mode_cn} · F9 或点结束录制）")
            else:
                self.status_var.set("已结束 · 数据已保存")
                self.btn_start.config(state="normal")
                self.btn_stop.config(state="disabled")
                self.fps_box.config(state="readonly")
                self.vfps_box.config(state="readonly")
                self.mode_box.config(state="readonly")
                self._stopping = False
        else:
            self._idle_ticks += 1
            if self._idle_ticks % 5 == 0:
                self.refresh_window_label()
        self.root.after(POLL_MS, self.tick)


def main():
    try:
        sys.stdout.reconfigure(errors="replace", line_buffering=True)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())