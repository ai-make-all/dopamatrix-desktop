import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const sourcePath = fileURLToPath(new URL('../src/views/SettingsView.vue', import.meta.url))
const source = readFileSync(sourcePath, 'utf8')
const scriptStart = source.indexOf('// ── TTS Settings')
const scriptEnd = source.indexOf('// ── Output dir', scriptStart)
const cardStart = source.indexOf('<!-- TTS 凭据卡', scriptEnd)
const cardEnd = source.indexOf('<!-- 输出目录卡', cardStart)
const ttsScript = source.slice(scriptStart, scriptEnd)
const ttsCard = source.slice(cardStart, cardEnd)

test('TTS settings use the exact external redacted/write-only routes', () => {
  assert.match(ttsScript, /axios\.get\(`\$\{store\.API_BASE\}\/api\/v1\/settings\/tts`\)/)
  assert.match(ttsScript, /axios\.post\(`\$\{store\.API_BASE\}\/api\/v1\/settings\/tts`, \{ api_key: key \}\)/)
  assert.match(ttsScript, /ttsIsConfigured\.value = resp\.data\.is_configured/)
  assert.match(ttsScript, /ttsSecretStatus\.value = resp\.data\.secret_status/)
})

test('TTS key is write-only, cleared after save, and never rendered', () => {
  assert.match(ttsCard, /v-model="ttsApiKeyInput"/)
  assert.match(ttsCard, /type="password"/)
  assert.match(ttsCard, /autocomplete="new-password"/)
  assert.match(ttsScript, /ttsApiKeyInput\.value = ''/)
  assert.doesNotMatch(ttsCard, /\{\{\s*ttsApiKeyInput/)
  assert.doesNotMatch(ttsCard, /showTtsKey/)
})

test('TTS UI is fixed to ElevenLabs and exposes no provider or proxy selector', () => {
  assert.match(ttsCard, /ElevenLabs/)
  assert.doesNotMatch(ttsCard, /<select/)
  assert.doesNotMatch(ttsCard, /<option/)
  assert.doesNotMatch(ttsCard, /v-model="[^"]*(provider|voice|proxy)/i)
  assert.doesNotMatch(ttsCard, /@change="[^"]*(provider|voice|proxy)/i)
})
