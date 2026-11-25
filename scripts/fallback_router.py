"""Smart Capability Router, Route Cache, Circuit Breaker, Gate Detector & Batch Pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import shlex
import subprocess
import time
from typing import Any

from scripts.display_mapper import list_monitors
from scripts.engines import tier1_browser, tier2_uia, tier25_ocr, tier3_vision, tier4_lowlevel
from scripts.overlay_hud import send_hud_event, start_hud_process, stop_hud_process, read_hud_info
from scripts.win32_core import (
    check_uipi_access,
    close_window_safe,
    enable_dpi_awareness,
    find_windows,
    get_desktop_environment,
    get_foreground_window,
    get_process_integrity_level,
    get_window_info,
)

BROWSER_PROCESSES = frozenset({"chrome.exe", "msedge.exe", "brave.exe", "firefox.exe"})
CANVAS_APP_PREFIXES = (
    "capcut",
    "jianying",
    "godot",
    "blender",
    "obs64",
    "unity",
    "unreal",
    "photoshop",
    "premiere",
    "afterfx",
)

GATE_TEXT_MARKERS = (
    "verify you are human",
    "cf-turnstile",
    "g-recaptcha",
    "hcaptcha",
    "are you a robot",
    "complete the security check",
)


def classify_window(win_info: dict[str, Any]) -> str:
    """Classify window in <1ms so the router jumps straight to the optimal tier."""
    cls = str(win_info.get("class_name", ""))
    proc = str(win_info.get("process_name", "")).lower()
    if cls == "#32770":
        return "FILE_DIALOG"
    if proc in BROWSER_PROCESSES:
        return "BROWSER"
    if any(proc.startswith(prefix) for prefix in CANVAS_APP_PREFIXES):
        return "CANVAS_APP"
    return "DESKTOP_APP"


def detect_human_gate(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in GATE_TEXT_MARKERS)


@dataclass
class RouteStats:
    preferred_tier: str | None = None
    uia_failures: int = 0
    calls: int = 0
    avg_ms: float = 0.0


class RouteCache:
    """In-RAM capability cache that auto-promotes Tier 2.5/3 after consecutive UIA misses."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], RouteStats] = {}

    def key(self, win_info: dict[str, Any]) -> tuple[str, str]:
        return (str(win_info.get("process_name", "")).lower(), str(win_info.get("class_name", "")))

    def get(self, win_info: dict[str, Any]) -> RouteStats:
        k = self.key(win_info)
        if k not in self._entries:
            self._entries[k] = RouteStats()
        return self._entries[k]

    def record_uia_miss(self, win_info: dict[str, Any]) -> None:
        st = self.get(win_info)
        st.uia_failures += 1
        if st.uia_failures >= 2:
            st.preferred_tier = "tier25_ocr"

    def record_success(self, win_info: dict[str, Any], tier: str, elapsed_ms: float) -> None:
        st = self.get(win_info)
        st.calls += 1
        st.avg_ms = ((st.avg_ms * (st.calls - 1)) + elapsed_ms) / st.calls
        if tier == "tier2_uia":
            st.uia_failures = 0
        st.preferred_tier = tier


