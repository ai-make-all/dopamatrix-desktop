function scriptText(value) {
  return typeof value === 'string' ? value : ''
}

export function hasUncommittedBeatScript({ activeBeatIndex, tracks, draftScript }) {
  if (!Number.isInteger(activeBeatIndex) || activeBeatIndex < 0) return false
  const track = Array.isArray(tracks) ? tracks[activeBeatIndex] : null
  if (!track) return true
  return scriptText(draftScript) !== scriptText(track.script_text)
}

export function cloneConfirmedTracks(tracks) {
  return JSON.parse(JSON.stringify(Array.isArray(tracks) ? tracks : []))
}
