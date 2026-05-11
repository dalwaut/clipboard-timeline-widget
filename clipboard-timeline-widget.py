#!/usr/bin/env python3
"""Clipboard Timeline Desktop Widget
Lightweight clipboard history manager — shows recent clips with
search, pin favorites, auto-expire old ones. Purely local.
Built by Boutabyte — https://boutabyte.com
"""

import json
import math
import signal
import time
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib

APP_NAME = "Clipboard Timeline"
CONFIG_DIR = Path.home() / ".config" / "clipboard-timeline-widget"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
HISTORY_FILE = CONFIG_DIR / "history.json"
AUTOSTART_DIR = Path.home() / ".config" / "autostart"
AUTOSTART_FILE = AUTOSTART_DIR / "bb-clipboard-timeline.desktop"
WIDGET_SCRIPT = Path(__file__).resolve()

POLL_MS = 800
MAX_HISTORY = 50
ROW_H = 28
MIN_W = 280
MIN_H = 120
TITLE_H = 36
COG_SIZE = 20
RESIZE_MARGIN = 8

# Warm purple/violet palette
C = {
    "bg":         (0.110, 0.090, 0.140),
    "accent":     (0.659, 0.447, 0.851),
    "cream":      (0.878, 0.847, 0.918),
    "label":      (0.447, 0.400, 0.533),
    "dim":        (0.220, 0.200, 0.290),
    "bar_empty":  (0.180, 0.161, 0.240),
    "red":        (1.000, 0.373, 0.333),
    "pin":        (0.910, 0.659, 0.298),
}

CSS_TEMPLATE = """
window {{ background-color: transparent; }}
.settings-window {{ background-color: {bg_hex}; border: 1px solid #ffffff; border-radius: 8px; }}
.settings-window * {{ color: {text_hex}; }}
.settings-window label {{ color: {label_hex}; font-size: 12px; }}
scale trough {{ background-color: {dim_hex}; min-height: 4px; border-radius: 2px; }}
scale highlight {{ background-color: {accent_hex}; min-height: 4px; border-radius: 2px; }}
scale slider {{ background-color: {text_hex}; min-width: 14px; min-height: 14px; border-radius: 7px; }}
button {{ background-color: {dim_hex}; color: {text_hex}; border: 1px solid {dim_hex}; border-radius: 4px; padding: 6px 14px; font-size: 11px; font-weight: bold; }}
button:hover {{ background-color: {accent_hex}; color: {bg_hex}; }}
.close-x {{ background: transparent; border: none; padding: 4px 10px; font-size: 16px; font-weight: bold; color: #ffffff; min-width: 24px; }}
.close-x:hover {{ color: {red_hex}; background: transparent; }}
.quit-btn {{ background-color: transparent; color: {red_hex}; border: 1px solid {red_hex}; }}
.quit-btn:hover {{ background-color: {red_hex}; color: {bg_hex}; }}
*:link, button:link {{ color: {label_hex}; background: transparent; border: none; padding: 0; font-size: 9px; }}
*:link:hover, button:link:hover {{ color: {accent_hex}; background: transparent; }}
switch {{ background-color: {dim_hex}; border-radius: 12px; min-height: 20px; min-width: 40px; }}
switch:checked {{ background-color: {accent_hex}; }}
switch slider {{ background-color: {text_hex}; border-radius: 10px; min-height: 16px; min-width: 16px; }}
"""


def load_settings():
    defaults = {"opacity": 0.90, "x": -1, "y": -1, "w": 340, "h": 320, "font_size": 10}
    if SETTINGS_FILE.exists():
        try:
            defaults.update(json.loads(SETTINGS_FILE.read_text()))
        except Exception:
            pass
    return defaults


def save_settings(settings):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings))


def load_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:
            pass
    return []


def save_history(history):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history[:MAX_HISTORY]))