class FallbackRouter:
    """5-Stage Smart Telemetry Router coordinating Tiers 1, 2, 2.5, 3, and 4."""

    def __init__(self) -> None:
        self.cache = RouteCache()

    def close(self) -> None:
        tier25_ocr.get_ocr_worker().close()

    def _hud(self, debug: bool, payload: dict[str, Any]) -> None:
        if debug:
            if not read_hud_info():
                start_hud_process()
            send_hud_event(payload)
        else:
            # Also emit silently if user toggled HUD on via `hud on` or Ctrl+Alt+H
            if read_hud_info():
                send_hud_event(payload)

    def _resolve_target(self, title: str | None) -> dict[str, Any]:
        if title:
            wins = find_windows(title_query=title, visible_only=True)
            if wins:
                return wins[0]
        return get_window_info(get_foreground_window())

    def doctor(self) -> dict[str, Any]:
        t0 = time.perf_counter()
        dpi_mode = enable_dpi_awareness()
        monitors = list_monitors()
        browsers = tier1_browser.discover_browsers()
        cdp = tier1_browser.find_cdp_endpoint()
        uia_ok = tier2_uia.check_uia_available()
        ocr_info = tier25_ocr.get_ocr_worker().get_info()
        rid, integrity = get_process_integrity_level(None)
        return {
            "ok": True,
            "dpi_awareness": dpi_mode,
            "integrity": integrity,
            "integrity_rid": rid,
            "monitors": monitors,
            "browsers_installed": browsers,
            "cdp_active": bool(cdp),
            "cdp_port": cdp["port"] if cdp else None,
            "uia_available": uia_ok,
            "winrt_ocr": ocr_info,
            "desktop_environment": get_desktop_environment(),
            "hud_active": bool(read_hud_info()),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def click(self, args: dict[str, Any], debug: bool = False) -> dict[str, Any]:
        t0 = time.perf_counter()
        button = str(args.get("button", "left"))
        clicks = int(args.get("clicks", 1))
        mode = "human" if args.get("human") else "turbo"
        restore_cursor = not bool(args.get("no_restore_cursor", False))
        monitor = int(args.get("monitor", 0))
        selector = args.get("selector")
        text = args.get("text")
        title = args.get("title")
        x = args.get("x")
        y = args.get("y")

        def hud_cb(ev: dict[str, Any]) -> None:
            self._hud(debug, ev)

        # Direct normalized Vision coordinates -> jump straight to Tier 3
        if x is not None and y is not None:
            return tier3_vision.click_vision(
                float(x),
                float(y),
                monitor_index=monitor,
                button=button,
                clicks=clicks,
                mode=mode,
                restore_cursor=restore_cursor,
                hud_cb=hud_cb,
            )

        win = self._resolve_target(title)
        hwnd = int(win.get("hwnd", 0))
        if hwnd:
            uipi = check_uipi_access(hwnd)
            if not uipi["allowed"]:
                return {
                    "ok": False,
                    "code": "ELEVATION_REQUIRED",
                    "error": f"Window '{win.get('title', '')}' requires '{uipi['target_label']}' integrity.",
                    "uipi": uipi,
                }

        wclass = classify_window(win)
        stats = self.cache.get(win)

        # 1. Browser / selector path -> Tier 1 Raw CDP
        if (wclass == "BROWSER" or selector) and button == "left" and clicks == 1:
            res1 = tier1_browser.click_browser(selector=selector, text=text)
            if res1.get("code") == "HUMAN_HANDOFF_REQUIRED":
                return res1
            if res1.get("ok"):
                self._hud(debug, {"tier": f"TIER 1: RAW CDP | {res1.get('elapsed_ms', 0)}ms"})
                self.cache.record_success(win, "tier1_browser", float(res1.get("elapsed_ms", 0)))
                return res1
            if selector and not text:
                return res1

        if not text:
            return {"ok": False, "code": "MISSING_TARGET", "error": "Provide --text, --selector, or --x/--y."}

        # 2. Tier 2 UIA (skip for CANVAS_APP or auto-promoted windows)
        skip_uia = (wclass == "CANVAS_APP") or (stats.preferred_tier == "tier25_ocr")
        if not skip_uia and button == "left" and clicks == 1:
            res2 = tier2_uia.click_uia(text=text, title=title, timeout_ms=80)
            if res2.get("code") == "ELEVATION_REQUIRED":
                return res2
            if res2.get("ok"):
                self._hud(debug, {"tier": f"TIER 2: WINDOWS UIA | {res2.get('elapsed_ms', 0)}ms"})
                self.cache.record_success(win, "tier2_uia", float(res2.get("elapsed_ms", 0)))
                return res2
            if res2.get("code") == "UIA_NO_PATTERN_HAS_BOUNDS" and res2.get("center_phys"):
                cx, cy = res2["center_phys"]
                res3 = tier3_vision.click_vision_physical(
                    cx, cy, button=button, clicks=clicks, mode=mode, restore_cursor=restore_cursor, target_hwnd=hwnd, hud_cb=hud_cb
                )
                res3["located_by"] = "tier2_uia_bounds"
                return res3
            self.cache.record_uia_miss(win)

        # 3. Tier 2.5 WinRT OCR (~50ms) -> Tier 3 physical click
        ocr_res = tier25_ocr.find_text_on_screen(text, window_title=title, monitor_index=monitor)
        ocr_lines_str = "\n".join(ocr_res.get("lines", []))
        if ocr_lines_str and detect_human_gate(ocr_lines_str):
            return {
                "ok": False,
                "code": "HUMAN_HANDOFF_REQUIRED",
                "tier": "tier25_ocr",
                "error": "Human verification / CAPTCHA challenge detected on screen. Please complete it manually.",
            }
        if not ocr_res.get("ok"):
            if not args.get("no_snapshot_on_fail") and ocr_res.get("code") == "OCR_TEXT_NOT_FOUND":
                snap_res = tier3_vision.snapshot(monitor_index=monitor, window_title=title, grid=True)
                if snap_res.get("ok"):
                    ocr_res["fallback_snapshot_path"] = snap_res["image_path"]
            return ocr_res

        cx, cy = ocr_res["center_phys"]
        click_res = tier3_vision.click_vision_physical(
            cx,
            cy,
            button=button,
            clicks=clicks,
            mode=mode,
            restore_cursor=restore_cursor,
            target_hwnd=hwnd or None,
            hud_cb=hud_cb,
        )
        click_res["located_by"] = "tier25_ocr"
        click_res["ocr_ms"] = ocr_res.get("elapsed_ms", 0)
        click_res["matched_text"] = ocr_res.get("matched_text", text)
        click_res["total_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
        if click_res.get("ok"):
            self._hud(debug, {"tier": f"TIER 2.5 OCR -> T3 | {click_res['total_ms']}ms", "click": [cx, cy]})
            self.cache.record_success(win, "tier25_ocr", click_res["total_ms"])
        return click_res

    def type_text(self, args: dict[str, Any], debug: bool = False) -> dict[str, Any]:
        text = str(args.get("text", ""))
        selector = args.get("selector")
        title = args.get("title")
        human = bool(args.get("human", False))
        no_clipboard = bool(args.get("no_clipboard", False))
        enter = bool(args.get("enter", False))

        win = self._resolve_target(title)
        hwnd = int(win.get("hwnd", 0))
        wclass = classify_window(win)

        if wclass == "FILE_DIALOG":
            res_dlg = tier2_uia.handle_file_dialog_fastpath(hwnd, text=text, submit=enter)
            if res_dlg.get("ok"):
                self._hud(debug, {"tier": f"TIER 2: #32770 FASTPATH | {res_dlg.get('elapsed_ms', 0)}ms"})
                return res_dlg

        if selector and (wclass == "BROWSER" or tier1_browser.find_cdp_endpoint()):
            res1 = tier1_browser.type_browser(selector=selector, text=text, enter=enter)
            if res1.get("ok") or res1.get("code") == "HUMAN_HANDOFF_REQUIRED":
                self._hud(debug, {"tier": f"TIER 1: CDP TYPE | {res1.get('elapsed_ms', 0)}ms"})
                return res1

        if not human and not no_clipboard:
            res_clip = tier4_lowlevel.atomic_clipboard_paste(text, target_hwnd=hwnd, press_enter=enter)
            if res_clip.get("ok") or res_clip.get("code") == "ELEVATION_REQUIRED":
                self._hud(debug, {"tier": "TIER 4: ATOMIC CLIPBOARD"})
                return res_clip

        res_u = tier4_lowlevel.send_unicode_text(text, human=human, target_hwnd=hwnd, press_enter=enter)
        self._hud(debug, {"tier": "TIER 4: UNICODE KEYS"})
        return res_u

    def scroll(self, args: dict[str, Any], debug: bool = False) -> dict[str, Any]:
        dy = int(args.get("dy", -3))
        dx = int(args.get("dx", 0))
        x = args.get("x")
        y = args.get("y")
        monitor = int(args.get("monitor", 0))
        title = args.get("title")

        win = self._resolve_target(title)
        if x is None and y is None and classify_window(win) == "BROWSER":
            res1 = tier1_browser.scroll_browser(dy=dy, dx=dx)
            if res1.get("ok"):
                self._hud(debug, {"tier": "TIER 1: CDP SCROLL"})
                return res1

        from scripts.display_mapper import norm_to_physical

        if x is not None and y is not None:
            px, py = norm_to_physical(float(x), float(y), monitor)
        else:
            l, t, r, b = win["rect"]
            px, py = (l + r) // 2, (t + b) // 2
        tier4_lowlevel.send_mouse_wheel(px, py, dy=dy, dx=dx)
        self._hud(debug, {"tier": "TIER 4: MOUSE WHEEL"})
        return {"ok": True, "tier": "tier4_lowlevel", "phys_xy": [px, py], "dy": dy, "dx": dx}

    def extract(self, args: dict[str, Any], debug: bool = False) -> dict[str, Any]:
        selector = args.get("selector")
        title = args.get("title")
        monitor = int(args.get("monitor", 0))
        force_ocr = bool(args.get("ocr", False))
        image_path = args.get("image")

        if image_path:
            res_ocr = tier25_ocr.get_ocr_worker().recognize_file(str(image_path))
            res_ocr["tier"] = "tier25_ocr"
            if res_ocr.get("lines"):
                res_ocr["text"] = "\n".join(res_ocr["lines"])
            self._hud(debug, {"tier": "TIER 2.5: OCR FILE"})
            return res_ocr

        win = self._resolve_target(title)
        wclass = classify_window(win)
        if not force_ocr and (selector or wclass == "BROWSER"):
            res1 = tier1_browser.extract_browser(selector=selector or "body")
            if res1.get("ok") or res1.get("code") == "HUMAN_HANDOFF_REQUIRED":
                self._hud(debug, {"tier": "TIER 1: CDP EXTRACT"})
                return res1

        if not force_ocr and wclass != "CANVAS_APP":
            res2 = tier2_uia.extract_uia(title=title)
            if res2.get("ok"):
                self._hud(debug, {"tier": "TIER 2: UIA EXTRACT"})
                return res2

        # Fallback to WinRT OCR full capture
        from scripts.display_mapper import get_monitor
        from scripts.win32_core import get_state_dir

        try:
            if title and win.get("hwnd"):
                l, t, r, b = win["rect"]
                img = tier3_vision.capture_region_pil(l, t, max(1, r - l), max(1, b - t))
            else:
                mon = get_monitor(monitor, list_monitors())
                img = tier3_vision.capture_region_pil(mon["left"], mon["top"], mon["width"], mon["height"])
        except tier3_vision.DesktopCaptureUnavailableError as exc:
            return tier3_vision._desktop_capture_error_payload(exc)

        bmp = get_state_dir() / "extract_ocr.bmp"
        img.save(bmp, format="BMP")
        res_ocr = tier25_ocr.get_ocr_worker().recognize_file(bmp)
        res_ocr["tier"] = "tier25_ocr"
        if res_ocr.get("lines"):
            res_ocr["text"] = "\n".join(res_ocr["lines"])
        self._hud(debug, {"tier": "TIER 2.5: OCR EXTRACT"})
        return res_ocr

    def batch(self, args: dict[str, Any], debug: bool = False) -> dict[str, Any]:
        t0 = time.perf_counter()
        steps = args.get("steps") or []
        stop_on_error = not bool(args.get("continue_on_error", False))
        results: list[dict[str, Any]] = []

        for idx, step in enumerate(steps):
            action = str(step.get("action", "")).lower()
            if action in ("click", "double_click", "right_click"):
                step_args = dict(step)
                if action == "double_click":
                    step_args["clicks"] = 2
                elif action == "right_click":
                    step_args["button"] = "right"
                res = self.click(step_args, debug=debug)
            elif action == "type":
                res = self.type_text(step, debug=debug)
            elif action == "hotkey":
                res = tier4_lowlevel.send_hotkey(str(step.get("keys", "")), force=bool(step.get("force", False)))
            elif action == "drag":
                mode = "turbo" if step.get("turbo") else "human"
                res = tier3_vision.drag_vision(
                    float(step["x1"]),
                    float(step["y1"]),
                    float(step["x2"]),
                    float(step["y2"]),
                    monitor_index=int(step.get("monitor", 0)),
                    mode=mode,
                    verify=not bool(step.get("no_verify", False)),
                )
            elif action == "scroll":
                res = self.scroll(step, debug=debug)
            elif action == "sleep":
                ms = float(step.get("ms", 100))
                time.sleep(ms / 1000.0)
                res = {"ok": True, "action": "sleep", "ms": ms}
            elif action == "wait_window":
                title_q = str(step.get("title", ""))
                timeout_ms = int(step.get("timeout_ms", 3000))
                deadline = time.perf_counter() + (timeout_ms / 1000.0)
                matched = []
                while time.perf_counter() < deadline:
                    matched = find_windows(title_query=title_q, visible_only=True)
                    if matched:
                        break
                    time.sleep(0.05)
                res = (
                    {"ok": True, "action": "wait_window", "hwnd": matched[0]["hwnd"], "title": matched[0]["title"]}
                    if matched
                    else {"ok": False, "code": "WAIT_WINDOW_TIMEOUT", "error": f"Window '{title_q}' did not appear."}
                )
            elif action == "wait_text":
                q = str(step.get("text", ""))
                timeout_ms = int(step.get("timeout_ms", 3000))
                deadline = time.perf_counter() + (timeout_ms / 1000.0)
                res = {"ok": False, "code": "WAIT_TEXT_TIMEOUT", "error": f"Text '{q}' did not appear."}
                while time.perf_counter() < deadline:
                    probe = tier25_ocr.find_text_on_screen(
                        q, window_title=step.get("title"), monitor_index=int(step.get("monitor", 0))
                    )
                    if probe.get("ok"):
                        res = {"ok": True, "action": "wait_text", "matched_text": probe.get("matched_text")}
                        break
                    time.sleep(0.08)
            else:
                res = {"ok": False, "code": "UNKNOWN_BATCH_ACTION", "error": f"Unknown action '{action}'"}

            results.append({"step": idx, "action": action, **res})
            if not res.get("ok") and stop_on_error:
                return {
                    "ok": False,
                    "code": res.get("code", "BATCH_STEP_FAILED"),
                    "failed_step": idx,
                    "results": results,
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                }

        return {
            "ok": True,
            "steps_executed": len(results),
            "results": results,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def snapshot(self, args: dict[str, Any], debug: bool = False) -> dict[str, Any]:
        mode = str(args.get("mode", "vision")).lower()
        monitor = int(args.get("monitor", 0))
        window_title = args.get("window")
        grid = not bool(args.get("no_grid", False))
        out_path = args.get("out")

        if mode == "tree":
            res = tier2_uia.snapshot_uia_tree(title=window_title)
            if res.get("ok"):
                self._hud(debug, {"tier": f"TIER 2: UIA TREE ({res.get('count', 0)})"})
            return res

        if mode == "auto":
            win = self._resolve_target(window_title)
            wclass = classify_window(win)
            if wclass in ("DESKTOP_APP", "FILE_DIALOG"):
                tree_res = tier2_uia.snapshot_uia_tree(title=window_title or win.get("title"))
                if tree_res.get("ok") and int(tree_res.get("count", 0)) >= 3:
                    self._hud(debug, {"tier": f"TIER 2: AUTO TREE ({tree_res['count']})"})
                    return tree_res

        res = tier3_vision.snapshot(
            monitor_index=monitor,
            window_title=window_title,
            grid=grid,
            out_path=out_path,
        )
        if res.get("ok"):
            self._hud(debug, {"tier": f"TIER 3: SNAPSHOT | {res.get('elapsed_ms', 0)}ms"})
        return res

    def list_windows_cmd(self, args: dict[str, Any]) -> dict[str, Any]:
        t0 = time.perf_counter()
        wins = find_windows(
            title_query=args.get("title"),
            process_query=args.get("process"),
            visible_only=True,
        )
        enriched: list[dict[str, Any]] = []
        for w in wins:
            if not w.get("title") and not w.get("process_name"):
                continue
            uipi = check_uipi_access(int(w["hwnd"]))
            enriched.append(
                {
                    **w,
                    "category": classify_window(w),
                    "integrity": uipi.get("target_label", "unknown"),
                    "uipi_allowed": bool(uipi.get("allowed", True)),
                }
            )
        return {
            "ok": True,
            "count": len(enriched),
            "windows": enriched,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def launch(self, args: dict[str, Any]) -> dict[str, Any]:
        t0 = time.perf_counter()
        target = str(args.get("target", "")).strip()
        if not target:
            return {"ok": False, "code": "MISSING_TARGET", "error": "Provide --target executable path or name."}
        extra = shlex.split(str(args.get("args", "")), posix=False) if args.get("args") else []
        try:
            proc = subprocess.Popen(
                [target, *extra],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=0x00000200,
            )
        except OSError as exc:
            return {"ok": False, "code": "LAUNCH_FAILED", "error": str(exc)}

        wait_title = args.get("wait_title")
        matched: dict[str, Any] | None = None
        if wait_title:
            timeout_ms = int(args.get("timeout_ms", 4000))
            deadline = time.perf_counter() + (timeout_ms / 1000.0)
            while time.perf_counter() < deadline:
                found = find_windows(title_query=str(wait_title), visible_only=True)
                if found:
                    matched = found[0]
                    break
                time.sleep(0.05)

        return {
            "ok": True,
            "pid": proc.pid,
            "target": target,
            "window": matched,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def focus_cmd(self, args: dict[str, Any]) -> dict[str, Any]:
        hwnd = int(args.get("hwnd") or 0)
        if not hwnd:
            win = self._resolve_target(args.get("title"))
            hwnd = int(win.get("hwnd") or 0)
        if not hwnd:
            return {"ok": False, "code": "WINDOW_NOT_FOUND", "error": "No matching visible window found."}
        res = tier4_lowlevel.ensure_window_focus(hwnd)
        if res.get("ok"):
            res["hwnd"] = hwnd
        return res

    def close_cmd(self, args: dict[str, Any]) -> dict[str, Any]:
        hwnd = int(args.get("hwnd") or 0)
        if not hwnd:
            title = args.get("title")
            if not title:
                return {"ok": False, "code": "MISSING_TARGET", "error": "Provide --title or --hwnd to close."}
            wins = find_windows(title_query=str(title), visible_only=True)
            if not wins:
                return {"ok": False, "code": "WINDOW_NOT_FOUND", "error": f"No window matching '{title}'."}
            hwnd = int(wins[0]["hwnd"])
        return close_window_safe(hwnd)

    def wait_cmd(self, args: dict[str, Any]) -> dict[str, Any]:
        t0 = time.perf_counter()
        window_q = args.get("window")
        text_q = args.get("text")
        monitor = int(args.get("monitor", 0))
        timeout_ms = int(args.get("timeout_ms", 3000))
        if not window_q and not text_q:
            return {"ok": False, "code": "MISSING_TARGET", "error": "Provide --window or --text to wait for."}

        deadline = time.perf_counter() + (timeout_ms / 1000.0)
        while time.perf_counter() < deadline:
            if window_q:
                found = find_windows(title_query=str(window_q), visible_only=True)
                if found and not text_q:
                    return {
                        "ok": True,
                        "window": found[0],
                        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                    }
            if text_q:
                probe = tier25_ocr.find_text_on_screen(
                    str(text_q), window_title=window_q, monitor_index=monitor
                )
                if probe.get("code") == "DESKTOP_CAPTURE_UNAVAILABLE":
                    return probe
                if probe.get("ok"):
                    return {
                        "ok": True,
                        "matched_text": probe.get("matched_text"),
                        "center_phys": probe.get("center_phys"),
                        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                    }
            time.sleep(0.06)

        return {
            "ok": False,
            "code": "WAIT_TIMEOUT",
            "error": f"Timed out after {timeout_ms}ms waiting for target.",
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        }

    def clipboard_cmd(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action", "get")).lower()
        if action == "get":
            has_txt, val = tier4_lowlevel.get_clipboard_text()
            return {"ok": True, "has_text": has_txt, "text": val}
        if action == "set":
            ok = tier4_lowlevel.set_clipboard_text(str(args.get("text", "")))
            return {"ok": ok}
        if action == "clear":
            ok = tier4_lowlevel.set_clipboard_text(None)
            return {"ok": ok}
        return {"ok": False, "code": "INVALID_ACTION", "error": f"Unknown clipboard action '{action}'"}

    def dispatch(self, cmd: str, args: dict[str, Any], debug: bool = False) -> dict[str, Any]:
        if cmd == "doctor":
            return self.doctor()
        if cmd == "snapshot":
            return self.snapshot(args, debug=debug)
        if cmd == "windows":
            return self.list_windows_cmd(args)
        if cmd == "launch":
            return self.launch(args)
        if cmd == "focus":
            return self.focus_cmd(args)
        if cmd == "close":
            return self.close_cmd(args)
        if cmd == "wait":
            return self.wait_cmd(args)
        if cmd == "clipboard":
            return self.clipboard_cmd(args)
        if cmd == "click":
            return self.click(args, debug=debug)
        if cmd == "drag":
            mode = "turbo" if args.get("turbo") else "human"
            return tier3_vision.drag_vision(
                float(args["x1"]),
                float(args["y1"]),
                float(args["x2"]),
                float(args["y2"]),
                monitor_index=int(args.get("monitor", 0)),
                mode=mode,
                verify=not bool(args.get("no_verify", False)),
                hud_cb=(lambda ev: self._hud(debug, ev)),
            )
        if cmd == "type":
            return self.type_text(args, debug=debug)
        if cmd == "hotkey":
            win = self._resolve_target(args.get("title")) if args.get("title") else {"hwnd": 0}
            res = tier4_lowlevel.send_hotkey(
                str(args.get("keys", "")),
                force=bool(args.get("force", False)),
                target_hwnd=int(win.get("hwnd", 0)),
            )
            if res.get("ok"):
                self._hud(debug, {"tier": f"TIER 4: HOTKEY ({args.get('keys', '')})"})
            return res
        if cmd == "scroll":
            return self.scroll(args, debug=debug)
        if cmd == "extract":
            return self.extract(args, debug=debug)
        if cmd == "open_browser":
            return tier1_browser.open_browser(
                url=str(args.get("url", "about:blank")),
                browser=str(args.get("browser", "auto")),
                headless=bool(args.get("headless", False)),
            )
        if cmd == "batch":
            return self.batch(args, debug=debug)
        if cmd == "hud":
            action = str(args.get("action", "status"))
            if action == "on":
                return start_hud_process()
            if action == "off":
                return stop_hud_process()
            if action == "status":
                info = read_hud_info()
                return {"ok": True, "running": bool(info), **(info or {})}
            if action == "demo":
                res = start_hud_process()
                send_hud_event(
                    {
                        "tier": "HUD DEMO: ALL TIERS READY",
                        "points": [[120, 120], [240, 160], [380, 210], [500, 260]],
                        "click": [500, 260],
                    }
                )
                return res
        return {"ok": False, "code": "UNKNOWN_COMMAND", "error": f"Unknown command: '{cmd}'"}
