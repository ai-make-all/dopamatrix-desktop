from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://tauri.localhost"


def _safe_subprocess_environment(temp_root: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not (
            key.startswith("RESERVATION_")
            or key.endswith("_SECRET")
            or key.endswith("_TOKEN")
            or key.endswith("_API_KEY")
        )
    }
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT)
    environment["LOCALAPPDATA"] = str(temp_root / "local-app-data")
    environment["APPDATA"] = str(temp_root / "roaming-app-data")
    return environment


def _run_application_probe(temp_root: Path) -> subprocess.CompletedProcess[str]:
    probe = textwrap.dedent(
        f"""
        import json
        import sys
        from pathlib import Path
        from unittest.mock import patch

        from fastapi import HTTPException
        from fastapi.responses import JSONResponse
        from fastapi.testclient import TestClient
        from src.api.bootstrap import BootstrapDecision
        from src.api.runtime_paths import RuntimeMode, RuntimePaths

        base = Path({str(temp_root)!r})
        packaged = RuntimePaths(
            mode=RuntimeMode.PACKAGED,
            runtime_root=base / "runtime",
            settings_db_path=base / "runtime" / "dopamatrix.db",
            tenant_data_dir=base / "runtime" / "data",
            internal_output_root=base / "runtime" / "output",
        )

        sys.argv = ["r5-cors-error-exposure-probe"]
        with (
            patch.object(sys, "frozen", True, create=True),
            patch(
                "src.api.bootstrap.prepare_bootstrap",
                return_value=BootstrapDecision(packaged, False),
            ),
            patch("src.api.bootstrap.apply_server_compatibility_cwd"),
            patch("src.api.runtime_mutation.acquire_server_runtime_mutation_barrier"),
            patch("src.api.runtime_mutation.release_server_runtime_mutation_barrier"),
            patch("appdirs.user_log_dir", return_value=str(base / "logs")),
        ):
            import main

        @main.app.get("/__r5/success")
        async def success_probe():
            return {{"ok": True}}

        @main.app.get("/__r5/explicit-500")
        async def explicit_500_probe():
            return JSONResponse(
                status_code=500,
                content={{"detail": "EXPLICIT_CONTROL"}},
            )

        @main.app.get("/__r5/runtime-error")
        async def runtime_error_probe():
            raise RuntimeError("SENSITIVE_TEST_SENTINEL")

        @main.app.get("/__r5/value-error")
        async def value_error_probe():
            raise ValueError("SENSITIVE_VALUE_SENTINEL")

        @main.app.get("/__r5/http-exception")
        async def http_exception_probe():
            raise HTTPException(status_code=418, detail="HTTP_CONTROL")

        @main.app.post("/__r5/known-safe-error")
        async def known_safe_error_probe():
            raise RuntimeError("OPENAI_PROVIDER_REQUEST_FAILED")

        @main.app.post("/__r5/unknown-sensitive-error")
        async def unknown_sensitive_error_probe():
            raise RuntimeError("SUPER_SECRET_DIAGNOSTIC_SENTINEL")

        client = TestClient(main.app, raise_server_exceptions=False)
        origin_headers = {{"Origin": {ORIGIN!r}}}

        options = client.options(
            "/__r5/success",
            headers={{
                "Origin": {ORIGIN!r},
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-local-user",
            }},
        )
        success = client.get("/__r5/success", headers=origin_headers)
        explicit_500 = client.get("/__r5/explicit-500", headers=origin_headers)
        runtime_error = client.get("/__r5/runtime-error", headers=origin_headers)
        value_error = client.get("/__r5/value-error", headers=origin_headers)
        http_exception = client.get("/__r5/http-exception", headers=origin_headers)
        tenant_control = client.get(
            "/health",
            headers={{"Origin": {ORIGIN!r}, "X-Local-User": "ph-elv-0002"}},
        )

        sensitive_headers = {{
            "Origin": {ORIGIN!r},
            "Authorization": "Bearer AUTHORIZATION_TEST_SENTINEL",
            "X-Api-Key": "API_KEY_TEST_SENTINEL",
        }}
        sensitive_body = {{"prompt": "REQUEST_BODY_TEST_SENTINEL"}}
        with patch.object(main, "logger") as known_logger:
            known_safe_error = client.post(
                "/__r5/known-safe-error?query=QUERY_STRING_TEST_SENTINEL",
                headers=sensitive_headers,
                json=sensitive_body,
            )
            known_log_call_count = known_logger.error.call_count
            known_call = known_logger.error.call_args
            known_log = known_call.args[0].format(*known_call.args[1:])

        with patch.object(main, "logger") as unknown_logger:
            unknown_sensitive_error = client.post(
                "/__r5/unknown-sensitive-error?query=QUERY_STRING_TEST_SENTINEL",
                headers=sensitive_headers,
                json=sensitive_body,
            )
            unknown_log_call_count = unknown_logger.error.call_count
            unknown_call = unknown_logger.error.call_args
            unknown_log = unknown_call.args[0].format(*unknown_call.args[1:])

        with patch.object(main, "logger") as failing_logger:
            failing_logger.error.side_effect = RuntimeError("LOGGER_FAILURE_SENTINEL")
            logging_failure = client.post(
                "/__r5/unknown-sensitive-error",
                headers=origin_headers,
                json={{}},
            )

        with patch.object(
            main.routes_dsl.DirectorNode,
            "draft_blueprint",
            side_effect=RuntimeError("SENSITIVE_DRAFT_SENTINEL"),
        ) as draft_blueprint:
            draft = client.post(
                "/api/v1/tasks/draft-blueprint",
                headers=origin_headers,
                json={{
                    "prompt": "safe structural test",
                    "mode": "auto",
                    "duration": 15,
                    "langs": ["en"],
                    "available_tags": ["safe-tag"],
                    "user_hard_tags": [],
                }},
            )
            draft_call_count = draft_blueprint.call_count

        def observed_response(response):
            return {{
                "status": response.status_code,
                "body": response.text,
                "allow_origin": response.headers.get("access-control-allow-origin"),
                "allow_methods": response.headers.get("access-control-allow-methods"),
                "allow_headers": response.headers.get("access-control-allow-headers"),
                "allow_credentials": response.headers.get("access-control-allow-credentials"),
            }}

        user_middleware = [
            middleware.cls.__name__ for middleware in main.app.user_middleware
        ]
        stack = []
        current = main.app.middleware_stack
        while current is not None and len(stack) < 16:
            stack.append(type(current).__name__)
            current = getattr(current, "app", None)

        print(json.dumps({{
            "options": observed_response(options),
            "success": observed_response(success),
            "explicit_500": observed_response(explicit_500),
            "runtime_error": observed_response(runtime_error),
            "value_error": observed_response(value_error),
            "http_exception": observed_response(http_exception),
            "tenant_control": observed_response(tenant_control),
            "known_safe_error": observed_response(known_safe_error),
            "known_log_call_count": known_log_call_count,
            "known_log": known_log,
            "unknown_sensitive_error": observed_response(unknown_sensitive_error),
            "unknown_log_call_count": unknown_log_call_count,
            "unknown_log": unknown_log,
            "logging_failure": observed_response(logging_failure),
            "draft": observed_response(draft),
            "draft_call_count": draft_call_count,
            "user_middleware": user_middleware,
            "effective_stack": stack,
            "fence_owner_count": user_middleware.count("UnhandledErrorFence"),
        }}))
        """
    )
    return subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPOSITORY_ROOT,
        env=_safe_subprocess_environment(temp_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )


class CorsErrorExposureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._temporary_directory.cleanup)
        result = _run_application_probe(Path(cls._temporary_directory.name))
        if result.returncode != 0:
            raise AssertionError(result.stderr or result.stdout)
        cls.observed = json.loads(result.stdout.strip().splitlines()[-1])

    def assert_cors_visible(self, case: str) -> None:
        self.assertEqual(self.observed[case]["allow_origin"], ORIGIN)
        self.assertEqual(self.observed[case]["allow_credentials"], "true")

    def test_options_preflight_remains_cors_visible(self):
        response = self.observed["options"]
        self.assertEqual(response["status"], 200)
        self.assert_cors_visible("options")
        self.assertIn("POST", response["allow_methods"])
        self.assertEqual(response["allow_headers"], "content-type,x-local-user")

    def test_success_response_remains_cors_visible(self):
        self.assertEqual(self.observed["success"]["status"], 200)
        self.assert_cors_visible("success")

    def test_explicit_500_response_remains_cors_visible(self):
        self.assertEqual(self.observed["explicit_500"]["status"], 500)
        self.assert_cors_visible("explicit_500")
        self.assertIn("EXPLICIT_CONTROL", self.observed["explicit_500"]["body"])

    def test_unhandled_runtime_error_is_generic_and_cors_visible(self):
        response = self.observed["runtime_error"]
        self.assertEqual(response["status"], 500)
        self.assert_cors_visible("runtime_error")
        self.assertEqual(response["body"], '{"detail":"INTERNAL_SERVER_ERROR"}')
        self.assertNotIn("SENSITIVE_TEST_SENTINEL", response["body"])

    def test_unhandled_value_error_is_generic_and_cors_visible(self):
        response = self.observed["value_error"]
        self.assertEqual(response["status"], 500)
        self.assert_cors_visible("value_error")
        self.assertEqual(response["body"], '{"detail":"INTERNAL_SERVER_ERROR"}')
        self.assertNotIn("SENSITIVE_VALUE_SENTINEL", response["body"])

    def test_http_exception_semantics_remain_cors_visible(self):
        response = self.observed["http_exception"]
        self.assertEqual(response["status"], 418)
        self.assert_cors_visible("http_exception")
        self.assertEqual(json.loads(response["body"]), {"detail": "HTTP_CONTROL"})

    def test_tenant_authority_still_rejects_before_route_execution(self):
        response = self.observed["tenant_control"]
        self.assertEqual(response["status"], 403)
        self.assert_cors_visible("tenant_control")
        self.assertEqual(json.loads(response["body"]), {"detail": "TENANT_NOT_APPROVED"})

    def test_known_safe_token_is_logged_once_without_request_secrets(self):
        response = self.observed["known_safe_error"]
        event = self.observed["known_log"]
        self.assertEqual(response["status"], 500)
        self.assert_cors_visible("known_safe_error")
        self.assertEqual(response["body"], '{"detail":"INTERNAL_SERVER_ERROR"}')
        self.assertEqual(self.observed["known_log_call_count"], 1)
        self.assertIn("UNHANDLED_REQUEST_EXCEPTION", event)
        self.assertIn("method=POST", event)
        self.assertIn("path=/__r5/known-safe-error", event)
        self.assertIn("exception_type=RuntimeError", event)
        self.assertIn("error_code=OPENAI_PROVIDER_REQUEST_FAILED", event)
        self.assertNotIn("QUERY_STRING_TEST_SENTINEL", event)
        self.assertNotIn("REQUEST_BODY_TEST_SENTINEL", event)
        self.assertNotIn("AUTHORIZATION_TEST_SENTINEL", event)
        self.assertNotIn("API_KEY_TEST_SENTINEL", event)

    def test_unknown_sensitive_message_is_redacted_to_unclassified(self):
        response = self.observed["unknown_sensitive_error"]
        event = self.observed["unknown_log"]
        self.assertEqual(response["status"], 500)
        self.assert_cors_visible("unknown_sensitive_error")
        self.assertEqual(response["body"], '{"detail":"INTERNAL_SERVER_ERROR"}')
        self.assertEqual(self.observed["unknown_log_call_count"], 1)
        self.assertIn("UNHANDLED_REQUEST_EXCEPTION", event)
        self.assertIn("method=POST", event)
        self.assertIn("path=/__r5/unknown-sensitive-error", event)
        self.assertIn("exception_type=RuntimeError", event)
        self.assertIn("error_code=UNCLASSIFIED", event)
        self.assertNotIn("SUPER_SECRET_DIAGNOSTIC_SENTINEL", event)
        self.assertNotIn("QUERY_STRING_TEST_SENTINEL", event)
        self.assertNotIn("REQUEST_BODY_TEST_SENTINEL", event)
        self.assertNotIn("AUTHORIZATION_TEST_SENTINEL", event)
        self.assertNotIn("API_KEY_TEST_SENTINEL", event)

    def test_logging_failure_does_not_change_generic_response(self):
        response = self.observed["logging_failure"]
        self.assertEqual(response["status"], 500)
        self.assert_cors_visible("logging_failure")
        self.assertEqual(response["body"], '{"detail":"INTERNAL_SERVER_ERROR"}')

    def test_effective_middleware_order_has_one_fence_inside_cors(self):
        self.assertEqual(
            self.observed["user_middleware"],
            [
                "CORSMiddleware",
                "UnhandledErrorFence",
                "TenantHeaderAuthorityMiddleware",
            ],
        )
        self.assertEqual(self.observed["fence_owner_count"], 1)
        self.assertEqual(
            self.observed["effective_stack"][:6],
            [
                "ServerErrorMiddleware",
                "CORSMiddleware",
                "UnhandledErrorFence",
                "TenantHeaderAuthorityMiddleware",
                "ExceptionMiddleware",
                "AsyncExitStackMiddleware",
            ],
        )

    def test_draft_unhandled_error_is_a_cors_visible_generic_500(self):
        response = self.observed["draft"]
        self.assertEqual(self.observed["draft_call_count"], 1)
        self.assertEqual(response["status"], 500)
        self.assert_cors_visible("draft")
        self.assertEqual(response["body"], '{"detail":"INTERNAL_SERVER_ERROR"}')
        self.assertNotIn("SENSITIVE_DRAFT_SENTINEL", response["body"])


if __name__ == "__main__":
    unittest.main()
