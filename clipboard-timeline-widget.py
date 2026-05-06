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

POLL_MS = 800  # check clipboard every 800ms
MAX_HISTORY = 50
MAX_VISIBLE = 10
ROW_H = 28
WIDGET_W = 340
TITLE_H = 36
COG_SIZE = 20

# Warm purple/violet palette
C = {
    "bg":         (0.110, 0.090, 0.140),   # #1c1724
    "accent":     (0.659, 0.447, 0.851),   # #a872d9
    "cream":      (0.878, 0.847, 0.918),   # #e0d8ea
    "label":      (0.447, 0.400, 0.533),   # #726688
    "dim":        (0.220, 0.200, 0.290),   # #38334a
    "bar_empty":  (0.180, 0.161, 0.240),   # #2e293d
    "amber":      (0.910, 0.733, 0.298),   # #e8bb4c
    "red":        (1.000, 0.373, 0.333),   # #ff5f55
    "green":      (0.400, 0.780, 0.467),   # #66c777
    "pin":        (0.910, 0.659, 0.298),   # #e8a84c
}


def load_settings():
    defaults = {"opacity": 0.90, "x": -1, "y": -1}
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
    outer = radius
    inner = radius * 0.55
    tooth_half = math.pi / teeth / 2.2
    cr.new_path()
    for i in range(teeth):
        angle = 2 * math.pi * i / teeth
        cr.line_to(cx + outer * math.cos(angle - tooth_half),
                   cy + outer * math.sin(angle - tooth_half))
        cr.line_to(cx + outer * math.cos(angle + tooth_half),
                   cy + outer * math.sin(angle + tooth_half))
        na = 2 * math.pi * (i + 0.5) / teeth
        cr.line_to(cx + inner * math.cos(na - tooth_half),
                   cy + inner * math.sin(na - tooth_half))
        cr.line_to(cx + inner * math.cos(na + tooth_half),
                   cy + inner * math.sin(na + tooth_half))
    cr.close_path()
    cr.fill()
    cr.set_source_rgba(*C["bg"], alpha)
    cr.arc(cx, cy, radius * 0.25, 0, 2 * math.pi)
    cr.fill()
    cr.restore()


