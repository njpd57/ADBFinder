"""GUI Tkinter: explorador de archivos Android a través de adb."""
from __future__ import annotations

import posixpath
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from .adb import Adb, AdbError, Device, Entry, human_size, unique_name

HOME = "/sdcard"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("ADBFinder")
        root.geometry("900x560")
        try:
            self.adb = Adb()
        except AdbError as e:
            messagebox.showerror("ADBFinder", str(e))
            raise SystemExit(1)

        self.devices: list[Device] = []
        self.serial: str | None = None
        self.path = HOME
        self.history: list[str] = []
        self.entries: dict[str, Entry] = {}
        self.clipboard: tuple[str, str, list[str]] | None = None  # (modo, serial, rutas)
        self.sort_col, self.sort_rev = "name", False
        self.busy = False
        self.sizes: dict[str, int] = {}
        self.sizes_pending = False
        self.size_token = 0
        self.size_cache: dict[tuple[str, str], tuple[float, dict[str, int]]] = {}
        self.SIZE_FRESH = 120  # s: antes de esto se usa la caché sin recalcular

        self._build()
        self.refresh_devices()

    # ---------- UI ----------
    def _build(self):
        top = ttk.Frame(self.root, padding=4)
        top.pack(fill="x")
        self.dev_var = tk.StringVar()
        self.dev_combo = ttk.Combobox(top, textvariable=self.dev_var, state="readonly", width=34)
        self.dev_combo.pack(side="left")
        self.dev_combo.bind("<<ComboboxSelected>>", lambda e: self._select_device())
        ttk.Button(top, text="⟳", width=3, command=self.refresh_devices).pack(side="left", padx=2)
        ttk.Button(top, text="◀", width=3, command=self.go_back).pack(side="left", padx=(10, 0))
        ttk.Button(top, text="▲", width=3, command=self.go_up).pack(side="left")
        ttk.Button(top, text="🏠", width=3, command=lambda: self.navigate(HOME)).pack(side="left")
        self.path_var = tk.StringVar(value=self.path)
        pe = ttk.Entry(top, textvariable=self.path_var)
        pe.pack(side="left", fill="x", expand=True, padx=6)
        pe.bind("<Return>", lambda e: self.navigate(self.path_var.get().strip() or "/"))

        bar = ttk.Frame(self.root, padding=(4, 0))
        bar.pack(fill="x")
        for text, cmd in [("Copiar", self.copy), ("Cortar", self.cut), ("Pegar", self.paste),
                          ("Renombrar", self.rename), ("Borrar", self.delete),
                          ("Nueva carpeta", self.new_folder),
                          ("⬇ Descargar al PC", self.pull), ("⬆ Subir archivos", self.push),
                          ("⬆ Subir carpeta", self.push_dir)]:
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=1, pady=2)

        cols = ("name", "size", "mtime", "perms")
        paned = ttk.PanedWindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=4, pady=4)
        side = ttk.Frame(paned, width=190)
        frame = ttk.Frame(paned)
        paned.add(side, weight=0)
        paned.add(frame, weight=1)
        self._build_sidebar(side)
        self.tree =ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")
        for c, t, w in [("name", "Nombre", 420), ("size", "Tamaño", 90),
                        ("mtime", "Modificado", 150), ("perms", "Permisos", 110)]:
            self.tree.heading(c, text=t, command=lambda c=c: self.sort_by(c))
            self.tree.column(c, width=w, anchor="e" if c == "size" else "w")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self.on_open)
        self.tree.bind("<Return>", self.on_open)
        self.tree.bind("<BackSpace>", lambda e: self.go_up())
        self.tree.bind("<Button-3>", self.on_context)
        # arrastrar dentro del dispositivo (mover; con Ctrl = copiar)
        self.drag_src: list[str] = []
        self.drag_moved = False
        self.drag_row = ""
        self.tree.bind("<ButtonPress-1>", self.on_press)
        self.tree.bind("<B1-Motion>", self.on_drag)
        self.tree.bind("<ButtonRelease-1>", self.on_release)
        # soltar archivos desde el Explorador de Windows (subir)
        self.root.after(200, self._enable_drop)

        self.menu = tk.Menu(self.root, tearoff=0)
        for text, cmd in [("Copiar", self.copy), ("Cortar", self.cut), ("Pegar", self.paste),
                          ("Renombrar", self.rename), ("Borrar", self.delete), (None, None),
                          ("Descargar al PC", self.pull), ("Nueva carpeta", self.new_folder)]:
            self.menu.add_separator() if text is None else self.menu.add_command(label=text, command=cmd)

        self.root.bind("<Control-c>", lambda e: self.copy())
        self.root.bind("<Control-x>", lambda e: self.cut())
        self.root.bind("<Control-v>", lambda e: self.paste())
        self.root.bind("<Control-a>", lambda e: self.tree.selection_set(self.tree.get_children()))
        self.root.bind("<F2>", lambda e: self.rename())
        self.root.bind("<F5>", lambda e: (self.invalidate_sizes(), self.reload()))
        self.root.bind("<Delete>", lambda e: self.delete())

        self.status = tk.StringVar(value="Listo")
        sbar = ttk.Frame(self.root, relief="sunken")
        sbar.pack(fill="x", side="bottom")
        self.mem_var = tk.StringVar()
        self.ram_var = tk.StringVar()
        ttk.Label(sbar, textvariable=self.ram_var, anchor="e", padding=(8, 0)).pack(side="right")
        ttk.Label(sbar, textvariable=self.mem_var, anchor="e").pack(side="right")
        self.disk_bar = ttk.Progressbar(sbar, length=120, maximum=100)
        self.disk_bar.pack(side="right", padx=6, pady=2)
        ttk.Label(sbar, textvariable=self.status, anchor="w").pack(side="left", fill="x", expand=True)

    def set_status(self, msg: str):
        self.status.set(msg)

    # ---------- barra lateral ----------
    FAVORITES = [("🏠", "Inicio", "/sdcard"), ("🖼", "DCIM", "/sdcard/DCIM"),
                 ("📷", "Pictures", "/sdcard/Pictures"), ("⬇", "Download", "/sdcard/Download"),
                 ("📄", "Documents", "/sdcard/Documents"), ("🎵", "Music", "/sdcard/Music"),
                 ("🎬", "Movies", "/sdcard/Movies"), ("💬", "Android", "/sdcard/Android")]

    def _build_sidebar(self, parent):
        self.side = ttk.Treeview(parent, show="tree", selectmode="browse")
        sb = ttk.Scrollbar(parent, orient="vertical", command=self.side.yview)
        self.side.configure(yscrollcommand=sb.set)
        self.side.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.side.column("#0", width=180)
        self.side.bind("<<TreeviewSelect>>", self.on_side_select)
        self.side.bind("<<TreeviewOpen>>", self.on_side_open)
        self.fill_sidebar()

    def fill_sidebar(self):
        self.side.delete(*self.side.get_children())
        self.side.insert("", "end", "sec:fav", text="Acceso rápido", open=True)
        for icon, name, path in self.FAVORITES:
            self.side.insert("sec:fav", "end", f"fav:{path}", text=f"{icon} {name}")
        self.side.insert("", "end", "sec:dev", text="Este dispositivo", open=True)
        self._side_dir("sec:dev", "/sdcard", "💾 Almacenamiento interno")
        self._side_dir("sec:dev", "/", "🖥 Raíz (/)")
        if self.serial:
            try:
                for v in self.adb.list_subdirs(self.serial, "/storage"):
                    if v not in ("self", "emulated"):
                        self._side_dir("sec:dev", f"/storage/{v}", f"💳 {v}")
            except AdbError:
                pass

    def _side_dir(self, parent: str, path: str, text: str):
        iid = f"dev:{path}"
        if self.side.exists(iid):
            return
        self.side.insert(parent, "end", iid, text=text)
        self.side.insert(iid, "end", f"dummy:{path}")

    def on_side_open(self, _e=None):
        iid = self.side.focus()
        kids = self.side.get_children(iid)
        if not iid.startswith("dev:") or not kids or not kids[0].startswith("dummy:") or not self.serial:
            return
        self.side.delete(*kids)
        base = iid[4:]
        try:
            subs = self.adb.list_subdirs(self.serial, base)
        except AdbError as e:
            self.set_status(f"Error: {e}")
            return
        for s in subs:
            self._side_dir(iid, posixpath.join(base, s), "📁 " + s)

    def on_side_select(self, _e=None):
        sel = self.side.selection()
        if sel and ":" in sel[0] and not sel[0].startswith(("sec:", "dummy:")):
            self.navigate(sel[0].split(":", 1)[1])

    # ---------- memoria ----------
    def update_mem(self):
        serial, path = self.serial, self.path
        if not serial:
            return

        def work():
            try:
                info = self.adb.meminfo(serial, path)
            except AdbError:
                return
            self.root.after(0, lambda: self._show_mem(serial, info))

        threading.Thread(target=work, daemon=True).start()

    def _show_mem(self, serial, info):
        if serial != self.serial:
            return
        if info.disk_total:
            self.mem_var.set(f"Almacenamiento: {human_size(info.disk_free)} libres de "
                             f"{human_size(info.disk_total)}")
            self.disk_bar["value"] = 100 * info.disk_used / info.disk_total
        else:
            self.mem_var.set("")
            self.disk_bar["value"] = 0
        self.ram_var.set(f"RAM: {human_size(info.ram_free)} libres de {human_size(info.ram_total)}"
                         if info.ram_total else "")

    # ---------- dispositivos ----------
    def refresh_devices(self):
        try:
            self.devices = self.adb.devices()
        except AdbError as e:
            self.set_status(str(e))
            return
        self.dev_combo["values"] = [d.label for d in self.devices]
        if not self.devices:
            self.dev_var.set("")
            self.serial = None
            self.clear_tree()
            self.set_status("Sin dispositivos. Conecta uno con depuración USB activada.")
            return
        keep = next((i for i, d in enumerate(self.devices) if d.serial == self.serial), 0)
        self.dev_combo.current(keep)
        self._select_device()

    def _select_device(self):
        i = self.dev_combo.current()
        if i < 0:
            return
        d = self.devices[i]
        self.serial = d.serial
        if d.state != "device":
            self.clear_tree()
            self.set_status(f"Dispositivo en estado '{d.state}'. "
                            "Acepta la autorización en el móvil o reconéctalo.")
            return
        self.history.clear()
        self.fill_sidebar()
        self.navigate(self.path if self.path else HOME, push=False)

    # ---------- navegación ----------
    def clear_tree(self):
        self.tree.delete(*self.tree.get_children())
        self.entries.clear()

    def navigate(self, path: str, push: bool = True):
        if not self.serial:
            return
        path = posixpath.normpath(path) if path else "/"
        try:
            entries = self.adb.list_dir(self.serial, path)
        except AdbError as e:
            self.set_status(f"Error: {e}")
            self.path_var.set(self.path)
            return
        if push and path != self.path:
            self.history.append(self.path)
        self.path = path
        self.path_var.set(path)
        self.entries = {e.name: e for e in entries}
        self.render()
        self.set_status(f"{len(entries)} elementos")
        self.update_mem()
        self.update_sizes()

    def update_sizes(self):
        """Calcula en segundo plano el peso de cada carpeta (du) y refresca la columna."""
        self.size_token += 1
        token, serial, path = self.size_token, self.serial, self.path
        self.sizes = {}
        self.sizes_pending = any(e.is_dir for e in self.entries.values())
        if not self.sizes_pending:
            return
        cached = self.size_cache.get((serial, path))
        if cached:
            ts, data = cached
            self.sizes, self.sizes_pending = dict(data), False
            self.render()
            if time.time() - ts < self.SIZE_FRESH:
                return  # caché reciente: no hace falta recalcular
            # caché vieja: se muestra y se refresca en segundo plano sin "…"
        else:
            self.render()

        def work():
            try:
                sizes = self.adb.folder_sizes(serial, path)
            except AdbError:
                sizes = None

            def apply():
                if sizes is not None:
                    self.size_cache[(serial, path)] = (time.time(), sizes)
                if token != self.size_token:
                    return  # el usuario ya cambió de carpeta
                self.sizes, self.sizes_pending = sizes or self.sizes, False
                self.render()

            self.root.after(0, apply)

        threading.Thread(target=work, daemon=True).start()

    def invalidate_sizes(self):
        """Tras modificar archivos, descarta la caché de la carpeta actual, sus
        ancestros y sus descendientes (sus pesos pudieron cambiar)."""
        cur = self.path.rstrip("/") + "/"
        for key in list(self.size_cache):
            serial, p = key
            p = p.rstrip("/") + "/"
            if serial == self.serial and (cur.startswith(p) or p.startswith(cur)):
                del self.size_cache[key]

    def _size_text(self, e: Entry) -> str:
        if not e.is_dir:
            return human_size(e.size)
        if e.name in self.sizes:
            return human_size(self.sizes[e.name])
        return "…" if self.sizes_pending else ""

    def render(self):
        selected = [i for i in self.tree.selection() if i in self.entries]
        self.tree.delete(*self.tree.get_children())
        keyf = {
            "name": lambda e: e.name.lower(),
            "size": lambda e: self.sizes.get(e.name, 0) if e.is_dir else e.size,
            "mtime": lambda e: e.mtime,
            "perms": lambda e: e.perms,
        }[self.sort_col]
        items = sorted(self.entries.values(), key=keyf, reverse=self.sort_rev)
        items.sort(key=lambda e: not e.is_dir)  # carpetas primero (orden estable)
        for e in items:
            label = ("📁 " if e.is_dir else "📄 ") + e.name
            self.tree.insert("", "end", iid=e.name,
                             values=(label, self._size_text(e), e.mtime, e.perms))
        if selected:
            self.tree.selection_set(selected)

    def sort_by(self, col: str):
        self.sort_rev = (not self.sort_rev) if col == self.sort_col else False
        self.sort_col = col
        self.render()

    def reload(self):
        self.navigate(self.path, push=False)

    def go_up(self):
        self.navigate(posixpath.dirname(self.path.rstrip("/")) or "/")

    def go_back(self):
        if self.history:
            self.navigate(self.history.pop(), push=False)

    def on_open(self, _e=None):
        sel = self.tree.selection()
        if len(sel) == 1 and self.entries[sel[0]].is_dir:
            self.navigate(posixpath.join(self.path, sel[0]))

    # ---------- arrastrar y soltar ----------
    def _enable_drop(self):
        from .dnd import enable_file_drop
        try:
            ok = enable_file_drop(self.root, self.on_file_drop)
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            self.set_status("Soltar desde el Explorador no disponible en este sistema.")

    def on_file_drop(self, files: list[str], x_root: int, y_root: int):
        if not self._need_device():
            return
        dest = self.path
        row = self._row_at(x_root, y_root)
        if row and self.entries[row].is_dir:
            dest = posixpath.join(self.path, row)
        serial = self.serial

        def work():
            for f in files:
                self.adb.push(serial, f, dest)

        self.run_bg(f"Subiendo {len(files)} elemento(s) a {dest}", work, f"Subido a {dest}")

    def _row_at(self, x_root: int, y_root: int) -> str:
        x, y = x_root - self.tree.winfo_rootx(), y_root - self.tree.winfo_rooty()
        if not (0 <= x < self.tree.winfo_width() and 0 <= y < self.tree.winfo_height()):
            return ""
        return self.tree.identify_row(y)

    def on_press(self, e):
        row = self.tree.identify_row(e.y)
        self.drag_row, self.drag_moved, self.drag_src = row, False, []
        if row and row in self.tree.selection() and not (e.state & 0x5):  # sin Shift/Ctrl
            self.drag_src = list(self.tree.selection())
            return "break"  # conserva la selección múltiple al empezar a arrastrar

    def on_drag(self, e):
        if self.drag_src:
            self.drag_moved = True
            target = self.tree.identify_row(e.y)
            ok = target and self.entries[target].is_dir and target not in self.drag_src
            self.tree.configure(cursor="hand2" if ok else "no" if target else "")
            return "break"

    def on_release(self, e):
        self.tree.configure(cursor="")
        src, self.drag_src = self.drag_src, []
        if not src:
            return
        if not self.drag_moved:  # clic simple sobre una fila ya seleccionada
            self.tree.selection_set(self.drag_row)
            return "break"
        target = self.tree.identify_row(e.y)
        if not target or target in src or not self.entries[target].is_dir:
            return "break"
        dest = posixpath.join(self.path, target)
        mode = "copy" if e.state & 0x4 else "move"  # Ctrl = copiar
        self._paste_into(mode, [posixpath.join(self.path, n) for n in src], dest)
        return "break"

    def on_context(self, e):
        row = self.tree.identify_row(e.y)
        if row and row not in self.tree.selection():
            self.tree.selection_set(row)
        self.menu.tk_popup(e.x_root, e.y_root)

    # ---------- utilidades ----------
    def selected_paths(self) -> list[str]:
        return [posixpath.join(self.path, n) for n in self.tree.selection()]

    def run_bg(self, label: str, work, done_msg: str):
        """Ejecuta `work()` en un hilo; al terminar refresca y muestra el resultado."""
        if self.busy:
            self.set_status("Hay otra operación en curso…")
            return
        self.busy = True
        self.set_status(label + "…")
        self.root.config(cursor="watch")

        def target():
            err = None
            try:
                work()
            except AdbError as e:
                err = str(e)
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {e}"
            self.root.after(0, lambda: finish(err))

        def finish(err):
            self.busy = False
            self.root.config(cursor="")
            self.invalidate_sizes()
            self.reload()
            if err:
                self.set_status(f"Error: {err}")
                messagebox.showerror("ADBFinder", err)
            else:
                self.set_status(done_msg)

        threading.Thread(target=target, daemon=True).start()

    def _need_device(self) -> bool:
        if not self.serial:
            self.set_status("Selecciona un dispositivo.")
            return False
        return True

    # ---------- portapapeles ----------
    def copy(self):
        self._clip("copy")

    def cut(self):
        self._clip("move")

    def _clip(self, mode: str):
        paths = self.selected_paths()
        if paths and self.serial:
            self.clipboard = (mode, self.serial, paths)
            self.set_status(f"{len(paths)} elemento(s) {'copiados' if mode == 'copy' else 'cortados'}")

    def paste(self):
        if not self._need_device():
            return
        if not self.clipboard:
            self.set_status("El portapapeles está vacío.")
            return
        mode, src_serial, paths = self.clipboard
        if src_serial != self.serial:
            messagebox.showinfo("ADBFinder", "No se puede pegar entre dispositivos distintos "
                                "(usa Descargar y Subir).")
            return
        self._paste_into(mode, paths, self.path)
        if mode == "move":
            self.clipboard = None

    def _paste_into(self, mode: str, paths: list[str], dest: str):
        serial = self.serial
        if dest == self.path:
            existing = set(self.entries)
        else:
            try:
                existing = {e.name for e in self.adb.list_dir(serial, dest)}
            except AdbError as e:
                self.set_status(f"Error: {e}")
                return
        plan: list[tuple[str, str | None]] = []  # (origen, nuevo nombre | None)
        for src in paths:
            name = posixpath.basename(src.rstrip("/"))
            parent = posixpath.dirname(src.rstrip("/")) or "/"
            if dest == src or dest.startswith(src.rstrip("/") + "/"):
                messagebox.showwarning("ADBFinder", f"No se puede pegar '{name}' dentro de sí mismo.")
                continue
            if mode == "move" and parent == dest:
                continue  # mover a la misma carpeta: nada que hacer
            new_name = None
            if name in existing:
                ans = messagebox.askyesnocancel(
                    "Ya existe", f"'{name}' ya existe en esta carpeta.\n\n"
                    "Sí = reemplazar\nNo = conservar ambos\nCancelar = omitir")
                if ans is None:
                    continue
                if ans is False:
                    new_name = unique_name(name, existing)
                    existing.add(new_name)
                else:
                    plan.append((posixpath.join(dest, name), "__delete__"))
            plan.append((src, new_name))
        if not plan:
            return

        def work():
            for src, nn in plan:
                if nn == "__delete__":
                    self.adb.delete(serial, src)
                elif mode == "copy":
                    self.adb.copy(serial, src, dest, nn)
                else:
                    self.adb.move(serial, src, dest, nn)

        verb = "Copiando" if mode == "copy" else "Moviendo"
        self.run_bg(verb, work, "Listo")

    # ---------- operaciones ----------
    def rename(self):
        sel = self.tree.selection()
        if len(sel) != 1 or not self._need_device():
            return
        old = sel[0]
        new = simpledialog.askstring("Renombrar", "Nuevo nombre:", initialvalue=old, parent=self.root)
        if not new or new == old or "/" in new:
            return
        if new in self.entries:
            messagebox.showwarning("ADBFinder", "Ya existe un elemento con ese nombre.")
            return
        p, serial = posixpath.join(self.path, old), self.serial
        self.run_bg("Renombrando", lambda: self.adb.rename(serial, p, new), "Renombrado")

    def delete(self):
        paths = self.selected_paths()
        if not paths or not self._need_device():
            return
        if not messagebox.askyesno("Borrar", f"¿Borrar {len(paths)} elemento(s) del dispositivo?\n"
                                   "Esta acción no se puede deshacer."):
            return
        serial = self.serial

        def work():
            for p in paths:
                self.adb.delete(serial, p)

        self.run_bg("Borrando", work, "Borrado")

    def new_folder(self):
        if not self._need_device():
            return
        name = simpledialog.askstring("Nueva carpeta", "Nombre:", parent=self.root)
        if not name or "/" in name:
            return
        p, serial = posixpath.join(self.path, name), self.serial
        self.run_bg("Creando carpeta", lambda: self.adb.mkdir(serial, p), "Carpeta creada")

    # ---------- PC <-> móvil ----------
    def pull(self):
        paths = self.selected_paths()
        if not paths or not self._need_device():
            return
        local = filedialog.askdirectory(title="Guardar en…")
        if not local:
            return
        serial = self.serial

        def work():
            for p in paths:
                self.adb.pull(serial, p, local)

        self.run_bg("Descargando", work, f"Descargado en {local}")

    def push(self):
        if not self._need_device():
            return
        files = filedialog.askopenfilenames(title="Archivos a subir")
        if files:
            self._push(list(files))

    def push_dir(self):
        if not self._need_device():
            return
        d = filedialog.askdirectory(title="Carpeta a subir")
        if d:
            self._push([d])

    def _push(self, locals_: list[str]):
        dest, serial = self.path, self.serial

        def work():
            for f in locals_:
                self.adb.push(serial, f, dest)

        self.run_bg("Subiendo", work, "Subida completada")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()
