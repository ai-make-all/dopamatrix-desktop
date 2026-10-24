import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import {
  cloneConfirmedTracks,
  hasUncommittedBeatScript,
} from '../src/utils/directRenderContract.js'

const approvedScript = 'This is a packaged provider smoke test.'
const drawerPath = fileURLToPath(new URL('../src/views/DslOrchestratorDrawer.vue', import.meta.url))
const workspacePath = fileURLToPath(new URL('../src/views/WorkspaceView.vue', import.meta.url))
const drawer = readFileSync(drawerPath, 'utf8')
const workspace = readFileSync(workspacePath, 'utf8')

test('Direct Render blocks an uncommitted Beat script', () => {
  const tracks = [{ id: 'Hook', script_text: 'AI draft text' }]
  assert.equal(hasUncommittedBeatScript({
    activeBeatIndex: 0,
    tracks,
    draftScript: approvedScript,
  }), true)
  assert.match(drawer, /hasUncommittedBeatScript\(/)
  assert.match(drawer, /Please confirm the open Beat script before Direct Render\./)
})

test('confirmed 39-character script survives the Direct Render snapshot', () => {
  assert.equal(approvedScript.length, 39)
  const tracks = [{ id: 'Hook', script_text: approvedScript }]
  assert.equal(hasUncommittedBeatScript({
    activeBeatIndex: 0,
    tracks,
    draftScript: approvedScript,
  }), false)

  const snapshot = cloneConfirmedTracks(tracks)
  assert.equal(snapshot[0].script_text, approvedScript)
  assert.match(drawer, /tracks:\s+cloneConfirmedTracks\(localTracks\.value\)/)
  assert.match(workspace, /script_text:\s+track\.script_text\s+\|\|\s+''/)
  assert.match(workspace, /axios\.post\(`\$\{store\.API_BASE\}\/api\/v1\/tasks\/submit-dsl`, payload\)/)
})
