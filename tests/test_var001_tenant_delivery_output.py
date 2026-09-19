from __future__ import annotations

import inspect
import os
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import delivery_output, routes_dsl, routes_matrix, settings_router
from src.api.runtime_paths import temporary_test_runtime_paths


class DeliveryRootSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "dopamatrix.db"
        self.runtime_paths = temporary_test_runtime_paths(self.root)
        self.runtime_paths.__enter__()
        app = FastAPI()
        app.include_router(settings_router.router)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.runtime_paths.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_global_round_trip_and_blank_unset(self):
        delivery_root = self.root / "operator-delivery"
        response = self.client.post(
            "/settings/delivery-root",
            json={"delivery_root": str(delivery_root)},
            headers={"X-Local-User": "Tenant-A"},
        )
        self.assertEqual(response.status_code, 200)
        normalized = str(delivery_root.resolve())
        self.assertEqual(
            response.json(),
            {"delivery_root": normalized, "is_configured": True},
        )

        other_tenant = self.client.get(
            "/settings/delivery-root",
            headers={"X-Local-User": "Tenant-B"},
        )
        self.assertEqual(other_tenant.json()["delivery_root"], normalized)

        cleared = self.client.post(
            "/settings/delivery-root",
            json={"delivery_root": "   "},
        )
        self.assertEqual(
            cleared.json(),
            {"delivery_root": "", "is_configured": False},
        )
        self.assertEqual(
            self.client.get("/settings/delivery-root").json(),
            {"delivery_root": "", "is_configured": False},
        )

    def test_persisted_in_app_settings(self):
        delivery_root = self.root / "persisted-root"
        response = self.client.post(
            "/settings/delivery-root",
            json={"delivery_root": str(delivery_root)},
        )
        self.assertEqual(response.status_code, 200)
        connection = sqlite3.connect(self.db_path)
        try:
            row = connection.execute(
                "SELECT key_value FROM app_settings "
                "WHERE key_name = 'delivery_root'"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row, (str(delivery_root.resolve()),))

    def test_relative_root_rejected_before_persistence(self):
        response = self.client.post(
            "/settings/delivery-root",
            json={"delivery_root": "relative/delivery"},
        )
        self.assertEqual(response.status_code, 422)
        if not self.db_path.exists():
            count = 0
        else:
            connection = sqlite3.connect(self.db_path)
            try:
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'app_settings'"
                ).fetchone()
                count = (
                    connection.execute(
                        "SELECT COUNT(*) FROM app_settings "
                        "WHERE key_name = 'delivery_root'"
                    ).fetchone()[0]
                    if table is not None
                    else 0
                )
            finally:
                connection.close()
        self.assertEqual(count, 0)

    def test_frontend_hydrates_backend_and_logout_does_not_clear_setting(self):
        source = Path("web_ui/src/stores/appStore.js").read_text(encoding="utf-8")
        self.assertIn("/api/v1/settings/delivery-root", source)
        logout = source[
            source.index("function handleLogout"):source.index("// ── Toast")
        ]
        self.assertNotIn("dopamatrix_output_dir", logout)
        self.assertNotIn("localStorage.setItem('dopamatrix_output_dir'", source)


class DeliveryPathTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = (Path(self.temporary.name) / "delivery").resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def test_tenant_project_render_and_export_contract(self):
        render_a = delivery_output.derive_render_delivery_dir(
            self.root,
            "tenant-a",
            "task-123",
            date(2026, 9, 14),
        )
        render_b = delivery_output.derive_render_delivery_dir(
            self.root,
            "tenant-b",
            "task-123",
            date(2026, 9, 14),
        )
        export_a = delivery_output.derive_export_delivery_dir(
            self.root,
            "tenant-a",
        )
        export_b = delivery_output.derive_export_delivery_dir(
            self.root,
            "tenant-b",
        )
        self.assertNotEqual(render_a, render_b)
        self.assertNotEqual(export_a, export_b)
        self.assertEqual(
            render_a.relative_to(self.root).parts,
            (
                "tenants",
                "tenant-a",
                "projects",
                "_default",
                "renders",
                "2026-09-14",
                "task-123",
            ),
        )
        self.assertEqual(
            export_a.relative_to(self.root).parts,
            ("tenants", "tenant-a", "projects", "_default", "exports"),
        )

    def test_absolute_root_is_required(self):
        with self.assertRaises(delivery_output.DeliveryPathError):
            delivery_output.derive_tenant_delivery_root("relative/root", "tenant-a")

    def test_tenant_injection_and_reserved_segments_are_rejected(self):
        invalid = (
            "../tenant-a",
            "tenant/a",
            "tenant\\a",
            "tenant:a",
            ".",
            "..",
            "CON",
            "NUL",
        )
        for tenant in invalid:
            with self.subTest(tenant=tenant):
                with self.assertRaises(delivery_output.DeliveryPathError):
                    delivery_output.derive_tenant_delivery_root(self.root, tenant)

    def test_derived_paths_are_confined_and_alias_escape_is_rejected(self):
        tenants = self.root / "tenants"
        outside = self.root.parent / "outside"
        tenants.mkdir(parents=True)
        outside.mkdir()
        alias = tenants / "tenant-a"
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(alias), str(outside)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    raise OSError(result.stderr or result.stdout)
            else:
                alias.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"filesystem alias unavailable: {exc}")
        with self.assertRaises(delivery_output.DeliveryPathError):
            delivery_output.derive_tenant_delivery_root(self.root, "tenant-a")


class PostAuthoritativePublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_hook_requires_history_and_assets(self):
        with patch.object(routes_dsl, "publish_render_delivery_assets") as publish:
            routes_dsl._publish_authoritative_delivery_safely(
                history_persisted=False,
                assets=[{"file_path": "output/final_en_a.mp4"}],
                tenant_id="tenant-a",
                task_id="task-a",
            )
            routes_dsl._publish_authoritative_delivery_safely(
                history_persisted=True,
                assets=[],
                tenant_id="tenant-a",
                task_id="task-a",
            )
            publish.assert_not_called()

            assets = [{"file_path": "output/final_en_a.mp4"}]
            routes_dsl._publish_authoritative_delivery_safely(
                history_persisted=True,
                assets=assets,
                tenant_id="tenant-a",
                task_id="task-a",
            )
            publish.assert_called_once_with(
                canonical_tenant="tenant-a",
                task_id="task-a",
                assets=assets,
            )

    def test_authority_terminal_and_off_history_failure_do_not_publish(self):
        with patch.object(routes_dsl, "publish_render_delivery_assets") as publish:
            # First two represent the completed authority-loss/persist-failure
            # wipe branches; the third proves history truth, not files, gates OFF.
            for history_persisted, assets in (
                (False, []),
                (False, []),
                (False, [{"file_path": "output/final_stale.mp4"}]),
            ):
                routes_dsl._publish_authoritative_delivery_safely(
                    history_persisted=history_persisted,
                    assets=assets,
                    tenant_id="tenant-a",
                    task_id="task-a",
                )
            publish.assert_not_called()

    def test_unexpected_hook_failure_is_nonfatal(self):
        with patch.object(
            routes_dsl,
            "publish_render_delivery_assets",
            side_effect=OSError("drive unavailable"),
        ):
            routes_dsl._publish_authoritative_delivery_safely(
                history_persisted=True,
                assets=[{"file_path": "output/final_en_a.mp4"}],
                tenant_id="tenant-a",
                task_id="task-a",
            )

    def test_render_worker_itself_does_not_publish(self):
        source = inspect.getsource(routes_dsl.render_worker)
        self.assertNotIn("publish_render_delivery_assets", source)
        self.assertNotIn("_publish_authoritative_delivery_safely", source)

    def test_publication_hook_is_after_wipe_and_before_terminal_websocket(self):
        source = inspect.getsource(routes_dsl._render_batch_worker_impl)
        wipe_index = source.index("if reservation_authority_lost:")
        publish_index = source.index("_publish_authoritative_delivery_safely(")
        payload_index = source.index("terminal_payload: dict[str, Any]")
        websocket_index = source.index("ws_manager.broadcast_sync(")
        self.assertLess(wipe_index, publish_index)
        self.assertLess(publish_index, payload_index)
        self.assertLess(payload_index, websocket_index)

    def test_only_final_and_deduplicated_cover_are_copied(self):
        delivery_root = self.temp_root / "delivery"
        internal = self.temp_root / "output"
        internal.mkdir()
        final = internal / "final_en_deadbeef.mp4"
        cover = internal / "cover_deadbeef.jpg"
        master = internal / "master_video_deadbeef.mp4"
        voice = internal / "voice_deadbeef.mp3"
        for path, content in (
            (final, b"final"),
            (cover, b"cover"),
            (master, b"master"),
            (voice, b"voice"),
        ):
            path.write_bytes(content)
        with patch.object(
            delivery_output,
            "get_delivery_root",
            return_value=str(delivery_root.resolve()),
        ):
            assets = [
                {
                    "file_path": str(final),
                    "cover_path": str(cover),
                    "master_path": str(master),
                    "voice_path": str(voice),
                },
                {"file_path": str(final), "cover_path": str(cover)},
            ]
            result = delivery_output.publish_render_delivery_assets(
                canonical_tenant="tenant-a",
                task_id="task-a",
                assets=assets,
                render_date=date(2026, 9, 14),
            )
        destination = Path(result.destination)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(
            {path.name for path in destination.iterdir()},
            {final.name, cover.name},
        )
        self.assertEqual((destination / final.name).read_bytes(), b"final")
        self.assertEqual((destination / cover.name).read_bytes(), b"cover")
        self.assertEqual(assets[0]["file_path"], str(final))

    def test_missing_source_and_copy_failure_are_nonfatal(self):
        delivery_root = self.temp_root / "delivery"
        internal = self.temp_root / "output"
        internal.mkdir()
        final = internal / "final_en_deadbeef.mp4"
        final.write_bytes(b"final")
        with (
            patch.object(
                delivery_output,
                "get_delivery_root",
                return_value=str(delivery_root.resolve()),
            ),
            patch.object(
                delivery_output.shutil,
                "copy2",
                Mock(side_effect=OSError("full")),
            ),
        ):
            result = delivery_output.publish_render_delivery_assets(
                canonical_tenant="tenant-a",
                task_id="task-a",
                assets=[
                    {"file_path": str(final)},
                    {"file_path": str(internal / "final_missing.mp4")},
                ],
            )
        self.assertEqual(result.failed_count, 2)
        self.assertEqual(result.copied_paths, ())


class TenantZipTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temporary.name)
        self.runtime_paths = temporary_test_runtime_paths(self.temp_root / "runtime")
        self.runtime_paths.__enter__()

    def tearDown(self):
        self.runtime_paths.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_configured_export_paths_are_tenant_isolated(self):
        delivery_root = self.temp_root / "delivery"
        with patch.object(
            routes_matrix,
            "get_delivery_root",
            return_value=str(delivery_root.resolve()),
        ):
            path_a = routes_matrix._export_directory_for_tenant("tenant-a")
            path_b = routes_matrix._export_directory_for_tenant("tenant-b")
        self.assertNotEqual(path_a, path_b)
        self.assertEqual(
            Path(path_a).relative_to(delivery_root.resolve()).parts,
            ("tenants", "tenant-a", "projects", "_default", "exports"),
        )

    def test_same_second_filenames_do_not_collide(self):
        frozen = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)
        class FrozenDateTime:
            @classmethod
            def now(cls, _timezone):
                return frozen

        with patch.object(routes_matrix, "datetime", FrozenDateTime):
            first = routes_matrix._new_export_filename("tenant-a")
            second = routes_matrix._new_export_filename("tenant-a")
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("dopamatrix_delivery_"))
        self.assertTrue(first.endswith(".zip"))

    def test_export_request_passes_canonical_tenant_and_resolved_directory(self):
        app = FastAPI()
        app.include_router(routes_matrix.router)
        observed = []

        def fake_background(*args):
            observed.append(args)

        with (
            patch.object(
                routes_matrix,
                "_export_directory_for_tenant",
                return_value=str(self.temp_root / "tenant-export"),
            ) as resolve_dir,
            patch.object(routes_matrix, "background_build_zip", fake_background),
        ):
            client = TestClient(app)
            response = client.post(
                "/matrix/export",
                json={"hashes": ["hash-a"]},
                headers={"X-Local-User": "Tenant-A"},
            )
            client.close()

        self.assertEqual(response.status_code, 200)
        canonical_tenant = routes_matrix.request_tenant_id(
            Mock(headers={"X-Local-User": "Tenant-A"})
        )
        resolve_dir.assert_called_once_with(canonical_tenant)
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0][1], canonical_tenant)
        self.assertEqual(observed[0][-1], str(self.temp_root / "tenant-export"))
        self.assertTrue(
            observed[0][2].startswith(
                f"dopamatrix_delivery_{routes_matrix._tenant_export_token(canonical_tenant)}_"
            )
        )

    def test_status_and_download_are_tenant_confined(self):
        delivery_root = self.temp_root / "delivery"
        filename = routes_matrix._new_export_filename("tenant-a")
        export_a = delivery_output.derive_export_delivery_dir(
            delivery_root.resolve(),
            "tenant-a",
        )
        export_a.mkdir(parents=True)
        payload = b"PK tenant-a zip"
        (export_a / filename).write_bytes(payload)

        app = FastAPI()
        app.include_router(routes_matrix.router)
        with patch.object(
            routes_matrix,
            "get_delivery_root",
            return_value=str(delivery_root.resolve()),
        ):
            client = TestClient(app)
            status_a = client.get(
                "/matrix/export/status",
                params={"filename": filename},
                headers={"X-Local-User": "tenant-a"},
            )
            self.assertEqual(status_a.status_code, 200)
            self.assertEqual(status_a.json()["status"], "ready")
            self.assertTrue(
                status_a.json()["download_url"].startswith(
                    "/api/v1/matrix/export/download?filename="
                )
            )

            download_a = client.get(
                "/matrix/export/download",
                params={"filename": filename},
                headers={"X-Local-User": "tenant-a"},
            )
            self.assertEqual(download_a.status_code, 200)
            self.assertEqual(download_a.content, payload)

            for endpoint in (
                "/matrix/export/status",
                "/matrix/export/download",
            ):
                response_b = client.get(
                    endpoint,
                    params={"filename": filename},
                    headers={"X-Local-User": "tenant-b"},
                )
                self.assertEqual(response_b.status_code, 404)
            client.close()

    def test_unset_root_preserves_legacy_export_directory(self):
        legacy = self.temp_root / "runtime" / "output" / "exports"
        with patch.object(routes_matrix, "get_delivery_root", return_value=""):
            resolved = routes_matrix._export_directory_for_tenant("tenant-a")
        self.assertEqual(resolved, str(legacy.resolve()))

    def test_filename_traversal_is_rejected(self):
        invalid = (
            "../dopamatrix_delivery_bad.zip",
            "..\\dopamatrix_delivery_bad.zip",
            "dopamatrix_delivery_bad/evil.zip",
            "dopamatrix_delivery_bad.zip.exe",
            "arbitrary.zip",
        )
        for filename in invalid:
            with self.subTest(filename=filename):
                with self.assertRaises(Exception) as context:
                    routes_matrix._safe_export_filename(filename)
                self.assertEqual(getattr(context.exception, "status_code", None), 400)

    def test_frontend_download_uses_tenant_header_carrying_axios(self):
        source = Path("web_ui/src/App.vue").read_text(encoding="utf-8")
        self.assertIn("axios.get(url, { responseType: 'blob' })", source)
        self.assertIn("URL.createObjectURL", source)
        self.assertIn("URL.revokeObjectURL", source)


class AuthorityBoundaryTests(unittest.TestCase):
    def test_backup_and_compositor_do_not_depend_on_delivery_root(self):
        backup = Path("src/api/backup_restore.py").read_text(encoding="utf-8")
        compositor = Path("src/nodes/compositor.py").read_text(encoding="utf-8")
        self.assertNotIn("delivery_output", backup)
        self.assertNotIn("delivery_root", backup)
        self.assertNotIn("delivery_root", compositor)

    def test_unauthenticated_global_export_static_mount_is_removed(self):
        main_source = Path("main.py").read_text(encoding="utf-8")
        self.assertNotIn('app.mount("/exports"', main_source)
        self.assertNotIn("fastapi.staticfiles", main_source)


if __name__ == "__main__":
    unittest.main()
