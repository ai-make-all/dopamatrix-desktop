/**
 * DopaMatrix DAM / DSL — 分面标签解析（单一真相源）
 * raw tag 形如 hook:残血反杀 → 分组展示与胶囊样式类名
 */

const FACET_HEAD = {
  hook: '⚓ HOOK',
  entity: '👁 ENTITY',
  vibe: '✨ VIBE',
  vfx: '💥 VFX',
  sfx: '🎵 SFX',
}

const KNOWN_PREFIXES = new Set(['hook', 'entity', 'vibe', 'vfx', 'sfx'])

/**
 * 将扁平 tags[] 按 `prefix:value` 分桶，供 DAM 分面矩阵等使用。
 * @param {string[]} tags
 * @returns {Array<{ key: string, label: string|null, icon: string|null, theme: string, values: { display: string, raw: string }[] }>}
 */
export function parseFacetedTags(tags = []) {
  const buckets = {
    hook:    { key: 'hook',    label: 'Hook',   icon: '⚓', theme: 'hook',    values: [] },
    entity:  { key: 'entity',  label: 'Entity', icon: '👁', theme: 'entity',  values: [] },
    vibe:    { key: 'vibe',    label: 'Vibe',   icon: '✨', theme: 'vibe',    values: [] },
    vfx:     { key: 'vfx',     label: 'VFX',    icon: '💥', theme: 'vfx',     values: [] },
    sfx:     { key: 'sfx',     label: 'SFX',    icon: '🎵', theme: 'sfx',     values: [] },
    generic: { key: 'generic', label: null,     icon: null, theme: 'generic', values: [] },
  }
  for (const tag of tags) {
    const colonIdx = tag.indexOf(':')
    if (colonIdx === -1) {
      buckets.generic.values.push({ display: tag, raw: tag })
      continue
    }
    const prefix = tag.slice(0, colonIdx).toLowerCase()
    const value = tag.slice(colonIdx + 1)
    if (prefix === 'hook') buckets.hook.values.push({ display: value, raw: tag })
    else if (prefix === 'entity') buckets.entity.values.push({ display: value, raw: tag })
    else if (prefix === 'vibe') buckets.vibe.values.push({ display: value, raw: tag })
    else if (prefix === 'vfx') buckets.vfx.values.push({ display: value, raw: tag })
    else if (prefix === 'sfx') buckets.sfx.values.push({ display: value, raw: tag })
    else buckets.generic.values.push({ display: tag, raw: tag })
  }
  return Object.values(buckets).filter(b => b.values.length > 0)
}

/**
 * Data Grid 等窄列：平铺 facet pills 并限制数量
 */
export function getVisiblePills(tags, maxVisible = 5) {
  const pills = []
  for (const group of parseFacetedTags(tags || [])) {
    for (const v of group.values) pills.push({ display: v.display, raw: v.raw, theme: group.theme })
  }
  return { visible: pills.slice(0, maxVisible), overflow: Math.max(0, pills.length - maxVisible) }
}

/**
 * 单条 raw 标签 → 胶囊展示片段（战术板 / 过滤器等）
 * @returns {{ facetClass: string, head: string, val: string, showHead: boolean }}
 */
export function getTagPillParts(raw) {
  if (raw == null || typeof raw !== 'string') {
    return { facetClass: 'facet-generic', head: '', val: '', showHead: false }
  }
  const ci = raw.indexOf(':')
  if (ci === -1) {
    return { facetClass: 'facet-generic', head: '', val: raw, showHead: false }
  }
  const prefix = raw.slice(0, ci).toLowerCase()
  const val = raw.slice(ci + 1)
  const facetClass = KNOWN_PREFIXES.has(prefix) ? `facet-${prefix}` : 'facet-generic'
  const head = FACET_HEAD[prefix] || `${prefix.toUpperCase()}`
  return { facetClass, head, val, showHead: true }
}
