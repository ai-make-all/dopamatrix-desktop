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

    def test_pyinstaller_packages_complete_prompt_resource_directory_once(self):
        command = get_pyinstaller_command()

        self.assertEqual(command.count("--add-data"), 1)
        data_index = command.index("--add-data")
        source_text, destination_text = command[data_index + 1].split(":", 1)
        self.assertEqual(source_text, "src/prompts")
        self.assertEqual(destination_text, "src/prompts")

        source_directory = REPOSITORY_ROOT / source_text
        self.assertTrue(source_directory.is_dir())

        templates = sorted(source_directory.rglob("*.jinja"))
        self.assertTrue(templates)
        self.assertIn(source_directory / "director_blueprint.jinja", templates)

        packaged_destinations = {
            Path(destination_text) / template.relative_to(source_directory)
            for template in templates
        }
        self.assertEqual(
            packaged_destinations,
            {
                Path("src/prompts") / template.relative_to(source_directory)
                for template in templates
            },
        )

    def test_prompt_resource_rule_excludes_runtime_and_secret_material(self):
        command = get_pyinstaller_command()
        data_index = command.index("--add-data")
        source_text, destination_text = command[data_index + 1].split(":", 1)

        self.assertEqual(
            (source_text, destination_text),
            ("src/prompts", "src/prompts"),
        )
        self.assertNotEqual(
            (REPOSITORY_ROOT / source_text).resolve(),
            REPOSITORY_ROOT.resolve(),
        )

        resource_files = [
            path.relative_to(REPOSITORY_ROOT / source_text).as_posix().lower()
            for path in (REPOSITORY_ROOT / source_text).rglob("*")
            if path.is_file()
        ]
        forbidden_names = {
            ".env",
            "logs",
            "output",
            "backup",
            "backups",
            "secure_settings",
        }
        for resource in resource_files:
            parts = set(Path(resource).parts)
            self.assertTrue(parts.isdisjoint(forbidden_names))
            self.assertFalse(resource.endswith((".db", ".db-wal", ".db-shm")))

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