def rounded_rect(cr, x, y, w, h, r):
    r = min(r, h / 2, w / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def draw_cog(cr, cx, cy, radius, color, alpha=1.0):
    cr.save()
    cr.set_source_rgba(*color, alpha)
    teeth = 6
    outer, inner = radius, radius * 0.55
    th = math.pi / teeth / 2.2
    cr.new_path()
    for i in range(teeth):
        a = 2 * math.pi * i / teeth
        cr.line_to(cx + outer * math.cos(a - th), cy + outer * math.sin(a - th))
        cr.line_to(cx + outer * math.cos(a + th), cy + outer * math.sin(a + th))
        na = 2 * math.pi * (i + 0.5) / teeth
        cr.line_to(cx + inner * math.cos(na - th), cy + inner * math.sin(na - th))
        cr.line_to(cx + inner * math.cos(na + th), cy + inner * math.sin(na + th))
    cr.close_path()
    cr.fill()
    cr.set_source_rgba(*C["bg"], alpha)
    cr.arc(cx, cy, radius * 0.25, 0, 2 * math.pi)
    cr.fill()
    cr.restore()


class SettingsWindow(Gtk.Window):
    def __init__(self, widget_app):
        super().__init__(title=f"{APP_NAME} Settings")
        self.app = widget_app
        self.set_default_size(300, 380)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        wx, wy = widget_app.get_position()
        self.move(wx + widget_app.widget_w // 2 - 150, wy + 30)
        self.get_style_context().add_class("settings-window")
        self.connect("delete-event", self.on_close)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_start(16)
        vbox.set_margin_end(16)
        vbox.set_margin_top(10)
        vbox.set_margin_bottom(14)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        title = Gtk.Label()
        title.set_markup('<span font_desc="12" weight="bold">Settings</span>')
        title.set_halign(Gtk.Align.START)
        header.pack_start(title, True, True, 0)
        close_btn = Gtk.Button(label="✕")
        close_btn.get_style_context().add_class("close-x")
        close_btn.connect("clicked", lambda _: self.on_close(None, None))
        header.pack_end(close_btn, False, False, 0)
        vbox.pack_start(header, False, False, 0)
        vbox.pack_start(Gtk.Separator(), False, False, 0)

        lbl = Gtk.Label(label="Opacity")
        lbl.set_halign(Gtk.Align.START)
        vbox.pack_start(lbl, False, False, 0)
        self.opacity_slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.2, 1.0, 0.05)
        self.opacity_slider.set_value(self.app.alpha)
        self.opacity_slider.set_draw_value(True)
        self.opacity_slider.set_value_pos(Gtk.PositionType.RIGHT)
        self.opacity_slider.connect("value-changed", self.on_opacity)
        vbox.pack_start(self.opacity_slider, False, False, 0)

        ts_lbl = Gtk.Label(label="Text Size")
        ts_lbl.set_halign(Gtk.Align.START)
        vbox.pack_start(ts_lbl, False, False, 0)
        self.text_size_slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 7, 16, 1)
        self.text_size_slider.set_value(self.app.font_size)
        self.text_size_slider.set_draw_value(True)
        self.text_size_slider.set_digits(0)
        self.text_size_slider.set_value_pos(Gtk.PositionType.RIGHT)
        self.text_size_slider.connect("value-changed", self.on_text_size)
        vbox.pack_start(self.text_size_slider, False, False, 0)

        auto_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        auto_lbl = Gtk.Label(label="Auto Start")
        auto_lbl.set_halign(Gtk.Align.START)
        auto_box.pack_start(auto_lbl, True, True, 0)
        self.auto_switch = Gtk.Switch()
        self.auto_switch.set_active(AUTOSTART_FILE.exists())
        self.auto_switch.connect("state-set", self.on_autostart)
        auto_box.pack_end(self.auto_switch, False, False, 0)
        vbox.pack_start(auto_box, False, False, 0)

        clear_btn = Gtk.Button(label="Clear History")
        clear_btn.connect("clicked", self.on_clear)
        vbox.pack_start(clear_btn, False, False, 2)

        attr = Gtk.LinkButton.new_with_label("https://boutabyte.com", "Built by Boutabyte")
        attr.set_halign(Gtk.Align.CENTER)
        vbox.pack_start(attr, False, False, 6)

        quit_btn = Gtk.Button(label="Quit Widget")
        quit_btn.get_style_context().add_class("quit-btn")
        quit_btn.connect("clicked", lambda _: Gtk.main_quit())
        vbox.pack_start(quit_btn, False, False, 2)

        self.add(vbox)
        self.show_all()

    def on_close(self, *args):
        self.hide()
        self.app.settings_win = None
        return True

    def on_opacity(self, scale):
        self.app.alpha = round(scale.get_value(), 2)
        self.app.settings["opacity"] = self.app.alpha
        save_settings(self.app.settings)
        self.app.canvas.queue_draw()

    def on_text_size(self, scale):
        self.app.font_size = int(scale.get_value())
        self.app.settings["font_size"] = self.app.font_size
        save_settings(self.app.settings)
        self.app.canvas.queue_draw()

    def on_autostart(self, switch, state):
        if state:
            AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
            AUTOSTART_FILE.write_text(
                f"[Desktop Entry]\nType=Application\n"
                f"Name=BB Widget: Clipboard Timeline\nComment=Clipboard history\n"
                f"Exec=python3 {WIDGET_SCRIPT}\nHidden=false\nNoDisplay=false\n"
                f"X-GNOME-Autostart-enabled=true\nX-GNOME-Autostart-Delay=5\n"
            )
        else:
            if AUTOSTART_FILE.exists():
                AUTOSTART_FILE.unlink()
        return False

    def on_clear(self, btn):
        self.app.history = [h for h in self.app.history if h.get("pinned")]
        save_history(self.app.history)
        self.app.scroll_offset = 0
        self.app.canvas.queue_draw()