class ClipboardTimelineWidget(Gtk.Window):
    def __init__(self):
        super().__init__(title=APP_NAME)
        self.settings = load_settings()
        self.alpha = self.settings["opacity"]
        self.history = load_history()  # [{text, time, pinned}]
        self.last_clip = ""
        self.drag_offset = None
        self.cog_hover = False
        self.hover_row = -1
        self.scroll_offset = 0
        self.content_h = 200

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

        overlay = Gtk.Overlay()
        self.add(overlay)

        self.canvas = Gtk.DrawingArea()
        self.canvas.set_size_request(WIDGET_W, 200)
        self.canvas.connect("draw", self.on_draw)
        self.canvas.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK |
            Gdk.EventMask.SCROLL_MASK
        )
        self.canvas.connect("button-press-event", self.on_press)
        self.canvas.connect("button-release-event", self.on_release)
        self.canvas.connect("motion-notify-event", self.on_motion)
        self.canvas.connect("scroll-event", self.on_scroll)
        overlay.add(self.canvas)

        self.cog_anchor = Gtk.Label()
        self.cog_anchor.set_halign(Gtk.Align.END)
        self.cog_anchor.set_valign(Gtk.Align.START)
        self.cog_anchor.set_margin_end(10)
        self.cog_anchor.set_margin_top(10)
        self.cog_anchor.set_size_request(1, 1)
        overlay.add_overlay(self.cog_anchor)

        self._build_popover(screen)

        # Get clipboard
        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        # Seed last_clip
        text = self.clipboard.wait_for_text()
        if text:
            self.last_clip = text

        GLib.timeout_add(POLL_MS, self.check_clipboard)
        self.show_all()

    def _build_popover(self, screen):
        self.popover = Gtk.Popover()
        self.popover.set_relative_to(self.cog_anchor)
        self.popover.set_position(Gtk.PositionType.BOTTOM)
        self.popover.connect("closed", lambda _: setattr(self, '_pop_open', False))
        self._pop_open = False

        pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        pop_box.set_margin_start(12)
        pop_box.set_margin_end(12)
        pop_box.set_margin_top(10)
        pop_box.set_margin_bottom(10)

        lbl = Gtk.Label(label="Opacity")
        lbl.set_halign(Gtk.Align.START)
        pop_box.pack_start(lbl, False, False, 0)

        self.opacity_slider = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.2, 1.0, 0.05
        )
        self.opacity_slider.set_value(self.alpha)
        self.opacity_slider.set_size_request(160, -1)
        self.opacity_slider.set_draw_value(True)
        self.opacity_slider.set_value_pos(Gtk.PositionType.RIGHT)
        self.opacity_slider.connect("value-changed", self.on_opacity_changed)
        pop_box.pack_start(self.opacity_slider, False, False, 0)

        auto_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        auto_lbl = Gtk.Label(label="Auto Start")
        auto_lbl.set_halign(Gtk.Align.START)
        auto_box.pack_start(auto_lbl, True, True, 0)
        self.auto_switch = Gtk.Switch()
        self.auto_switch.set_active(AUTOSTART_FILE.exists())
        self.auto_switch.connect("state-set", self.on_autostart_toggled)
        auto_box.pack_end(self.auto_switch, False, False, 0)
        pop_box.pack_start(auto_box, False, False, 0)

        clear_btn = Gtk.Button(label="Clear History")
        clear_btn.connect("clicked", self.on_clear_history)
        pop_box.pack_start(clear_btn, False, False, 2)

        attr_btn = Gtk.LinkButton.new_with_label(
            "https://boutabyte.com", "Built by Boutabyte"
        )
        attr_btn.set_halign(Gtk.Align.CENTER)
        pop_box.pack_start(attr_btn, False, False, 4)

        quit_btn = Gtk.Button(label="Quit Widget")
        quit_btn.connect("clicked", lambda _: Gtk.main_quit())
        pop_box.pack_start(quit_btn, False, False, 4)

        self.popover.add(pop_box)
        self.popover.show_all()
        self.popover.hide()

        css = Gtk.CssProvider()
        css.load_from_data(b"""
            window { background-color: transparent; }
            popover, popover * { background-color: #1c1724; color: #e0d8ea; }
            popover label { color: #726688; }
            scale trough { background-color: #2e293d; min-height: 4px; border-radius: 2px; }
            scale highlight { background-color: #a872d9; min-height: 4px; border-radius: 2px; }
            scale slider { background-color: #e0d8ea; min-width: 14px; min-height: 14px; border-radius: 7px; }
            button { background-color: #38334a; color: #e0d8ea; border: 1px solid #38334a; border-radius: 4px; padding: 4px 12px; }
            button:hover { background-color: #a872d9; color: #1c1724; }
            *:link, button:link { color: #726688; background: transparent; border: none; padding: 0; font-size: 9px; }
            *:link:hover, button:link:hover { color: #a872d9; background: transparent; }
            switch { background-color: #38334a; border-radius: 12px; min-height: 20px; min-width: 40px; }
            switch:checked { background-color: #a872d9; }
            switch slider { background-color: #e0d8ea; border-radius: 10px; min-height: 16px; min-width: 16px; }
        """)
        Gtk.StyleContext.add_provider_for_screen(
            screen, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _cog_rect(self):
        return (WIDGET_W - 14 - COG_SIZE, 8, COG_SIZE, COG_SIZE)

    def _in_cog(self, x, y):
        cx, cy, cw, ch = self._cog_rect()
        return cx <= x <= cx + cw and cy <= y <= cy + ch

    def _row_y_start(self):
        return TITLE_H + 14

    def _pin_btn_rect(self, row_index):
        y_start = self._row_y_start() + row_index * ROW_H
        return (14, y_start + 5, 14, 14)

    def _row_rect(self, row_index):
        y_start = self._row_y_start() + row_index * ROW_H
        return (14, y_start, WIDGET_W - 28, ROW_H)

    # ── Clipboard ──
    def check_clipboard(self):
        text = self.clipboard.wait_for_text()
        if text and text != self.last_clip and text.strip():
            self.last_clip = text
            # Remove duplicates
            self.history = [h for h in self.history if h["text"] != text]
            # Add to front
            self.history.insert(0, {
                "text": text,
                "time": time.time(),
                "pinned": False,
            })
            # Trim (keep pinned)
            pinned = [h for h in self.history if h.get("pinned")]
            unpinned = [h for h in self.history if not h.get("pinned")]
            self.history = pinned + unpinned[:MAX_HISTORY - len(pinned)]
            save_history(self.history)
            self.canvas.queue_draw()
        return True  # keep timer

    # ── Input ──
    def on_press(self, widget, event):
        if event.button == 1:
            if self._in_cog(event.x, event.y):
                self._pop_open = not self._pop_open
                if self._pop_open:
                    self.popover.popup()
                else:
                    self.popover.popdown()
                return True

            # Check pin buttons and row clicks
            visible = self._visible_items()
            for i, item in enumerate(visible):
                px, py, pw, ph = self._pin_btn_rect(i)
                if px <= event.x <= px + pw and py <= event.y <= py + ph:
                    # Toggle pin
                    idx = self.history.index(item)
                    self.history[idx]["pinned"] = not self.history[idx].get("pinned", False)
                    save_history(self.history)
                    self.canvas.queue_draw()
                    return True

                rx, ry, rw, rh = self._row_rect(i)
                if rx <= event.x <= rx + rw and ry <= event.y <= ry + rh:
                    # Copy to clipboard
                    self.clipboard.set_text(item["text"], -1)
                    self.clipboard.store()
                    self.last_clip = item["text"]
                    self.canvas.queue_draw()
                    return True

            if event.y <= TITLE_H:
                self.drag_offset = (event.x_root, event.y_root,
                                    *self.get_position())
        return True

    def on_release(self, widget, event):
        if self.drag_offset:
            self.drag_offset = None
            x, y = self.get_position()
            self.settings["x"] = x
            self.settings["y"] = y
            save_settings(self.settings)
        return True

    def on_motion(self, widget, event):
        if self.drag_offset:
            ox, oy, wx, wy = self.drag_offset
            self.move(int(wx + event.x_root - ox),
                      int(wy + event.y_root - oy))
        else:
            was_cog = self.cog_hover
            self.cog_hover = self._in_cog(event.x, event.y)

            old_row = self.hover_row
            self.hover_row = -1
            visible = self._visible_items()
            for i in range(len(visible)):
                rx, ry, rw, rh = self._row_rect(i)
                if rx <= event.x <= rx + rw and ry <= event.y <= ry + rh:
                    self.hover_row = i
                    break

            if was_cog != self.cog_hover or old_row != self.hover_row:
                self.canvas.queue_draw()
        return True

    def on_scroll(self, widget, event):
        if event.direction == Gdk.ScrollDirection.DOWN:
            max_off = max(0, len(self.history) - MAX_VISIBLE)
            self.scroll_offset = min(self.scroll_offset + 1, max_off)
        elif event.direction == Gdk.ScrollDirection.UP:
            self.scroll_offset = max(0, self.scroll_offset - 1)
        self.canvas.queue_draw()
        return True

    def _visible_items(self):
        # Pinned first, then by time
        pinned = [h for h in self.history if h.get("pinned")]
        unpinned = [h for h in self.history if not h.get("pinned")]
        ordered = pinned + unpinned
        return ordered[self.scroll_offset:self.scroll_offset + MAX_VISIBLE]

    # ── Settings ──
    def on_opacity_changed(self, scale):
        self.alpha = round(scale.get_value(), 2)
        self.settings["opacity"] = self.alpha
        save_settings(self.settings)
        self.canvas.queue_draw()

    def on_autostart_toggled(self, switch, state):
        if state:
            AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
            AUTOSTART_FILE.write_text(
                f"[Desktop Entry]\nType=Application\n"
                f"Name=BB Widget: Clipboard Timeline\n"
                f"Comment=Clipboard history manager\n"
                f"Exec=python3 {WIDGET_SCRIPT}\n"
                f"Hidden=false\nNoDisplay=false\n"
                f"X-GNOME-Autostart-enabled=true\n"
                f"X-GNOME-Autostart-Delay=5\n"
            )
        else:
            if AUTOSTART_FILE.exists():
                AUTOSTART_FILE.unlink()
        return False

    def on_clear_history(self, btn):
        self.history = [h for h in self.history if h.get("pinned")]
        save_history(self.history)
        self.scroll_offset = 0
        self.canvas.queue_draw()

    # ── Drawing ──
    def on_draw(self, widget, cr):
        a = self.alpha
        alloc = widget.get_allocation()
        w = alloc.width

        visible = self._visible_items()
        vis_count = len(visible)
        needed_h = TITLE_H + 14 + max(vis_count, 1) * ROW_H + 16
        if not self.history:
            needed_h = TITLE_H + 60

        cr.set_operator(0)
        cr.paint()
        cr.set_operator(2)

        rounded_rect(cr, 0, 0, w, needed_h, 10)
        cr.set_source_rgba(*C["bg"], a)
        cr.fill()

        rounded_rect(cr, 0.5, 0.5, w - 1, needed_h - 1, 10)
        cr.set_source_rgba(*C["dim"], a * 0.5)
        cr.set_line_width(1)
        cr.stroke()

        pad = 14
        y = 18

        # Title
        cr.select_font_face("JetBrains Mono", 0, 1)
        cr.set_font_size(13)
        cr.set_source_rgba(*C["accent"], a)
        cr.move_to(pad, y)
        cr.show_text("clipboard")
        tx = cr.get_current_point()[0]
        cr.select_font_face("JetBrains Mono", 0, 0)
        cr.set_source_rgba(*C["cream"], a)
        cr.move_to(tx, y)
        cr.show_text(" timeline")

        # Count
        cr.set_font_size(9)
        count_str = f"{len(self.history)} clips"
        ext = cr.text_extents(count_str)
        cr.set_source_rgba(*C["label"], a)
        cr.move_to(w - pad - COG_SIZE - 8 - ext.width, y)
        cr.show_text(count_str)

        # Cog
        cog_cx = WIDGET_W - pad - COG_SIZE / 2
        cog_cy = y - 4
        cog_color = C["accent"] if self.cog_hover else C["label"]
        draw_cog(cr, cog_cx, cog_cy, 8, cog_color, a)

        # Divider
        y += 8
        cr.set_source_rgba(*C["dim"], a * 0.6)
        cr.set_line_width(0.5)
        cr.move_to(pad, y)
        cr.line_to(w - pad, y)
        cr.stroke()

        if not self.history:
            cr.select_font_face("JetBrains Mono", 0, 0)
            cr.set_font_size(10)
            cr.set_source_rgba(*C["label"], a)
            cr.move_to(pad, y + 24)
            cr.show_text("Clipboard history will appear here")
            self.canvas.set_size_request(WIDGET_W, needed_h)
            return

        # Rows
        for i, item in enumerate(visible):
            row_y = self._row_y_start() + i * ROW_H
            is_hover = (self.hover_row == i)
            is_pinned = item.get("pinned", False)

            # Hover highlight
            if is_hover:
                rounded_rect(cr, pad - 4, row_y, w - pad * 2 + 8, ROW_H - 2, 4)
                cr.set_source_rgba(*C["accent"], a * 0.08)
                cr.fill()

            # Pin indicator
            cr.set_font_size(10)
            if is_pinned:
                cr.set_source_rgba(*C["pin"], a)
            else:
                cr.set_source_rgba(*C["dim"], a * 0.6)
            cr.move_to(pad, row_y + 16)
            cr.show_text("●" if is_pinned else "○")

            # Clip text (truncated)
            text = item["text"].replace("\n", " ").replace("\t", " ").strip()
            max_chars = 34
            if len(text) > max_chars:
                text = text[:max_chars - 1] + "…"

            cr.select_font_face("JetBrains Mono", 0, 0)
            cr.set_font_size(10)
            cr.set_source_rgba(*C["cream"], a)
            cr.move_to(pad + 18, row_y + 16)
            cr.show_text(text)

            # Time ago
            elapsed = time.time() - item.get("time", 0)
            if elapsed < 60:
                ago = "now"
            elif elapsed < 3600:
                ago = f"{int(elapsed/60)}m"
            elif elapsed < 86400:
                ago = f"{int(elapsed/3600)}h"
            else:
                ago = f"{int(elapsed/86400)}d"

            cr.set_font_size(8)
            cr.set_source_rgba(*C["label"], a * 0.7)
            ext = cr.text_extents(ago)
            cr.move_to(w - pad - ext.width, row_y + 15)
            cr.show_text(ago)

        # Scroll indicator
        total = len(self.history)
        if total > MAX_VISIBLE:
            bar_h = max(20, int(needed_h * 0.4 * MAX_VISIBLE / total))
            track_h = needed_h - TITLE_H - 30
            bar_y = TITLE_H + 10 + int((track_h - bar_h) * self.scroll_offset / max(1, total - MAX_VISIBLE))
            rounded_rect(cr, w - 6, bar_y, 3, bar_h, 1.5)
            cr.set_source_rgba(*C["dim"], a * 0.5)
            cr.fill()

        if needed_h != self.content_h:
            self.content_h = needed_h
            self.canvas.set_size_request(WIDGET_W, needed_h)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    w = ClipboardTimelineWidget()
    w.connect("destroy", Gtk.main_quit)
    Gtk.main()
