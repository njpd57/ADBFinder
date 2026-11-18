import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adbfinder.adb import parse_ls, parse_du, parse_meminfo, unique_name, human_size  # noqa: E402

SAMPLE = """total 24
drwxrwx--x  2 root sdcard_rw 4096 2024-05-01 10:22 .
drwxr-xr-x 30 root root      4096 2024-05-01 10:22 ..
drwxrwx--x  2 root sdcard_rw 4096 2024-05-01 10:22 Mis Fotos
-rw-rw----  1 root sdcard_rw 1234 2024-05-02 08:00 archivo con espacios.txt
lrwxrwxrwx  1 root root        10 2024-05-02 08:00 enlace -> /sdcard/Mis Fotos
-rw-rw----  1 root sdcard_rw  7 May 3 12:01 viejo.txt
"""


class ParseTests(unittest.TestCase):
    def test_parse(self):
        e = {x.name: x for x in parse_ls(SAMPLE)}
        self.assertEqual(set(e), {"Mis Fotos", "archivo con espacios.txt", "enlace", "viejo.txt"})
        self.assertTrue(e["Mis Fotos"].is_dir)
        self.assertEqual(e["archivo con espacios.txt"].size, 1234)
        self.assertTrue(e["enlace"].is_link)
        self.assertEqual(e["viejo.txt"].mtime, "May 3 12:01")

    def test_unique(self):
        self.assertEqual(unique_name("a.txt", {"a.txt"}), "a (1).txt")
        self.assertEqual(unique_name("a.txt", {"a.txt", "a (1).txt"}), "a (2).txt")
        self.assertEqual(unique_name("b", set()), "b")

    def test_meminfo(self):
        df = ("Filesystem 1K-blocks Used Available Use% Mounted on\n"
              "/dev/fuse 1000 400 600 40% /storage/emulated\n")
        mem = "MemTotal:        4000 kB\nMemFree: 1 kB\nMemAvailable:   1500 kB\n"
        m = parse_meminfo(df, mem)
        self.assertEqual((m.disk_total, m.disk_used, m.disk_free), (1024000, 409600, 614400))
        self.assertEqual((m.ram_total, m.ram_free), (4000 * 1024, 1500 * 1024))

    def test_du(self):
        out = "100\t/sdcard/DCIM\n8\t/sdcard/Mis Fotos\n120\t/sdcard\n"
        self.assertEqual(parse_du(out, "/sdcard"),
                         {"DCIM": 100 * 1024, "Mis Fotos": 8 * 1024})

    def test_size(self):
        self.assertEqual(human_size(512), "512 B")
        self.assertEqual(human_size(2048), "2.0 KB")


if __name__ == "__main__":
    unittest.main()
