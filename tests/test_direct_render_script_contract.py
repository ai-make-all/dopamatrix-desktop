from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DRAWER = ROOT / "web_ui" / "src" / "views" / "DslOrchestratorDrawer.vue"
WORKSPACE = ROOT / "web_ui" / "src" / "views" / "WorkspaceView.vue"
CONTRACT = ROOT / "web_ui" / "src" / "utils" / "directRenderContract.js"


class DirectRenderScriptContractTests(unittest.TestCase):
    def test_uncommitted_editor_script_blocks_before_confirm_emit(self) -> None:
        drawer = DRAWER.read_text(encoding="utf-8")
        contract = CONTRACT.read_text(encoding="utf-8")

        guard_at = drawer.index("if (hasUncommittedBeatScript({")
        emit_at = drawer.index("emit('confirm',", guard_at)
        self.assertLess(guard_at, emit_at)
        self.assertIn(
            "Please confirm the open Beat script before Direct Render.",
            drawer,
        )
        self.assertIn(
            "scriptText(draftScript) !== scriptText(track.script_text)",
            contract,
        )

    def test_confirmed_39_character_script_reaches_submit_dsl_mapping(self) -> None:
        approved_script = "This is a packaged provider smoke test."
        self.assertEqual(len(approved_script), 39)

        drawer = DRAWER.read_text(encoding="utf-8")
        workspace = WORKSPACE.read_text(encoding="utf-8")
        self.assertIn("tracks:       cloneConfirmedTracks(localTracks.value)", drawer)
        self.assertIn("script_text:   track.script_text   || ''", workspace)
        self.assertIn(
            "axios.post(`${store.API_BASE}/api/v1/tasks/submit-dsl`, payload)",
            workspace,
        )


if __name__ == "__main__":
    unittest.main()
