// ── DopaMatrix SSOT: 全局资产配置唯一真相源 ─────────────────────────
// 所有组件的资产类型、分面命名空间、颜色、DSL层级均从此处读取，禁止在组件内重复定义。

/** 全局分面命名空间（打标桶的标准枚举，与 DAM 解析层对齐） */
export const FACET_NAMESPACES = [
  { value: 'hook',    label: '⚓ 剧情钩子 (Hook)',    color: 'purple' },
  { value: 'entity',  label: '👁️ 视觉实体 (Entity)',  color: 'emerald' },
  { value: 'vibe',    label: '✨ 氛围情绪 (Vibe)',    color: 'sky' },
  { value: 'vfx',     label: '💥 视觉特效 (VFX)',     color: 'amber' },
  { value: 'sfx',     label: '🎵 音效配乐 (SFX)',     color: 'orange' },
  { value: 'context', label: '💡 核心卖点 (Context)', color: 'blue' },
  { value: 'build',   label: '📈 剧情推进 (Build)',   color: 'indigo' },
  { value: 'cta',     label: '🔥 行动号召 (CTA)',     color: 'rose' },
]

/** 全局物料物理属性注册表（接管文件后缀、物理层级、DSL 映射） */
export const ASSET_REGISTRY = {
  video:         { label: '视频骨料',    icon: '🎬', axis_type: 'X',           color: '#3b82f6', facet_prefix: ['hook', 'context', 'build', 'cta', 'entity', 'vibe'], dsl_layer: 'main_v_track', is_container: false, extensions: ['mp4', 'mov'] },
  image:         { label: '静态画面',    icon: '🖼️', axis_type: 'X',           color: '#10b981', facet_prefix: ['entity', 'context'],                                  dsl_layer: 'main_v_track', is_container: false, extensions: ['png', 'jpg', 'jpeg', 'webp'] },
  audio_bgm:     { label: '听觉配乐',    icon: '🎼', axis_type: 'Y',           color: '#f59e0b', facet_prefix: ['vibe'],                                               dsl_layer: 'AudioTrack',   is_container: false, extensions: ['mp3', 'wav', 'aac'] },
  vfx:           { label: '视觉特效层',  icon: '✨', axis_type: 'Y',           color: '#fbbf24', facet_prefix: ['vfx'],                                                dsl_layer: 'overlay',      is_container: false, extensions: ['png', 'gif', 'webp'] },
  sfx:           { label: '音效层',      icon: '⚡', axis_type: 'Y',           color: '#f97316', facet_prefix: ['sfx'],                                                dsl_layer: 'AudioTrack',   is_container: false, extensions: ['mp3', 'wav'] },
  scene_master:  { label: '场景底模',    icon: '🏛️', axis_type: 'X_STRUCTURE', color: '#ec4899', facet_prefix: ['slot', 'vibe'],                                       dsl_layer: 'SceneMaster',  is_container: true,  extensions: ['mp4', 'mov', 'png', 'jpg', 'jpeg'] },
  text_template: { label: '文本动态资产', icon: '📝', axis_type: 'Y',           color: '#8b5cf6', facet_prefix: ['hook', 'context', 'build', 'cta', 'vibe', 'entity'],  dsl_layer: 'TextOverlay',  is_container: false, extensions: [] },
}

/** 供前端资产库过滤器使用的数组（含"全部"入口） */
export const ASSET_FILTER_OPTIONS = [
  { type: 'all', label: '全部', icon: '📦' },
  ...Object.entries(ASSET_REGISTRY).map(([k, v]) => ({ type: k, label: v.label, icon: v.icon })),
]