class ClipboardTimelineWidget(Gtk.Window):
    def __init__(self):
        super().__init__(title=APP_NAME)
        self.settings = load_settings()
        self.alpha = self.settings["opacity"]
        self.font_size = self.settings.get("font_size", 10)
        self.history = load_history()
        self.last_clip = ""
        self.drag_offset = None
        self.resize_edge = None
        self.cog_hover = False
        self.hover_row = -1
        self.scroll_offset = 0
        self.settings_win = None
        self.widget_w = self.settings.get("w", 340)
        self.widget_h = self.settings.get("h", 320)

        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_below(True)
        self.stick()
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        if self.settings["x"] >= 0 and self.settings["y"] >= 0:
            self.move(self.settings["x"], self.settings["y"])
        else:
            display = Gdk.Display.get_default()
            mon = display.get_primary_monitor() or display.get_monitor(0)
            geom = mon.get_geometry()
            self.move(geom.x + geom.width - 380, geom.y + 60)

        self.canvas = Gtk.DrawingArea()
        self.canvas.set_size_request(self.widget_w, self.widget_h)
        self.canvas.connect("draw", self.on_draw)
        self.canvas.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.SCROLL_MASK
        )
        self.canvas.connect("button-press-event", self.on_press)
        self.canvas.connect("button-release-event", self.on_release)
        self.canvas.connect("motion-notify-event", self.on_motion)
        self.canvas.connect("scroll-event", self.on_scroll)
        self.add(self.canvas)

        css = Gtk.CssProvider()
        css.load_from_data(CSS_TEMPLATE.format(
            bg_hex="#1c1724", text_hex="#e0d8ea", label_hex="#726688",
            dim_hex="#38334a", accent_hex="#a872d9", red_hex="#ff5f55",
        ).encode())
        Gtk.StyleContext.add_provider_for_screen(screen, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        text = self.clipboard.wait_for_text()
        if text:
            self.last_clip = text

        GLib.timeout_add(POLL_MS, self.check_clipboard)
        self.show_all()

    def _max_visible(self):
        # Rows start at TITLE_H + 14, need ~6px bottom margin
        usable = self.widget_h - TITLE_H - 14 - 6
        return max(1, usable // ROW_H)

    def _cog_rect(self):
        return (self.widget_w - 14 - COG_SIZE, 8, COG_SIZE, COG_SIZE)

    def _in_cog(self, x, y):
        cx, cy, cw, ch = self._cog_rect()
        return cx <= x <= cx + cw and cy <= y <= cy + ch

    def _row_y_start(self):
        return TITLE_H + 14

    def _pin_btn_rect(self, i):
        return (14, self._row_y_start() + i * ROW_H + 5, 14, 14)

    def _row_rect(self, i):
        return (14, self._row_y_start() + i * ROW_H, self.widget_w - 28, ROW_H)

    def _resize_edge_at(self, x, y):
        w, h = self.widget_w, self.widget_h
        m = RESIZE_MARGIN
        left, right = x <= m, x >= w - m
        top, bottom = y <= m, y >= h - m
        if right and bottom: return "se"
        if left and bottom: return "sw"
        if right and top: return "ne"
        if left and top: return "nw"
        if right: return "e"
        if left: return "w"
        if bottom: return "s"
        if top and y > 0: return "n"
        return None

    def _visible_items(self):
        pinned = [h for h in self.history if h.get("pinned")]
        unpinned = [h for h in self.history if not h.get("pinned")]
        ordered = pinned + unpinned
        mv = self._max_visible()
        return ordered[self.scroll_offset:self.scroll_offset + mv]

    def check_clipboard(self):
        text = self.clipboard.wait_for_text()
        if text and text != self.last_clip and text.strip():
            self.last_clip = text
            self.history = [h for h in self.history if h["text"] != text]
            self.history.insert(0, {"text": text, "time": time.time(), "pinned": False})
            pinned = [h for h in self.history if h.get("pinned")]
            unpinned = [h for h in self.history if not h.get("pinned")]
            self.history = pinned + unpinned[:MAX_HISTORY - len(pinned)]
            save_history(self.history)
            self.canvas.queue_draw()
        return True

    def on_press(self, widget, event):
        if event.button == 1:
            edge = self._resize_edge_at(event.x, event.y)
            if edge:
                self.resize_edge = edge
                wx, wy = self.get_position()
                self.drag_offset = (event.x_root, event.y_root, self.widget_w, self.widget_h, wx, wy)
                return True
            if self._in_cog(event.x, event.y):
                if not self.settings_win:
                    self.settings_win = SettingsWindow(self)
                else:
                    self.settings_win.present()
                return True
            visible = self._visible_items()
            for i, item in enumerate(visible):
                px, py, pw, ph = self._pin_btn_rect(i)
                if px <= event.x <= px + pw and py <= event.y <= py + ph:
                    idx = self.history.index(item)
                    self.history[idx]["pinned"] = not self.history[idx].get("pinned", False)
                    save_history(self.history)
                    self.canvas.queue_draw()
                    return True
                rx, ry, rw, rh = self._row_rect(i)
                if rx <= event.x <= rx + rw and ry <= event.y <= ry + rh:
                    self.clipboard.set_text(item["text"], -1)
                    self.clipboard.store()
                    self.last_clip = item["text"]
                    self.canvas.queue_draw()
                    return True
            if event.y <= TITLE_H:
                self.drag_offset = (event.x_root, event.y_root, *self.get_position(), 0, 0)
                self.resize_edge = None
        return True

    def on_release(self, widget, event):
        if self.resize_edge:
            x, y = self.get_position()
            self.settings.update({"w": self.widget_w, "h": self.widget_h, "x": x, "y": y})
            save_settings(self.settings)
            self.resize_edge = None
            self.drag_offset = None
        elif self.drag_offset:
            self.drag_offset = None
            x, y = self.get_position()
            self.settings["x"] = x
            self.settings["y"] = y
            save_settings(self.settings)
        return True

    def on_motion(self, widget, event):
        if self.resize_edge and self.drag_offset:
            ox, oy, ow, oh, owx, owy = self.drag_offset
            dx, dy = event.x_root - ox, event.y_root - oy
            nw, nh, nx, ny = ow, oh, owx, owy
            e = self.resize_edge
            if "e" in e: nw = max(MIN_W, int(ow + dx))
            if "w" in e: nw = max(MIN_W, int(ow - dx)); nx = owx + (ow - nw)
            if "s" in e: nh = max(MIN_H, int(oh + dy))
            if "n" in e: nh = max(MIN_H, int(oh - dy)); ny = owy + (oh - nh)
            self.widget_w, self.widget_h = nw, nh
            self.canvas.set_size_request(nw, nh)
            self.resize(nw, nh)
            self.move(nx, ny)
            self.canvas.queue_draw()
        elif self.drag_offset and not self.resize_edge:
            ox, oy, wx, wy = self.drag_offset[:4]
            self.move(int(wx + event.x_root - ox), int(wy + event.y_root - oy))
        else:
            was_cog = self.cog_hover
            self.cog_hover = self._in_cog(event.x, event.y)
            old_row = self.hover_row
            self.hover_row = -1
            for i in range(len(self._visible_items())):
                rx, ry, rw, rh = self._row_rect(i)
                if rx <= event.x <= rx + rw and ry <= event.y <= ry + rh:
                    self.hover_row = i
                    break
            edge = self._resize_edge_at(event.x, event.y)
            win = self.get_window()
            if win:
                cmap = {"se":"se-resize","sw":"sw-resize","ne":"ne-resize","nw":"nw-resize",
                        "e":"e-resize","w":"w-resize","s":"s-resize","n":"n-resize"}
                win.set_cursor(Gdk.Cursor.new_from_name(self.get_display(), cmap[edge]) if edge in cmap else None)
            if was_cog != self.cog_hover or old_row != self.hover_row:
                self.canvas.queue_draw()
        return True

    def on_scroll(self, widget, event):
        total = len(self.history)
        mv = self._max_visible()
        if event.direction == Gdk.ScrollDirection.DOWN:
            self.scroll_offset = min(self.scroll_offset + 1, max(0, total - mv))
        elif event.direction == Gdk.ScrollDirection.UP:
            self.scroll_offset = max(0, self.scroll_offset - 1)
        self.canvas.queue_draw()
        return True

    def on_draw(self, widget, cr):
        a = self.alpha
        fs = self.font_size
        w = self.widget_w
        h = self.widget_h

        cr.set_operator(0); cr.paint(); cr.set_operator(2)
        rounded_rect(cr, 0, 0, w, h, 10)
        cr.set_source_rgba(*C["bg"], a); cr.fill()
        rounded_rect(cr, 0.5, 0.5, w - 1, h - 1, 10)
        cr.set_source_rgba(*C["dim"], a * 0.5); cr.set_line_width(1); cr.stroke()

        pad = 14
        y = 18

        cr.select_font_face("JetBrains Mono", 0, 1)
        cr.set_font_size(fs + 3)
        cr.set_source_rgba(*C["accent"], a)
        cr.move_to(pad, y); cr.show_text("clipboard")
        tx = cr.get_current_point()[0]
        cr.select_font_face("JetBrains Mono", 0, 0)
        cr.set_source_rgba(*C["cream"], a)
        cr.move_to(tx, y); cr.show_text(" timeline")

        cr.set_font_size(fs - 1)
        cs = f"{len(self.history)} clips"
        ext = cr.text_extents(cs)
        cr.set_source_rgba(*C["label"], a)
        cr.move_to(w - pad - COG_SIZE - 8 - ext.width, y); cr.show_text(cs)

        cog_color = C["accent"] if self.cog_hover else C["label"]
        draw_cog(cr, w - pad - COG_SIZE / 2, y - 4, 8, cog_color, a)

        y += 8
        cr.set_source_rgba(*C["dim"], a * 0.6); cr.set_line_width(0.5)
        cr.move_to(pad, y); cr.line_to(w - pad, y); cr.stroke()

        if not self.history:
            cr.set_font_size(fs); cr.set_source_rgba(*C["label"], a)
            cr.move_to(pad, y + 24); cr.show_text("Clipboard history will appear here")
            # Resize grip
            for dx in range(3):
                for dy in range(3 - dx):
                    cr.set_source_rgba(*C["label"], a * 0.3)
                    cr.arc(w - 8 + dx * 3, h - 8 + dy * 3, 1, 0, 2 * math.pi); cr.fill()
            return

        visible = self._visible_items()
        for i, item in enumerate(visible):
            row_y = self._row_y_start() + i * ROW_H
            if row_y + ROW_H > h - 10:
                break
            is_hover = (self.hover_row == i)
            is_pinned = item.get("pinned", False)

            if is_hover:
                rounded_rect(cr, pad - 4, row_y, w - pad * 2 + 8, ROW_H - 2, 4)
                cr.set_source_rgba(*C["accent"], a * 0.08); cr.fill()

            cr.set_font_size(fs)
            cr.set_source_rgba(*C["pin"] if is_pinned else (*C["dim"][:3],), a * (1.0 if is_pinned else 0.6))
            cr.move_to(pad, row_y + 16); cr.show_text("●" if is_pinned else "○")

            text = item["text"].replace("\n", " ").replace("\t", " ").strip()
            max_chars = max(10, (w - 80) // 7)
            if len(text) > max_chars:
                text = text[:max_chars - 1] + "…"
            cr.select_font_face("JetBrains Mono", 0, 0)
            cr.set_font_size(fs); cr.set_source_rgba(*C["cream"], a)
            cr.move_to(pad + 18, row_y + 16); cr.show_text(text)

            elapsed = time.time() - item.get("time", 0)
            if elapsed < 60: ago = "now"
            elif elapsed < 3600: ago = f"{int(elapsed/60)}m"
            elif elapsed < 86400: ago = f"{int(elapsed/3600)}h"
            else: ago = f"{int(elapsed/86400)}d"
            cr.set_font_size(fs - 2); cr.set_source_rgba(*C["label"], a * 0.7)
            ext = cr.text_extents(ago)
            cr.move_to(w - pad - ext.width, row_y + 15); cr.show_text(ago)

        # Resize grip
        for dx in range(3):
            for dy in range(3 - dx):
                cr.set_source_rgba(*C["label"], a * 0.3)
                cr.arc(w - 8 + dx * 3, h - 8 + dy * 3, 1, 0, 2 * math.pi); cr.fill()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())
    w = ClipboardTimelineWidget()
    w.connect("destroy", Gtk.main_quit)
    Gtk.main()
