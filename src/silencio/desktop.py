"""Silencio's Windows desktop entry point, also used by the frozen executable."""
from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any

from silencio.desktop_support import (
    PROFILES, VERSION, Preferences, configure_logging, consume_command,
    data_directory, request_existing, set_login_start, start_guardian, watch_parent,
)
from silencio.graph import default_state_path
from silencio.runtime import LiveInstance
from silencio.updates import Update, check_for_update, download_update, launch_installer


class DesktopWindow:
    def __init__(self, state_path: Path, preferences: Preferences, *, background: bool, first_run: bool) -> None:
        import tkinter as tk
        from tkinter import ttk
        from silencio.desktop_runtime import DesktopRuntime

        self.tk = tk
        self.state_path = state_path
        self.preferences = preferences
        self.root = tk.Tk()
        self.root.title("Silencio")
        icon_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2] / "packaging"))
        icon_path = icon_root / "assets" / "silencio.ico"
        if icon_path.is_file():
            self.root.iconbitmap(str(icon_path))  # type: ignore[no-untyped-call]
        self.root.geometry("580x740")
        self.root.minsize(540, 720)
        self.root.configure(bg="#101719")
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.ui_actions: queue.Queue[str] = queue.Queue()
        self.update_events: queue.Queue[tuple[str, Any, bool]] = queue.Queue()
        self.available_update: Update | None = None
        self.update_busy = False
        self.tray: Any = None
        self.closing = False
        self.running = False
        self.enabled = False
        self.outputs: list[tuple[str, str]] = []
        self.last_health: dict[str, Any] = {}
        self.last_title = ""
        self.last_view: tuple[Any, ...] | None = None
        self.runtime = DesktopRuntime(state_path, preferences, first_run=first_run)
        self.root.report_callback_exception = self.callback_error
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground="#243236", background="#243236",
                        foreground="#f3f7f5", arrowcolor="#73e0b1", padding=10, borderwidth=0)
        style.map("TCombobox", fieldbackground=[("readonly", "#243236")],
                  foreground=[("readonly", "#f3f7f5")], selectbackground=[("readonly", "#243236")])
        self.root.option_add("*TCombobox*Listbox.background", "#243236")
        self.root.option_add("*TCombobox*Listbox.foreground", "#f3f7f5")
        self.root.option_add("*Font", "{Segoe UI} 10")
        body = tk.Frame(self.root, bg="#101719", padx=32, pady=26)
        body.pack(fill="both", expand=True)
        top = tk.Frame(body, bg="#101719")
        top.pack(fill="x")
        tk.Label(top, text="silencio", font=("Segoe UI", 28, "bold"), fg="#f3f7f5", bg="#101719").pack(side="left")
        tk.Label(top, text="ON YOUR DEVICE", font=("Segoe UI", 9, "bold"), fg="#73e0b1", bg="#101719").pack(side="right", pady=10)
        tk.Label(body, text="Less Music. More of what is being said.", fg="#9daeb0", bg="#101719").pack(anchor="w", pady=(2, 26))
        card = tk.Frame(body, bg="#1b272a", padx=24, pady=22)
        card.pack(fill="x")
        self.status = tk.Label(card, text="Getting ready", font=("Segoe UI", 19, "bold"), fg="#f3f7f5", bg="#1b272a", anchor="w")
        self.status.pack(fill="x")
        self.detail = tk.Label(card, text="Connecting your audio…", fg="#aebcbe", bg="#1b272a", wraplength=440, justify="left", height=3, anchor="nw")
        self.detail.pack(fill="x", pady=(8, 14))
        self.toggle = tk.Button(card, text="Starting…", command=lambda: self.runtime.send("toggle"),
            font=("Segoe UI", 12, "bold"), bg="#73e0b1", fg="#10221b", activebackground="#9bebc8",
            relief="flat", bd=0, padx=16, pady=12, cursor="hand2", state="disabled")
        self.toggle.pack(fill="x")
        self.metric = tk.Label(card, text="Audio stays on this computer", fg="#8fa5a8", bg="#1b272a", font=("Segoe UI", 9))
        self.metric.pack(pady=(12, 0))
        tk.Label(body, text="PLAY THROUGH", fg="#9daeb0", bg="#101719", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(23, 7))
        self.output_var = tk.StringVar()
        self.output_box = ttk.Combobox(body, textvariable=self.output_var, state="readonly")
        self.output_box.pack(fill="x")
        self.output_box.bind("<<ComboboxSelected>>", lambda _: self.select_output())
        tk.Label(body, text="FILTER", fg="#9daeb0", bg="#101719", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(17, 7))
        self.profile_var = tk.StringVar(value=next(name for name, profile in PROFILES.items() if profile == preferences.profile))
        profile = ttk.Combobox(body, textvariable=self.profile_var, values=list(PROFILES), state="readonly")
        profile.pack(fill="x")
        profile.bind("<<ComboboxSelected>>", lambda _: self.runtime.send("profile", PROFILES[self.profile_var.get()]))
        self.login_var = tk.BooleanVar(value=preferences.start_with_windows)
        tk.Checkbutton(body, text="Start with Windows", variable=self.login_var, command=self.change_startup,
            bg="#101719", fg="#d8e2e2", selectcolor="#243236", activebackground="#101719",
            activeforeground="#f3f7f5", highlightthickness=0, bd=0).pack(anchor="w", pady=(18, 10))
        footer = tk.Frame(body, bg="#101719")
        footer.pack(fill="x", side="bottom")
        self.update_button = tk.Button(body, text="Check for updates", command=self.update_action,
            bg="#101719", fg="#73e0b1", activebackground="#243236", activeforeground="#ffffff",
            relief="flat", cursor="hand2", padx=6)
        self.update_button.pack(anchor="w", side="bottom", pady=(0, 6))
        for title, callback in (("Help & details", self.details), ("Open logs", self.open_logs), ("Quit", self.quit)):
            tk.Button(footer, text=title, command=callback, bg="#101719", fg="#aebcbe", activebackground="#243236",
                      activeforeground="#ffffff", relief="flat", cursor="hand2", padx=6).pack(side="left" if title != "Quit" else "right")
        self.create_tray()
        if background and self.tray is not None:
            self.root.withdraw()
        self.runtime.start()
        self.root.after(150, self.poll)
        if getattr(sys, "frozen", False):
            self.root.after(10_000, lambda: self.check_updates(manual=False))

    def check_updates(self, *, manual: bool) -> None:
        if not manual and not self.closing:
            self.root.after(24 * 60 * 60 * 1000, lambda: self.check_updates(manual=False))
        if self.closing or self.update_busy:
            return
        self.update_busy = True
        self.update_button.configure(text="Checking for updates…", state="disabled")

        def worker() -> None:
            try:
                self.update_events.put(("checked", check_for_update(), manual))
            except Exception as exc:
                logging.info("Update check failed: %s", exc)
                self.update_events.put(("error", "Could not check for updates. Check your internet connection and try again.", manual))

        threading.Thread(target=worker, daemon=True, name="update-check").start()

    def update_action(self) -> None:
        from tkinter import messagebox

        update = self.available_update
        if update is None:
            self.check_updates(manual=True)
            return
        if self.closing or self.update_busy:
            return
        if not messagebox.askyesno("Update Silencio",
                f"Download Silencio {update.version} and open its installer?\n\n"
                "Setup will close Silencio and restore ordinary playback before updating. "
                "Your preferences will be kept.", parent=self.root):
            return
        self.update_busy = True
        self.update_button.configure(text="Downloading update…", state="disabled")

        def worker() -> None:
            try:
                path = download_update(update, data_directory() / "updates")
                self.update_events.put(("downloaded", path, True))
            except Exception as exc:
                logging.warning("Update download failed: %s", exc)
                self.update_events.put(("error", "The update could not be downloaded and verified. Please try again.", True))

        threading.Thread(target=worker, daemon=True, name="update-download").start()

    def poll_updates(self) -> None:
        from tkinter import messagebox

        while not self.update_events.empty():
            action, value, manual = self.update_events.get_nowait()
            self.update_busy = False
            if self.closing:
                continue
            if action == "checked":
                self.available_update = value
                if value is None and manual:
                    messagebox.showinfo("Silencio updates", "You're up to date.", parent=self.root)
            elif action == "downloaded":
                try:
                    launch_installer(value)
                except OSError as exc:
                    logging.warning("Could not open installer: %s", exc)
                    messagebox.showerror("Silencio updates", "Could not open the installer. Please try again.", parent=self.root)
            elif manual:
                messagebox.showerror("Silencio updates", value, parent=self.root)
            self.update_button.configure(state="normal", text=(
                f"Install update {self.available_update.version}" if self.available_update else "Check for updates"))

    def callback_error(self, kind: Any, error: Any, trace: Any) -> None:
        from tkinter import messagebox
        logging.error("UI action failed", exc_info=(kind, error, trace))
        messagebox.showerror("Silencio", f"That action could not finish: {error}", parent=self.root)

    def create_tray(self) -> None:
        try:
            import pystray
            from PIL import Image, ImageDraw
            image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((4, 4, 60, 60), radius=16, fill="#172629")
            for x, height in ((20, 14), (30, 34), (40, 24)):
                draw.rounded_rectangle((x, 32-height//2, x+5, 32+height//2), radius=2, fill="#73e0b1")
            self.tray = pystray.Icon("Silencio", image, "Silencio — starting")
            self.tray.menu = pystray.Menu(
                pystray.MenuItem("Open Silencio", lambda *_: self.ui_actions.put("show"), default=True),
                pystray.MenuItem("Suppress Music", lambda *_: self.runtime.send("toggle"),
                    checked=lambda _: self.enabled, enabled=lambda _: self.running),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", lambda *_: self.ui_actions.put("quit")))
            self.tray.run_detached()
        except Exception:
            logging.exception("Tray unavailable; keeping window accessible")
            self.tray = None

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide(self) -> None:
        if self.tray is None:
            self.quit()
        else:
            self.root.withdraw()

    def quit(self) -> None:
        if not self.closing:
            self.closing = True
            self.show()
            self.status.configure(text="Restoring your audio")
            self.detail.configure(text="Closing Silencio…")
            self.toggle.configure(state="disabled")
            self.runtime.send("quit")

    def select_output(self) -> None:
        index = self.output_box.current()
        if 0 <= index < len(self.outputs):
            self.runtime.send("output", self.outputs[index][0])

    def change_startup(self) -> None:
        enabled = self.login_var.get()
        try:
            set_login_start(enabled)
        except Exception:
            self.login_var.set(not enabled)
            raise
        self.preferences.start_with_windows = enabled
        self.preferences.save(self.state_path.with_suffix(".preferences.json"))

    def open_logs(self) -> None:
        os.startfile(data_directory() / "logs")

    def details(self) -> None:
        from tkinter import messagebox
        health = self.last_health
        messagebox.showinfo("About Silencio", f"Silencio {VERSION}\n\n"
            "Music suppression for spoken Vocal. Singing and SFX may also be removed. Some overlapping Music can remain.\n\n"
            "Closing this window keeps Silencio in the tray. Quit restores normal playback. Ctrl+Alt+M toggles the filter.\n\n"
            "Use Windows volume or your volume keys as usual. Zero and mute silence playback with the filter on or off.\n\n"
            "If an app bypasses filtering, select Default in its audio settings and restart playback. Exclusive or protected audio may bypass capture.\n\n"
            "Everything runs locally. Silencio does not record audio or access your microphone.\n\n"
            f"Audio dropouts: {health.get('underruns', 0)} · Buffer overruns: {health.get('overruns', 0)}\n"
            f"Processing deadline misses: {health.get('deadline_misses', 0)}\n\n"
            "VB-CABLE by VB-Audio · www.vb-cable.com\nVB-CABLE is donationware; contributions are welcome.\n"
            "Third-party notices are included in the installation folder.", parent=self.root)

    def poll(self) -> None:
        self.poll_updates()
        command = consume_command(self.state_path)
        if command:
            self.ui_actions.put(command)
        while not self.ui_actions.empty():
            action = self.ui_actions.get_nowait()
            if action == "show":
                self.show()
            elif action == "quit":
                self.quit()
        while not self.runtime.events.empty():
            event = self.runtime.events.get_nowait()
            if event.get("stopped"):
                if self.closing:
                    if self.tray:
                        self.tray.stop()
                    self.root.destroy()
                    return
                self.show()
                self.toggle.configure(text="Close", state="normal", command=self.close_stopped)
                continue
            if "outputs" in event:
                if event["outputs"] != self.outputs:
                    self.outputs = event["outputs"]
                    self.output_box.configure(values=[name for _, name in self.outputs])
            if "selected_output" in event:
                for index, (identifier, _) in enumerate(self.outputs):
                    if identifier == event["selected_output"]:
                        self.output_box.current(index)
            if "title" not in event or self.closing:
                continue
            self.running = bool(event.get("running"))
            self.enabled = bool(event.get("enabled"))
            if self.running:
                self.last_health = event
            view = (event["title"], event["detail"], self.running, self.enabled,
                    bool(event.get("restart")), bool(event.get("busy")), bool(event.get("driver")),
                    bool(event.get("error")), f"{event['latency_ms']:.0f}" if self.running else "",
                    bool(event.get("muted")))
            # Keep diagnostics current without redrawing unchanged controls
            # four times per second alongside the real-time audio callbacks.
            if view == self.last_view:
                continue
            self.last_view = view
            new_title = self.last_title != event["title"]
            self.last_title = event["title"]
            self.status.configure(text=event["title"], font=("Segoe UI", 18, "bold"))
            self.detail.configure(text=event["detail"])
            if self.running:
                self.toggle.configure(text="Turn suppression off" if self.enabled else "Turn suppression on",
                    state="normal", command=lambda: self.runtime.send("toggle"))
                self.metric.configure(text=("Muted  ·  " if event.get("muted") else "") +
                    f"{event['latency_ms']:.0f} ms estimated delay  ·  Local processing")
            else:
                self.metric.configure(text="Audio stays on this computer")
                if event.get("restart"):
                    self.toggle.configure(text="Restart Windows when you're ready", state="disabled")
                    if new_title:
                        self.show()
                elif event.get("busy"):
                    self.toggle.configure(text="Installing…", state="disabled")
                else:
                    driver = bool(event.get("driver"))
                    self.toggle.configure(text="Set up audio" if driver else "Retry", state="normal",
                        command=lambda action="driver" if driver else "retry": self.runtime.send(action))
                    if new_title and (event.get("error") or driver):
                        self.show()
            if self.tray:
                title = "Silencio — " + ("ON" if self.enabled else "OFF") if self.running else "Silencio — needs attention"
                if self.tray.title != title:
                    self.tray.title = title
                    self.tray.update_menu()
        self.root.after(250, self.poll)

    def close_stopped(self) -> None:
        if self.tray:
            self.tray.stop()
        self.root.destroy()


def self_test(report_path: Path) -> int:
    """Exercise the shipped native libraries and every model, with no routing changes."""
    import numpy as np
    import sounddevice as sd
    import tkinter as tk
    import pystray
    from PIL import Image
    from silencio.boost import build_boosted_live_engine
    from silencio.windows_audio import WindowsAudio

    results: dict[str, Any] = {"version": VERSION, "frozen": bool(getattr(sys, "frozen", False)), "models": {}}
    try:
        root = tk.Tk()
        root.withdraw()
        root.update()
        root.destroy()
        Image.new("RGB", (8, 8))
        assert pystray.Icon
        for profile in PROFILES.values():
            engine = build_boosted_live_engine(prefer="cpu", profile=profile, enabled=True)
            probe = np.random.default_rng(24).normal(0, .005, (480, 2)).astype(np.float32)
            for _ in range(30):
                output = engine.process_block(probe)
                assert output.shape == probe.shape and np.all(np.isfinite(output))
            results["models"][profile] = "passed"
        results["portaudio"] = sd.get_portaudio_version()[1]
        audio = WindowsAudio()
        try:
            results["playback_devices"] = [device.name for device in audio.endpoints()]
        finally:
            audio.close()
        results["passed"] = True
    except Exception as exc:
        logging.exception("Packaged self-test failed")
        results.update(passed=False, error=str(exc))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0 if results["passed"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--first-run", action="store_true")
    parser.add_argument("--quit", action="store_true")
    parser.add_argument("--watch", type=int)
    parser.add_argument("--state", type=Path, default=None)
    parser.add_argument("--self-test", type=Path)
    parser.add_argument("--no-startup", action="store_true", help="leave launch-at-login unchanged (developer testing)")
    parser.add_argument("--profile", choices=list(PROFILES.values()), default=None)
    args = parser.parse_args(argv)
    state = args.state or default_state_path()
    configure_logging()
    if args.self_test:
        return self_test(args.self_test)
    if args.watch is not None:
        return watch_parent(args.watch, state)
    if args.quit:
        request_existing(state, "quit")
        for _ in range(100):
            probe = LiveInstance(state)
            if probe.acquire():
                probe.close()
                return 0
            time.sleep(.1)
        return 2
    instance = LiveInstance(state)
    if not instance.acquire():
        request_existing(state, "show")
        return 0
    from silencio.graph import register_hotkey, unregister_hotkey
    hotkey = None
    try:
        state.with_suffix(".command.json").unlink(missing_ok=True)
        preferences = Preferences.load(state.with_suffix(".preferences.json"))
        if args.profile:
            preferences.profile = args.profile
            preferences.save(state.with_suffix(".preferences.json"))
        if not args.no_startup and getattr(sys, "frozen", False):
            set_login_start(preferences.start_with_windows)
        guardian = start_guardian(state)
        # Give the helper a chance to acquire a process handle before routing.
        time.sleep(.1)
        if guardian.poll() is not None:
            raise RuntimeError("Audio recovery could not start. Please reinstall Silencio.")
        window = DesktopWindow(state, preferences, background=args.background, first_run=args.first_run)
        hotkey = register_hotkey(lambda: window.runtime.send("toggle"))
        window.root.mainloop()
        if window.runtime.is_alive():
            window.runtime.send("quit")
            window.runtime.join(timeout=10)
        return 0
    except Exception as exc:
        logging.exception("Desktop startup failed")
        import tkinter.messagebox
        tkinter.messagebox.showerror("Silencio couldn't start", f"{exc}\n\nDetails: {data_directory() / 'logs'}")
        return 1
    finally:
        unregister_hotkey(hotkey)
        instance.close()


if __name__ == "__main__":
    raise SystemExit(main())
