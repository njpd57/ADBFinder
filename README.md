# ADBFinder

Explorador de archivos para Android a través de adb (Python + Tkinter, sin dependencias externas).

## Descarga
Descarga el ejecutable para Windows desde la [última release](https://github.com/njpd57/ADBFinder/releases/latest) (`ADBFinder.exe`, no requiere Python).

## Requisitos
- Python 3.9+
- `adb` (platform-tools). Se busca en el PATH, en `C:\platform-tools` o en la variable `ADB_PATH`.
- Dispositivo con **Depuración USB** activada y autorizada.

## Uso
```
python main.py
```
- Doble clic: entrar en carpeta · Backspace: subir · F5: recargar
- Ctrl+C / Ctrl+X / Ctrl+V: copiar / cortar / pegar dentro del dispositivo
- F2 renombrar · Supr borrar · clic derecho: menú
- **Descargar al PC** (adb pull), **Subir archivos / carpeta** (adb push)

## Tests
```
python -m unittest discover tests
```

## Empaquetar
```
pip install pyinstaller
pyinstaller --noconsole --onefile main.py
```
