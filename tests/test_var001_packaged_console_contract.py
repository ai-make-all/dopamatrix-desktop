"""H4-1B source contracts for one packaged backend binary on Windows."""

from __future__ import annotations

import json
import platform
import unittest
from pathlib import Path

from build_backend import get_pyinstaller_command, get_sidecar_filename


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class PackagedConsoleContractTests(unittest.TestCase):
    def test_pyinstaller_build_is_one_console_backend_binary(self):
        command = get_pyinstaller_command()

        self.assertEqual(command[0], "pyinstaller")
        self.assertIn("--onefile", command)
        self.assertIn("--console", command)
        self.assertNotIn("--windowed", command)
        self.assertEqual(command.count("--name"), 1)
        name_index = command.index("--name")
        self.assertEqual(command[name_index + 1], "backend")
        self.assertEqual(command[-1], "main.py")

    @unittest.skipUnless(platform.system() == "Windows", "Windows sidecar naming contract")
    def test_tauri_uses_same_backend_external_binary_without_operator_args(self):
        config = json.loads(
            (REPOSITORY_ROOT / "web_ui" / "src-tauri" / "tauri.conf.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(config["bundle"]["externalBin"], ["bin/backend"])
        self.assertEqual(get_sidecar_filename(), "backend-x86_64-pc-windows-msvc.exe")

        rust_source = (
            REPOSITORY_ROOT / "web_ui" / "src-tauri" / "src" / "lib.rs"
        ).read_text(encoding="utf-8")
        start = rust_source.index('.sidecar("backend")')
        end = rust_source.index(".spawn()", start)
        sidecar_builder = rust_source[start:end]
        self.assertNotIn(".arg(", sidecar_builder)
        self.assertNotIn(".args(", sidecar_builder)
        self.assertNotIn('"operator"', sidecar_builder)


if __name__ == "__main__":
    unittest.main()
