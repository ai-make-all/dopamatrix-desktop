from __future__ import annotations

import ast
import json
import tomllib
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TAURI_CONFIG_PATH = REPOSITORY_ROOT / "web_ui/src-tauri/tauri.conf.json"
PACKAGE_JSON_PATH = REPOSITORY_ROOT / "web_ui/package.json"
PACKAGE_LOCK_PATH = REPOSITORY_ROOT / "web_ui/package-lock.json"
VERSION_SOURCE_PATH = REPOSITORY_ROOT / "src/version.py"
LOGIN_SOURCE_PATH = REPOSITORY_ROOT / "web_ui/src/components/Login.vue"
CARGO_MANIFEST_PATH = REPOSITORY_ROOT / "web_ui/src-tauri/Cargo.toml"
CARGO_LOCK_PATH = REPOSITORY_ROOT / "web_ui/src-tauri/Cargo.lock"


def _application_version() -> str:
    tree = ast.parse(VERSION_SOURCE_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "APPLICATION_VERSION"
            for target in node.targets
        ):
            continue
        value = ast.literal_eval(node.value)
        if isinstance(value, str):
            return value
    raise AssertionError("APPLICATION_VERSION string assignment not found")


def _walk_mapping_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key))
            keys.update(_walk_mapping_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_walk_mapping_keys(child))
    return keys


class H6InstallerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tauri = json.loads(TAURI_CONFIG_PATH.read_text(encoding="utf-8"))
        cls.package = json.loads(PACKAGE_JSON_PATH.read_text(encoding="utf-8"))
        cls.package_lock = json.loads(PACKAGE_LOCK_PATH.read_text(encoding="utf-8"))
        with CARGO_MANIFEST_PATH.open("rb") as cargo_manifest:
            cls.cargo = tomllib.load(cargo_manifest)
        with CARGO_LOCK_PATH.open("rb") as cargo_lock:
            cls.cargo_lock = tomllib.load(cargo_lock)
        cls.login = LOGIN_SOURCE_PATH.read_text(encoding="utf-8")

    def test_bundle_is_nsis_only_current_user(self):
        bundle = self.tauri["bundle"]
        self.assertIs(bundle["active"], True)
        self.assertEqual(bundle["targets"], "nsis")
        self.assertEqual(bundle["windows"]["nsis"]["installMode"], "currentUser")

        install_modes = [
            child.get("installMode")
            for child in bundle["windows"].values()
            if isinstance(child, dict) and "installMode" in child
        ]
        self.assertEqual(install_modes, ["currentUser"])
        self.assertNotIn("perMachine", install_modes)
        self.assertNotIn("both", install_modes)

    def test_bundle_preserves_exact_sidecar_and_media_resources(self):
        bundle = self.tauri["bundle"]
        self.assertEqual(bundle["externalBin"], ["bin/backend"])
        self.assertEqual(
            bundle["resources"],
            ["bin/ffmpeg.exe", "bin/ffprobe.exe"],
        )
        self.assertNotIn(".env", bundle["resources"])
        self.assertEqual(len(bundle["externalBin"]), 1)
        self.assertEqual(Path(bundle["externalBin"][0]).name, "backend")

    def test_no_wix_or_updater_configuration_is_introduced(self):
        all_keys = _walk_mapping_keys(self.tauri)
        self.assertNotIn("wix", self.tauri["bundle"])
        self.assertNotIn("wix", all_keys)
        self.assertNotIn("createUpdaterArtifacts", all_keys)
        self.assertNotIn("updater", all_keys)

    def test_release_identity_is_aligned(self):
        self.assertEqual(self.tauri["version"], "1.5.0-rc2")
        self.assertEqual(self.package["version"], "1.5.0-rc2")
        self.assertEqual(self.package_lock["version"], "1.5.0-rc2")
        self.assertEqual(
            self.package_lock["packages"][""]["version"],
            "1.5.0-rc2",
        )
        self.assertEqual(_application_version(), "1.5.0-rc2")
        self.assertEqual(self.cargo["package"]["version"], "1.5.0-rc2")
        local_app = [
            package
            for package in self.cargo_lock["package"]
            if package["name"] == "app"
        ]
        self.assertEqual(len(local_app), 1)
        self.assertEqual(local_app[0]["version"], "1.5.0-rc2")

    def test_login_displays_current_release_identity_only(self):
        self.assertIn("SYSTEM READY · v1.5.0-rc2", self.login)
        self.assertIn("DOPAMATRIX // DESKTOP // v1.5.0-rc2", self.login)
        self.assertNotIn("v1.1-ALPHA", self.login)
        self.assertNotIn("BUILD 001", self.login)
        self.assertNotIn("DESKTOP ALPHA", self.login)


if __name__ == "__main__":
    unittest.main()
