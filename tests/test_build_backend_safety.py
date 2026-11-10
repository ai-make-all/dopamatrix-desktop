"""RE-SAFE-01: isolated fixtures only; every subprocess.run is fail-closed mocked."""
import ast
from contextlib import closing
import importlib.util
import os
from pathlib import Path
import stat
import sqlite3
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("safe_build_under_test", PROJECT / "build_backend.py")
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)


class BuildBackendSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="re-safe-01-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "project"
        (self.root / "src" / "prompts").mkdir(parents=True)
        (self.root / "main.py").write_text("# synthetic input\n", encoding="utf-8")
        (self.root / "build_backend.py").write_text("# synthetic location\n", encoding="utf-8")
        self.addCleanup(patch.stopall)
        patch.object(backend, "__file__", str(self.root / "build_backend.py")).start()
        patch.object(backend.Path, "cwd", return_value=self.root).start()
        patch.object(backend.platform, "system", return_value="Windows").start()
        patch.object(backend.platform, "machine", return_value="AMD64").start()
        self.native = patch.object(
            backend.subprocess, "run", side_effect=AssertionError("REAL SUBPROCESS FORBIDDEN")
        ).start()
        self.native.side_effect = self.fake_build
        patch.object(backend.subprocess, "Popen", side_effect=AssertionError("REAL POPEN FORBIDDEN")).start()
        patch.object(os, "system", side_effect=AssertionError("REAL SHELL FORBIDDEN")).start()
        self.commands = []

    def fake_build(self, argv, *, cwd, check):
        """No native process: write only inside this fixture's freshly claimed stage."""
        self.assertEqual(cwd, str(self.root))
        self.assertTrue(check)
        self.assertEqual(argv[0], "pyinstaller")
        stage = Path(argv[argv.index("--specpath") + 1])
        self.assertEqual(stage.parent, self.root)
        self.assertTrue(stage.name.startswith(".re-safe-build-"))
        self.assertEqual(list(stage.iterdir()), [])
        for flag, child in (("--workpath", "build"), ("--distpath", "dist")):
            self.assertEqual(Path(argv[argv.index(flag) + 1]), stage / child)
        self.commands.append(argv)
        (stage / "dist").mkdir()
        name = "backend.exe" if os.name == "nt" else "backend"
        (stage / "dist" / name).write_bytes(b"SYNTHETIC SIDECAR - NOT EXECUTABLE")
        return subprocess.CompletedProcess(argv, 0)

    def staged_target(self):
        stages = list(self.root.glob(".re-safe-build-*"))
        self.assertEqual(len(stages), 1)
        return stages[0] / backend.get_sidecar_filename()

    def seed(self, relative, content=b"PREEXISTING - NOT DISPOSABLE"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_rs01_t01_no_reset_kill_or_cleanup(self):
        with patch.object(backend, "prepare_release_data") as reset, \
             patch.object(backend, "kill_backend_processes") as kill, \
             patch.object(backend, "clean_build_cache") as clean, \
             patch.object(backend, "move_with_retry") as move:
            self.assertIsNone(backend.build())
            for forbidden in (reset, kill, clean, move):
                forbidden.assert_not_called()
        for helper, args in ((backend.prepare_release_data, ()),
                             (backend.kill_backend_processes, ()),
                             (backend.clean_build_cache, ()),
                             (backend.move_with_retry, ("foreign", "foreign"))):
            with self.assertRaisesRegex(backend.BuildSafetyError, "DISABLED"):
                helper(*args)
        self.assertEqual(self.native.call_count, 1)

    def test_rs01_t02_business_fixture_unchanged(self):
        fixtures = {
            "output/clip.mp4": b"SYNTHETIC OUTPUT",
            "history.txt": b"task_history=7;usage_count=9",
            "Delivery/final": b"DELIVERY", "Backup/snapshot": b"BACKUP",
            "materials/input": b"MATERIAL", "Secure Settings/fake": b"NOT A SECRET",
        }
        for path, value in fixtures.items():
            self.seed(path, value)
        database = self.root / "dopamatrix.db"
        with closing(sqlite3.connect(database)) as db:
            db.executescript("CREATE TABLE task_history(id INTEGER);"
                             "INSERT INTO task_history VALUES(7);"
                             "CREATE TABLE local_assets_inventory(usage_count INTEGER);"
                             "INSERT INTO local_assets_inventory VALUES(9);")
            db.commit()
        fixtures["dopamatrix.db"] = database.read_bytes()
        backend.build()
        for path, value in fixtures.items():
            self.assertEqual((self.root / path).read_bytes(), value)
        with closing(sqlite3.connect(database)) as db:
            self.assertEqual(db.execute("SELECT id FROM task_history").fetchall(), [(7,)])
            self.assertEqual(db.execute("SELECT usage_count FROM local_assets_inventory").fetchall(), [(9,)])

    def test_rs01_t03_wrong_cwd_or_missing_input_refused_before_write(self):
        with patch.object(backend.Path, "cwd", return_value=self.root.parent):
            with self.assertRaisesRegex(backend.BuildSafetyError, "CWD_MISMATCH"):
                backend.build()
        (self.root / "main.py").unlink()  # Our own artificial input only.
        with self.assertRaises(backend.BuildSafetyError):
            backend.build()
        self.native.assert_not_called()
        self.assertEqual(list(self.root.glob(".re-safe-build-*")), [])

    def test_rs01_t04_existing_build_dist_spec_sidecar_preserved(self):
        paths = ["build/old", "dist/backend.exe", "old.spec",
                 "web_ui/src-tauri/bin/" + backend.get_sidecar_filename()]
        for path in paths:
            self.seed(path)
        backend.build()
        for path in paths:
            self.assertEqual((self.root / path).read_bytes(), b"PREEXISTING - NOT DISPOSABLE")
        self.assertTrue(self.staged_target().is_file())
        # Even a target appearing after the initial stage claim cannot be overwritten.
        real_fake = self.fake_build
        def racing_target(argv, **kwargs):
            result = real_fake(argv, **kwargs)
            stage = Path(argv[argv.index("--specpath") + 1])
            (stage / backend.get_sidecar_filename()).write_bytes(b"FOREIGN TARGET")
            return result
        self.native.side_effect = racing_target
        with self.assertRaises(backend.BuildSafetyError):
            backend.build()
        for stage in self.root.glob(".re-safe-build-*"):
            value = (stage / backend.get_sidecar_filename()).read_bytes()
            self.assertIn(value, (b"FOREIGN TARGET", b"SYNTHETIC SIDECAR - NOT EXECUTABLE"))

    def test_rs01_t05_injected_symlink_junction_alias_refused(self):
        real_lstat = Path.lstat
        for kind in ("symlink", "junction", "hardlink"):
            def injected(path, *, _kind=kind, **kwargs):
                info = real_lstat(path, **kwargs)
                if path == self.root / "main.py":
                    return SimpleNamespace(
                        st_mode=stat.S_IFLNK if _kind == "symlink" else info.st_mode,
                        st_file_attributes=0x400 if _kind == "junction" else 0,
                        st_nlink=2 if _kind == "hardlink" else info.st_nlink,
                    )
                return info
            with self.subTest(kind=kind), patch.object(Path, "lstat", injected):
                with self.assertRaisesRegex(backend.BuildSafetyError, "REPARSE|FILE_ALIAS"):
                    backend.build()
        real_resolve = Path.resolve
        def alias(path, *args, **kwargs):
            return self.root.parent if path == self.root else real_resolve(path, *args, **kwargs)
        with patch.object(Path, "resolve", alias):
            with self.assertRaisesRegex(backend.BuildSafetyError, "PATH_ALIAS"):
                backend.build()
        self.native.assert_not_called()
        self.assertEqual(list(self.root.glob(".re-safe-build-*")), [])

    def test_rs01_t06_permission_lock_native_failure_no_retry(self):
        with patch.object(backend.tempfile, "mkdtemp", side_effect=PermissionError("DENIED")):
            with self.assertRaisesRegex(backend.BuildSafetyError, "DENIED"):
                backend.build()
        self.native.assert_not_called()
        for failure in (PermissionError("FILE LOCKED"),
                        subprocess.CalledProcessError(9, ["FAKE PYINSTALLER"])):
            with self.subTest(failure=type(failure).__name__):
                self.native.reset_mock()
                self.native.side_effect = failure
                with self.assertRaises(backend.BuildSafetyError):
                    backend.build()
                self.assertEqual(self.native.call_count, 1)
        self.native.side_effect = self.fake_build
        with patch.object(backend.shutil, "copyfileobj", side_effect=PermissionError("COPY LOCKED")):
            with self.assertRaisesRegex(backend.BuildSafetyError, "COPY LOCKED"):
                backend.build()
        self.assertTrue(list(self.root.glob(".re-safe-build-*")))  # Retain, never auto-clean.

    def test_rs01_t07_positive_isolated_stage_and_changed_stage_rejection(self):
        backend.build()
        target = self.staged_target()
        self.assertEqual(target.read_bytes(), b"SYNTHETIC SIDECAR - NOT EXECUTABLE")
        self.assertTrue((target.parent / "dist").is_dir())
        self.assertFalse((self.root / "web_ui").exists())
        original_id = backend._object_id
        seen = []
        def changed(path):
            result = original_id(path)
            if path.name.startswith(".re-safe-build-"):
                seen.append(path)
                if len(seen) > 1:
                    return (-1, -1)
            return result
        with patch.object(backend, "_object_id", side_effect=changed):
            with self.assertRaisesRegex(backend.BuildSafetyError, "STAGE_CHANGED"):
                backend.build()

    def test_rs01_t08_static_boundary_and_protected_identity(self):
        source = (PROJECT / "build_backend.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        build_calls = {node.func.id for node in ast.walk(functions["build"])
                       if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertTrue(build_calls.isdisjoint({"prepare_release_data", "kill_backend_processes",
                                               "clean_build_cache", "move_with_retry"}))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, {"remove", "unlink", "rmtree", "rename",
                                                  "replace", "copy2", "connect"})
        self.assertNotIn("taskkill", source.lower())
        self.assertEqual(backend.get_pyinstaller_command(), [
            "pyinstaller", "--noconfirm", "--onefile", "--console", "--name", "backend",
            "--add-data", "src/prompts:src/prompts", "main.py"])


if __name__ == "__main__":
    unittest.main()
