"""Capa ADB: todas las operaciones sobre el dispositivo, sin dependencias de GUI."""
from __future__ import annotations

import os
import posixpath
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class AdbError(Exception):
    pass


@dataclass
class Device:
    serial: str
    state: str
    info: str = ""

    @property
    def label(self) -> str:
        model = re.search(r"model:(\S+)", self.info)
        name = model.group(1) if model else ""
        txt = f"{name} ({self.serial})" if name else self.serial
        return txt if self.state == "device" else f"{txt} [{self.state}]"


@dataclass
class Entry:
    name: str
    is_dir: bool
    size: int
    mtime: str
    perms: str
    is_link: bool = False


_LS_RE = re.compile(
    r"^(?P<perm>[-dlbcpsD][rwxsStT-]{9})[.+]?\s+(?:\d+\s+)?"
    r"(?P<owner>\S+)\s+(?P<group>\S+)\s+"
    r"(?:(?P<size>\d+)|\d+,\s*\d+)\s+"
    r"(?P<date>\d{4}-\d\d-\d\d\s+\d\d:\d\d(?::\d\d)?|\w{3}\s+\d+\s+[\d:]+)\s+"
    r"(?P<name>.+)$"
)


@dataclass
class MemInfo:
    disk_total: int = 0
    disk_used: int = 0
    disk_free: int = 0
    ram_total: int = 0
    ram_free: int = 0


def parse_meminfo(df_out: str, mem_out: str) -> MemInfo:
    """df -k (última línea de datos) + líneas MemTotal/MemAvailable de /proc/meminfo."""
    info = MemInfo()
    lines = [l for l in df_out.splitlines() if l.strip()]
    for line in reversed(lines):
        t = line.split()
        if len(t) >= 5 and t[-5].isdigit() and t[-4].isdigit() and t[-3].isdigit():
            info.disk_total, info.disk_used, info.disk_free = (int(x) * 1024 for x in t[-5:-2])
            break
    for line in mem_out.splitlines():
        m = re.match(r"(MemTotal|MemAvailable):\s+(\d+)\s*kB", line)
        if m:
            kb = int(m.group(2)) * 1024
            if m.group(1) == "MemTotal":
                info.ram_total = kb
            else:
                info.ram_free = kb
    return info


def parse_du(output: str, base: str) -> dict[str, int]:
    """Salida de `du -k` -> {nombre_hijo: bytes}. Ignora la línea de la propia carpeta."""
    base = base.rstrip("/")
    sizes: dict[str, int] = {}
    for line in output.splitlines():
        m = re.match(r"^\s*(\d+)\s+(.+?)\s*$", line)
        if not m:
            continue
        path = m.group(2).rstrip("/")
        if path == base or path == "":
            continue
        sizes[posixpath.basename(path)] = int(m.group(1)) * 1024
    return sizes


