# ADBFinder

File explorer for Android over adb (Python + Tkinter, no external dependencies).

## Download
Get the Windows executable from the [latest release](https://github.com/njpd57/ADBFinder/releases/latest) (`ADBFinder-Setup-<version>.exe` installer or portable `ADBFinder.exe`, no Python required).

## Requirements
- Python 3.9+
- `adb` (platform-tools), found in `PATH`, `C:\platform-tools` or `ADB_PATH`.
- Device with **USB debugging** enabled and authorized.

## Usage
```
python main.pyw
```
- Double click: open folder · Backspace: go up · F5: reload
- Ctrl+C / Ctrl+X / Ctrl+V: copy / cut / paste inside the device
- F2 rename · Del delete · right click: menu
- **Download to PC** (adb pull), **Upload files / folder** (adb push)

## Tests
```
python -m unittest discover tests
```

## Package
```
pip install pyinstaller
pyinstaller --noconsole --onefile --name ADBFinder main.pyw
```
To build the Windows installer (`dist\ADBFinder-Setup-<version>.exe`), install [Inno Setup 6](https://jrsoftware.org/isinfo.php) and then run:
```
ISCC /DAppVersion=1.1.0 installer\ADBFinder.iss
```
