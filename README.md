# ExplorerLargerer

A Windows photo browser that shows thumbnails **way** larger than Windows Explorer's maximum "Extra Large" size.

![screenshot placeholder](screenshot.png)

## Why?

Windows Explorer maxes out at 256px thumbnails. ExplorerLargerer lets you browse photos at 80–1000px thumbnails — useful when you want to visually scan a folder of photos without opening each one.

## Features

- Scrollable grid of photos at any thumbnail size from **80px to 1000px**
- Live slider to resize thumbnails instantly
- Dark UI
- Click any photo to open it in your default viewer
- Keyboard shortcuts:
  - `Ctrl+O` — open folder
  - `+` / `-` — nudge thumbnail size up/down

## Requirements

- Windows
- Python 3.10+ with [Pillow](https://pillow.readthedocs.io/)

```
pip install pillow
```

## Usage

```
python explorer_largerer.py
python explorer_largerer.py "C:\Users\You\Pictures"
```

Or double-click **ExplorerLargerer.bat** (edit the Python path inside if needed).

## License

MIT
