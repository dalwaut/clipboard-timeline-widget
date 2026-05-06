# Clipboard Timeline Desktop Widget

A lightweight Linux desktop widget that tracks your clipboard history with pin favorites, time tracking, and click-to-copy.

## Features

- **Auto-capture** — Monitors clipboard every 800ms, records new entries
- **Click to copy** — Click any entry to paste it back to clipboard
- **Pin favorites** — Click the dot to pin important clips (survive clear)
- **Time tracking** — Shows "now", "5m", "2h", "1d" for each entry
- **Scrollable** — Scroll wheel for long history
- **Clear History** — Wipe non-pinned entries from settings
- **Draggable** — Click and drag the title bar
- **Adjustable transparency** — Opacity slider
- **Auto Start** — Toggle to launch on login
- **Warm purple theme** — distinct from other BB widgets
- **Purely local** — No cloud, no network, no tracking

## Requirements

```bash
sudo apt install python3-gi python3-gi-cairo
```

## Install

```bash
git clone https://github.com/dalwaut/clipboard-timeline-widget.git
cd clipboard-timeline-widget
chmod +x clipboard-timeline-widget.py
./clipboard-timeline-widget.py
```

Or install via [BB Widget Manager](https://github.com/dalwaut/bb-widgets).

## Built by [Boutabyte](https://boutabyte.com)

## License

MIT