def find_adb() -> str:
    env = os.environ.get("ADB_PATH")
    if env and os.path.isfile(env):
        return env
    found = shutil.which("adb")
    if found:
        return found
    for cand in (r"C:\platform-tools\adb.exe",
                 os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe")):
        if os.path.isfile(cand):
            return cand
    raise AdbError("No se encontró adb. Instala platform-tools o define ADB_PATH.")


def parse_ls(output: str) -> list[Entry]:
    entries: list[Entry] = []
    for line in output.splitlines():
        line = line.rstrip("\r")
        m = _LS_RE.match(line)
        if not m:
            continue
        name = m.group("name")
        is_link = m.group("perm")[0] == "l"
        if " -> " in name:
            name = name.split(" -> ", 1)[0]
            is_link = True
        if name in (".", ".."):
            continue
        entries.append(Entry(
            name=name,
            is_dir=m.group("perm")[0] == "d",
            size=int(m.group("size") or 0),
            mtime=m.group("date"),
            perms=m.group("perm"),
            is_link=is_link,
        ))
    return entries


class Adb:
    def __init__(self, adb_path: str | None = None):
        self.adb = adb_path or find_adb()

    def _run(self, args: list[str], timeout: int | None = 60, check: bool = True):
        try:
            p = subprocess.run(
                [self.adb, *args], capture_output=True, timeout=timeout,
                creationflags=_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            raise AdbError("adb tardó demasiado en responder.")
        out = p.stdout.decode("utf-8", "replace")
        err = p.stderr.decode("utf-8", "replace").strip()
        if check and p.returncode != 0:
            raise AdbError(err or out.strip() or f"adb falló (código {p.returncode})")
        return p.returncode, out, err

    def _shell(self, serial: str, command: str, timeout: int | None = 600, check=True):
        return self._run(["-s", serial, "shell", command], timeout=timeout, check=check)

    # ---- dispositivos ----
    def devices(self) -> list[Device]:
        _, out, _ = self._run(["devices", "-l"], timeout=15)
        res = []
        for line in out.splitlines()[1:]:
            parts = line.split(None, 2)
            if len(parts) >= 2 and not line.startswith("*"):
                res.append(Device(parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
        return res

    # ---- listado ----
    def list_dir(self, serial: str, path: str) -> list[Entry]:
        q = shlex.quote(path.rstrip("/") + "/")
        rc, out, err = self._shell(serial, f"ls -laL {q}", check=False)
        entries = parse_ls(out)
        if not entries and ("denied" in (out + err).lower() or "No such" in (out + err)
                            or "Not a directory" in (out + err)):
            raise AdbError((err or out).strip().splitlines()[0])
        if not entries:  # toybox sin -L / vacío: reintento simple
            rc, out, err = self._shell(serial, f"ls -la {q}", check=False)
            entries = parse_ls(out)
            if not entries and rc != 0:
                raise AdbError((err or out).strip() or "No se pudo listar la carpeta")
        return entries

    def list_subdirs(self, serial: str, path: str) -> list[str]:
        return sorted((e.name for e in self.list_dir(serial, path) if e.is_dir), key=str.lower)

    def folder_sizes(self, serial: str, path: str) -> dict[str, int]:
        """Tamaño de cada hijo de `path` (du -k -d 1; alternativa du -sk */*)."""
        q = shlex.quote(path.rstrip("/") or "/")
        _, out, _ = self._shell(serial, f"du -k -d 1 {q} 2>/dev/null", timeout=300, check=False)
        sizes = parse_du(out, path)
        if not sizes:
            base = shlex.quote(path.rstrip("/"))
            _, out, _ = self._shell(serial, f"du -sk {base}/* {base}/.[!.]* 2>/dev/null",
                                    timeout=300, check=False)
            sizes = parse_du(out, path)
        return sizes

    def meminfo(self, serial: str, path: str) -> MemInfo:
        sep = "@@MEM@@"
        cmd = f"df -k {shlex.quote(path)}; echo {sep}; cat /proc/meminfo"
        _, out, _ = self._shell(serial, cmd, timeout=20, check=False)
        df_out, _, mem_out = out.partition(sep)
        return parse_meminfo(df_out, mem_out)

    def exists(self, serial: str, path: str) -> bool:
        rc, _, _ = self._shell(serial, f"test -e {shlex.quote(path)}", check=False)
        return rc == 0

    def is_dir(self, serial: str, path: str) -> bool:
        rc, _, _ = self._shell(serial, f"test -d {shlex.quote(path)}", check=False)
        return rc == 0

    # ---- operaciones en el dispositivo ----
    def _sh_ok(self, serial: str, command: str):
        rc, out, err = self._shell(serial, command, check=False)
        if rc != 0 or "Permission denied" in out or "No such file" in out:
            raise AdbError((err or out).strip() or "Operación fallida")

    def copy(self, serial: str, src: str, dst_dir: str, new_name: str | None = None):
        dst = posixpath.join(dst_dir, new_name or posixpath.basename(src.rstrip("/")))
        self._sh_ok(serial, f"cp -r {shlex.quote(src)} {shlex.quote(dst)}")

    def move(self, serial: str, src: str, dst_dir: str, new_name: str | None = None):
        dst = posixpath.join(dst_dir, new_name or posixpath.basename(src.rstrip("/")))
        self._sh_ok(serial, f"mv {shlex.quote(src)} {shlex.quote(dst)}")

    def delete(self, serial: str, path: str):
        if path.strip("/") == "":
            raise AdbError("Ruta no permitida")
        self._sh_ok(serial, f"rm -rf {shlex.quote(path)}")

    def mkdir(self, serial: str, path: str):
        self._sh_ok(serial, f"mkdir -p {shlex.quote(path)}")

    def rename(self, serial: str, path: str, new_name: str):
        dst = posixpath.join(posixpath.dirname(path.rstrip("/")), new_name)
        self._sh_ok(serial, f"mv {shlex.quote(path)} {shlex.quote(dst)}")

    # ---- transferencia PC <-> móvil ----
    def pull(self, serial: str, remote: str, local_dir: str):
        self._run(["-s", serial, "pull", remote, local_dir], timeout=None)

    def push(self, serial: str, local: str, remote_dir: str):
        try:
            self._run(["-s", serial, "push", local, remote_dir.rstrip("/") + "/"], timeout=None)
        except AdbError as e:
            # Protected locations (e.g. Android/data) reject the directory creation done by
            # `adb push`, although the shell can create them and single files can be pushed.
            if "secure_mkdirs" not in str(e) or not os.path.isdir(local):
                raise
            self._push_tree(serial, local, remote_dir)

    def _push_tree(self, serial: str, local: str, remote_dir: str):
        local = os.path.abspath(local)
        root = posixpath.join(remote_dir, os.path.basename(local))
        dirs, files = [root], []
        for cur, subdirs, names in os.walk(local):
            rel = os.path.relpath(cur, local).replace(os.sep, "/")
            base = root if rel == "." else posixpath.join(root, rel)
            dirs.extend(posixpath.join(base, d) for d in subdirs)
            files.extend((os.path.join(cur, n), base) for n in names)
        for i in range(0, len(dirs), 50):
            self.mkdir_many(serial, dirs[i:i + 50])
        for src, dst in files:
            self._run(["-s", serial, "push", src, dst.rstrip("/") + "/"], timeout=None)

    def mkdir_many(self, serial: str, paths: list[str]):
        self._sh_ok(serial, "mkdir -p " + " ".join(shlex.quote(p) for p in paths))


def unique_name(name: str, existing: set[str]) -> str:
    if name not in existing:
        return name
    stem, ext = posixpath.splitext(name)
    i = 1
    while f"{stem} ({i}){ext}" in existing:
        i += 1
    return f"{stem} ({i}){ext}"


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return str(n)
