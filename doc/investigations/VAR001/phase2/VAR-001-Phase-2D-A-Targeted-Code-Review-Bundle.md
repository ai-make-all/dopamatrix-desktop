# VAR-001 Phase 2D-A Targeted Code Review Bundle

## A. Git Status

```text
 M web_ui/src/views/QueueView.vue
?? web_ui/src/components/CoverageDiagnosticsPanel.vue
?? web_ui/src/utils/coveragePresentation.ts
?? web_ui/tests/coveragePresentation.test.mjs
```

`git diff --stat` only统计已跟踪文件：

```text
web_ui/src/views/QueueView.vue | 116 +++++++++++++++++++++++++++--------------
1 file changed, 76 insertions(+), 40 deletions(-)
```

## B. QueueView Diff

完整当前 diff：

```diff
diff --git a/web_ui/src/views/QueueView.vue b/web_ui/src/views/QueueView.vue
index f55bed9..a4afac6 100644
--- a/web_ui/src/views/QueueView.vue
+++ b/web_ui/src/views/QueueView.vue
@@ -22,6 +22,7 @@ import {
 } from '../utils/coverageDiagnostics'
 import MasterPreviewModal from '../components/MasterPreviewModal.vue'
 import CoverPreviewCard   from '../components/matrix/CoverPreviewCard.vue'
+import CoverageDiagnosticsPanel from '../components/CoverageDiagnosticsPanel.vue'

 const queueStore = useQueueStore()
 const appStore   = useAppStore()
@@ -217,6 +218,12 @@ function togglePrompt(id: string) {
   else expandedPrompts.add(id)
 }

+const expandedCoveragePanels = reactive<Set<string>>(new Set())
+function setCoveragePanelExpanded(id: string, open: boolean) {
+  if (open) expandedCoveragePanels.add(id)
+  else expandedCoveragePanels.delete(id)
+}
+
 const expandedAssetTitles = reactive<Set<string>>(new Set())

 function assetTitleKey(task: QueueTask, asset: QueueTaskAsset, localIdx: number): string {
@@ -521,47 +528,59 @@ const triggerRealWsFlood = async () => {
         <p>流水线空闲，前往工作台创建矩阵任务</p>
       </div>

-      <!-- item-size = strip(52px) + margin-bottom(8px) = 60 -->
-      <RecycleScroller
+      <DynamicScroller
         v-else
         class="task-scroller"
         :items="processingTasks"
-        :item-size="60"
+        :min-item-size="60"
         :prerender="14"
         key-field="id"
-        v-slot="{ item }"
+        v-slot="{ item, active }"
       >
-        <!-- 极简监控条：零 <video>/<img>，~8 DOM 节点 -->
-        <div :class="['monitor-strip', `monitor-strip--${item.type}`]">
-
-          <div class="ms-left">
-            <span :class="['ms-pulse', { 'ms-pulse--running': item.type === 'running' }]" />
-            <span class="ms-id">#{{ item.id.slice(-8) }}</span>
-            <span :class="['ms-badge', statusClass(item.type)]">{{ statusLabel(item.type) }}</span>
-          </div>
+        <DynamicScrollerItem
+          :item="item"
+          :active="active"
+          :size-dependencies="[expandedCoveragePanels.has(item.id)]"
+        >
+          <div class="monitor-entry">
+            <!-- 极简监控条：零 <video>/<img>，~8 DOM 节点 -->
+            <div :class="['monitor-strip', `monitor-strip--${item.type}`]">
+
+              <div class="ms-left">
+                <span :class="['ms-pulse', { 'ms-pulse--running': item.type === 'running' }]" />
+                <span class="ms-id">#{{ item.id.slice(-8) }}</span>
+                <span :class="['ms-badge', statusClass(item.type)]">{{ statusLabel(item.type) }}</span>
+              </div>

-          <p
-            class="ms-prompt"
-            :class="{ 'ms-prompt--warning': !!getOutcomeSummary(item) }"
-            :title="getOutcomeSummary(item)?.text || item.prompt || ''"
-          >{{ getOutcomeSummary(item)?.text || item.prompt || '（无描述）' }}</p>
+              <p
+                class="ms-prompt"
+                :class="{ 'ms-prompt--warning': !!getOutcomeSummary(item) }"
+                :title="getOutcomeSummary(item)?.text || item.prompt || ''"
+              >{{ getOutcomeSummary(item)?.text || item.prompt || '（无描述）' }}</p>

-          <div class="ms-right">
-            <template v-if="item.type === 'running'">
-              <div class="ms-bar" aria-hidden="true">
-                <div class="ms-bar-fill" />
+              <div class="ms-right">
+                <template v-if="item.type === 'running'">
+                  <div class="ms-bar" aria-hidden="true">
+                    <div class="ms-bar-fill" />
+                  </div>
+                  <svg class="ms-spin" fill="none" viewBox="0 0 24 24" width="14" height="14">
+                    <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" opacity="0.25"/>
+                    <path fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" opacity="0.8"/>
+                  </svg>
+                </template>
+                <span v-else-if="item.type === 'failed'" class="ms-fail-tag">✕ 错误</span>
+                <span v-else class="ms-ts">{{ item.startTs || '--' }}</span>
               </div>
-              <svg class="ms-spin" fill="none" viewBox="0 0 24 24" width="14" height="14">
-                <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" opacity="0.25"/>
-                <path fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" opacity="0.8"/>
-              </svg>
-            </template>
-            <span v-else-if="item.type === 'failed'" class="ms-fail-tag">✕ 错误</span>
-            <span v-else class="ms-ts">{{ item.startTs || '--' }}</span>
-          </div>

-        </div>
-      </RecycleScroller>
+            </div>
+            <CoverageDiagnosticsPanel
+              v-if="item.coverageDiagnostics"
+              :diagnostics="item.coverageDiagnostics"
+              @toggle="setCoveragePanelExpanded(item.id, $event)"
+            />
+          </div>
+        </DynamicScrollerItem>
+      </DynamicScroller>

     </section>

@@ -573,18 +592,26 @@ const triggerRealWsFlood = async () => {
         <p>暂无完成成果，等待流水线产出战果</p>
       </div>

-      <!-- item-size = card(258px) + margin-bottom(12px) = 270 -->
-      <RecycleScroller
+      <DynamicScroller
         v-else
         class="task-scroller"
         :items="completedTasks"
-        :item-size="270"
+        :min-item-size="270"
         :prerender="8"
         key-field="id"
-        v-slot="{ item }"
+        v-slot="{ item, active }"
       >
-        <!-- ── Phase 7 完整三行式卡片 ── -->
-        <div class="task-card task-card--completed">
+        <DynamicScrollerItem
+          :item="item"
+          :active="active"
+          :size-dependencies="[
+            expandedCoveragePanels.has(item.id),
+            expandedPrompts.has(item.id),
+            expandedAssetTitles.size,
+          ]"
+        >
+          <!-- ── Phase 7 完整三行式卡片 ── -->
+          <div class="task-card task-card--completed">

           <!-- ══ ROW 1: 元数据 ══ -->
           <div class="row-meta">
@@ -638,6 +665,12 @@ const triggerRealWsFlood = async () => {
             </button>
           </div>

+          <CoverageDiagnosticsPanel
+            v-if="item.coverageDiagnostics"
+            :diagnostics="item.coverageDiagnostics"
+            @toggle="setCoveragePanelExpanded(item.id, $event)"
+          />
+
           <!-- ══ ROW 3: 资产轮播（1:1 强制比例横向轮播）══ -->
           <template v-if="item.assets?.length">
             <div
@@ -760,8 +793,9 @@ const triggerRealWsFlood = async () => {
             <div class="row-empty" />
           </template>

-        </div>
-      </RecycleScroller>
+          </div>
+        </DynamicScrollerItem>
+      </DynamicScroller>

     </section>

@@ -1011,6 +1045,7 @@ const triggerRealWsFlood = async () => {
   text-overflow: ellipsis;
   margin:        0;
 }
+.monitor-entry { min-width: 0; }
 .ms-prompt--warning {
   color: #fbbf24;
   font-weight: 600;
@@ -1076,7 +1111,8 @@ const triggerRealWsFlood = async () => {
    高度：220px + margin-bottom 12px = 232px（匹配 RecycleScroller item-size）
 ══════════════════════════════════════════════════════════════════════════ */
 .task-card {
-  height:         258px;
+  min-height:     258px;
+  height:         auto;
   box-sizing:     border-box;
   margin-bottom:  12px;
   padding:        0.6rem 0.85rem 0.5rem;
```

QueueView 没有本地导入 `DynamicScroller`。它通过 Phase 2D 前已经存在的全局注册获得：

```js
import VueVirtualScroller from 'vue-virtual-scroller'
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'

app.use(VueVirtualScroller)
```

## C. DynamicScroller Integration

两个列表的完整当前模板区域：

```vue
<section v-if="activeTab === 'processing'" class="task-scroll-area">
  <div v-if="processingTasks.length === 0" class="empty-state">
    <div class="empty-icon">⚡</div>
    <p>流水线空闲，前往工作台创建矩阵任务</p>
  </div>

  <DynamicScroller
    v-else
    class="task-scroller"
    :items="processingTasks"
    :min-item-size="60"
    :prerender="14"
    key-field="id"
    v-slot="{ item, active }"
  >
    <DynamicScrollerItem
      :item="item"
      :active="active"
      :size-dependencies="[expandedCoveragePanels.has(item.id)]"
    >
      <div class="monitor-entry">
        <div :class="['monitor-strip', `monitor-strip--${item.type}`]">
          <div class="ms-left">
            <span :class="['ms-pulse', { 'ms-pulse--running': item.type === 'running' }]" />
            <span class="ms-id">#{{ item.id.slice(-8) }}</span>
            <span :class="['ms-badge', statusClass(item.type)]">
              {{ statusLabel(item.type) }}
            </span>
          </div>

          <p
            class="ms-prompt"
            :class="{ 'ms-prompt--warning': !!getOutcomeSummary(item) }"
            :title="getOutcomeSummary(item)?.text || item.prompt || ''"
          >{{ getOutcomeSummary(item)?.text || item.prompt || '（无描述）' }}</p>

          <div class="ms-right">
            <template v-if="item.type === 'running'">
              <div class="ms-bar" aria-hidden="true">
                <div class="ms-bar-fill" />
              </div>
              <svg class="ms-spin" fill="none" viewBox="0 0 24 24" width="14" height="14">
                <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" opacity="0.25"/>
                <path fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" opacity="0.8"/>
              </svg>
            </template>
            <span v-else-if="item.type === 'failed'" class="ms-fail-tag">✕ 错误</span>
            <span v-else class="ms-ts">{{ item.startTs || '--' }}</span>
          </div>
        </div>

        <CoverageDiagnosticsPanel
          v-if="item.coverageDiagnostics"
          :diagnostics="item.coverageDiagnostics"
          @toggle="setCoveragePanelExpanded(item.id, $event)"
        />
      </div>
    </DynamicScrollerItem>
  </DynamicScroller>
</section>

<section v-else class="task-scroll-area">
  <div v-if="completedTasks.length === 0" class="empty-state">
    <div class="empty-icon">🏆</div>
    <p>暂无完成成果，等待流水线产出战果</p>
  </div>

  <DynamicScroller
    v-else
    class="task-scroller"
    :items="completedTasks"
    :min-item-size="270"
    :prerender="8"
    key-field="id"
    v-slot="{ item, active }"
  >
    <DynamicScrollerItem
      :item="item"
      :active="active"
      :size-dependencies="[
        expandedCoveragePanels.has(item.id),
        expandedPrompts.has(item.id),
        expandedAssetTitles.size,
      ]"
    >
      <div class="task-card task-card--completed">
        <div class="row-meta">
          <div class="meta-left">
            <span class="meta-task-id">#{{ item.id.slice(-8) }}</span>
            <span v-if="item.assets?.length" class="meta-batch">
              包含 {{ item.assets.length }} 个视频
            </span>
            <span :class="['mode-badge', getModeClass(item)]">
              {{ getModeLabel(item) }}
            </span>
            <span
              :class="[
                'status-badge',
                getOutcomeSummary(item) ? 'badge-outcome-warning' : 'badge-completed',
              ]"
            >{{ completedStatusLabel(item) }}</span>
          </div>
          <div class="meta-right">
            <span v-if="item.startTs" class="meta-time">
              {{ item.startTs }}<template v-if="item.endTs"> → {{ item.endTs }}</template>
            </span>
            <span v-if="item.duration" class="meta-duration">{{ item.duration }}</span>
          </div>
        </div>

        <div
          v-if="getOutcomeSummary(item)"
          class="row-outcome-warning"
          :class="`row-outcome-warning--${getOutcomeSummary(item)?.severity}`"
          :title="getOutcomeSummary(item)?.text"
        >
          {{ getOutcomeSummary(item)?.text }}
        </div>
        <div
          v-else
          class="row-prompt"
          :class="{ 'row-prompt--expanded': expandedPrompts.has(item.id) }"
        >
          <p class="prompt-text" :class="{ 'prompt-text--clamp': !expandedPrompts.has(item.id) }">
            {{ item.prompt || '（无描述）' }}
          </p>
          <button
            v-if="(item.prompt?.length ?? 0) > 60"
            class="prompt-toggle"
            @click.stop="togglePrompt(item.id)"
            :aria-label="expandedPrompts.has(item.id) ? '折叠' : '展开'"
          >
            <svg
              class="toggle-arrow"
              :class="{ 'toggle-arrow--up': expandedPrompts.has(item.id) }"
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2.5"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </button>
        </div>

        <CoverageDiagnosticsPanel
          v-if="item.coverageDiagnostics"
          :diagnostics="item.coverageDiagnostics"
          @toggle="setCoveragePanelExpanded(item.id, $event)"
        />

        <template v-if="item.assets?.length">
          <div
            class="row-carousel"
            :class="{ 'row-carousel--few': item.assets.length <= PAGE_SIZE }"
          >
            <button
              class="carousel-arrow carousel-arrow--left"
              :disabled="getCarousel(item.id).page === 0"
              @click="carouselPrev(item.id, item.assets.length, $event)"
              v-show="item.assets.length > PAGE_SIZE"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" stroke-width="2.5"
                   stroke-linecap="round" stroke-linejoin="round">
                <polyline points="15 18 9 12 15 6"/>
              </svg>
            </button>

            <div
              class="carousel-viewport"
              :class="{ 'carousel-viewport--few': item.assets.length <= PAGE_SIZE }"
            >
              <div
                v-for="(asset, localIdx) in getVisibleAssets(item)"
                :key="asset.file_hash || localIdx"
                :class="[
                  'carousel-item-wrapper',
                  { 'carousel-item-wrapper--fixed': item.assets.length <= PAGE_SIZE },
                ]"
              >
                <div
                  :class="[
                    'carousel-cell',
                    {
                      'carousel-cell--active':
                        getGlobalIdx(item, localIdx) === getCarousel(item.id).activeIdx,
                    },
                  ]"
                >
                  <div class="carousel-thumb-frame">
                    <CoverPreviewCard
                      :variant="{
                        id:             asset.file_hash,
                        task_id:        item.id,
                        video_url:      appStore.buildVideoUrl(asset.file_path),
                        cover_url:      asset.cover_path
                          ? appStore.buildVideoUrl(asset.cover_path)
                          : '',
                        status:         asset.status || 'PENDING',
                        cover_strategy: 'EXTRACT',
                      }"
                      :hide-actions="true"
                      aspect-ratio="1/1"
                      @preview="handleCardPreview(item, localIdx)"
                    />
                    <div
                      class="queue-corner-ribbon"
                      :class="`queue-ribbon-${normalizeAssetStatus(asset.status).toLowerCase()}`"
                    >
                      <span>{{ normalizeAssetStatus(asset.status) }}</span>
                    </div>
                  </div>
                </div>

                <div
                  class="carousel-title-box"
                  :class="{
                    'carousel-title-box--expanded':
                      expandedAssetTitles.has(assetTitleKey(item, asset, localIdx)),
                  }"
                  :title="getAssetTitle(item, asset)"
                  @click.stop
                >
                  <p class="carousel-title-text">{{ getAssetTitle(item, asset) }}</p>
                  <button
                    v-if="getAssetTitle(item, asset).length > 18"
                    class="carousel-title-toggle"
                    @click="toggleAssetTitle(item, asset, localIdx, $event)"
                    :aria-label="
                      expandedAssetTitles.has(assetTitleKey(item, asset, localIdx))
                        ? '折叠标题'
                        : '展开标题'
                    "
                  >
                    <svg
                      class="toggle-arrow"
                      :class="{
                        'toggle-arrow--up':
                          expandedAssetTitles.has(assetTitleKey(item, asset, localIdx)),
                      }"
                      width="10"
                      height="10"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2.6"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    >
                      <polyline points="6 9 12 15 18 9"/>
                    </svg>
                  </button>
                </div>
              </div>
            </div>

            <button
              class="carousel-arrow carousel-arrow--right"
              :disabled="
                getCarousel(item.id).page
                  >= Math.ceil(item.assets.length / PAGE_SIZE) - 1
              "
              @click="carouselNext(item.id, item.assets.length, $event)"
              v-show="item.assets.length > PAGE_SIZE"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" stroke-width="2.5"
                   stroke-linecap="round" stroke-linejoin="round">
                <polyline points="9 18 15 12 9 6"/>
              </svg>
            </button>

            <div v-if="item.assets.length > PAGE_SIZE" class="carousel-dots">
              <span
                v-for="p in Math.ceil(item.assets.length / PAGE_SIZE)"
                :key="p"
                :class="['dot', { 'dot--active': p - 1 === getCarousel(item.id).page }]"
              />
            </div>
          </div>
        </template>

        <template v-else>
          <div class="row-empty" />
        </template>
      </div>
    </DynamicScrollerItem>
  </DynamicScroller>
</section>
```

Nesting is balanced:

```text
DynamicScroller
└─ DynamicScrollerItem
   └─ task root
      ├─ existing content
      ├─ CoverageDiagnosticsPanel
      └─ existing asset region
```

## D. Expansion / Remeasure Semantics

当前源码存在明确的重新测量触发链：

```ts
const expandedCoveragePanels = reactive<Set<string>>(new Set())

function setCoveragePanelExpanded(id: string, open: boolean) {
  if (open) expandedCoveragePanels.add(id)
  else expandedCoveragePanels.delete(id)
}
```

Panel 的 native `<details>` toggle：

```vue
<details class="coverage-panel" @toggle="onToggle">
```

```ts
function onToggle(event: Event) {
  emit('toggle', (event.currentTarget as HTMLDetailsElement).open)
}
```

QueueView 接收：

```vue
@toggle="setCoveragePanelExpanded(item.id, $event)"
```

并将响应式布尔值作为高度依赖：

```vue
:size-dependencies="[expandedCoveragePanels.has(item.id)]"
```

安装版本的 `DynamicScrollerItem` 对 `sizeDependencies` 的实现是：

```js
if (!this.vscrollResizeObserver) {
  for (const k in this.sizeDependencies) {
    this.$watch(() => this.sizeDependencies[k], this.onDataUpdate);
  }
}
```

依赖变化后：

```js
onDataUpdate () {
  this.updateSize();
}
```

最终在下一 tick 读取当前 DOM 高度：

```js
computeSize (id) {
  this.$nextTick(() => {
    if (this.id === id) {
      const width = this.$el.offsetWidth;
      const height = this.$el.offsetHeight;
      this.applyWidthHeight(width, height);
    }
    this.$_pendingSizeUpdate = null;
  });
}
```

如果当前环境提供其注入的 resize observer，组件在 mounted 时还会调用：

```js
this.updateSize();
this.observeSize();
```

结论：

- collapsed → expanded 会触发 native toggle。
- toggle 改变响应式 Set。
- `size-dependencies[0]` 从 `false` 变为 `true`。
- DynamicScrollerItem 重新测量 DOM 高度。
- expanded → collapsed 使用同一路径。

这是源码级机制证明。现有测试没有浏览器运行时的高度断言，因此不把它描述为浏览器测试证明，但不存在“无重测机制”的 finding。

## E. CoverageDiagnosticsPanel

完整当前文件：

```vue
<script setup lang="ts">
import { computed } from 'vue'

import type {
  CoverageClassificationV1,
  CoverageDiagnosticsV1,
} from '../utils/coverageDiagnostics'
import {
  beatDisplayName,
  coverageStatusLabel,
  coverageStatusReason,
  coverageSummary,
  distributionText,
  previewSeedSummary,
  rejectionSummary,
  terminationPresentation,
} from '../utils/coveragePresentation'

const props = defineProps<{
  diagnostics: CoverageDiagnosticsV1
}>()

const emit = defineEmits<{
  toggle: [open: boolean]
}>()

const summary = computed(() => coverageSummary(props.diagnostics))
const termination = computed(() => terminationPresentation(props.diagnostics.termination_reason))
const rejection = computed(() => rejectionSummary(props.diagnostics))
const preview = computed(() => previewSeedSummary(props.diagnostics))

function onToggle(event: Event) {
  emit('toggle', (event.currentTarget as HTMLDetailsElement).open)
}

function statusClass(classification: CoverageClassificationV1 | null): string {
  if (classification === 'VARIABLE_BALANCED') return 'coverage-status--balanced'
  if (classification === 'FIXED_BY_CAPACITY') return 'coverage-status--fixed'
  if (classification === 'VARIABLE_TARGET_NOT_MET') return 'coverage-status--attention'
  return 'coverage-status--unavailable'
}
</script>

<template>
  <details class="coverage-panel" @toggle="onToggle">
    <summary class="coverage-summary">
      <span>{{ summary }}</span>
      <span class="coverage-summary-action" aria-hidden="true">查看详情</span>
    </summary>

    <div class="coverage-content">
      <div class="coverage-table-scroll">
        <table class="coverage-table">
          <thead>
            <tr>
              <th scope="col">Beat</th>
              <th scope="col">可用候选</th>
              <th scope="col">已使用</th>
              <th scope="col">未使用</th>
              <th scope="col">分布</th>
              <th scope="col">状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="beat in diagnostics.beats" :key="`${beat.beat_index}:${beat.beat_identity}`">
              <th scope="row">
                <span class="coverage-beat-name">{{ beatDisplayName(beat) }}</span>
              </th>
              <td>{{ beat.pool_size }}</td>
              <td>{{ beat.unique_used }}</td>
              <td>{{ beat.unused_count }}</td>
              <td class="coverage-distribution">{{ distributionText(beat) }}</td>
              <td class="coverage-status-cell">
                <span :class="['coverage-status', statusClass(beat.classification)]">
                  {{ coverageStatusLabel(beat.classification) }}
                </span>
                <small>{{ coverageStatusReason(beat.classification) }}</small>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <section class="coverage-planning-context" aria-label="覆盖规划上下文">
        <div class="coverage-context-grid">
          <span><b>计划接受</b>{{ diagnostics.accepted_count }} / {{ diagnostics.requested_count }}</span>
          <span><b>已检查组合</b>{{ diagnostics.examined_count }} / {{ diagnostics.candidate_space_size }}</span>
          <span><b>搜索预算</b>{{ diagnostics.search_budget }}</span>
          <span><b>规划状态</b>{{ termination.label }}</span>
        </div>
        <p v-if="termination.explanation" class="coverage-context-note">
          {{ termination.explanation }}
        </p>
        <p v-if="rejection" class="coverage-context-note">{{ rejection }}</p>
        <p v-if="preview" class="coverage-context-note">{{ preview }}</p>
      </section>
    </div>
  </details>
</template>

<style scoped>
.coverage-panel {
  flex-shrink: 0;
  min-width: 0;
  margin: 0 0 6px;
  border: 1px solid rgba(56, 189, 248, 0.16);
  border-radius: 7px;
  background: rgba(15, 23, 42, 0.5);
  color: #cbd5e1;
}

.coverage-summary {
  min-height: 28px;
  box-sizing: border-box;
  padding: 5px 9px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  color: #bae6fd;
  font-size: 0.7rem;
  font-weight: 650;
  line-height: 1.35;
}

.coverage-summary:focus-visible {
  outline: 2px solid #38bdf8;
  outline-offset: 2px;
}

.coverage-summary-action {
  flex-shrink: 0;
  color: #64748b;
  font-size: 0.62rem;
  font-weight: 500;
}

.coverage-panel[open] .coverage-summary-action {
  font-size: 0;
}

.coverage-panel[open] .coverage-summary-action::after {
  content: '收起';
  font-size: 0.62rem;
}

.coverage-content {
  padding: 0 9px 9px;
  border-top: 1px solid rgba(148, 163, 184, 0.1);
}

.coverage-table-scroll {
  max-width: 100%;
  overflow-x: auto;
  padding-top: 7px;
}

.coverage-table {
  width: 100%;
  min-width: 660px;
  border-collapse: collapse;
  color: #94a3b8;
  font-size: 0.68rem;
  font-variant-numeric: tabular-nums;
}

.coverage-table th,
.coverage-table td {
  padding: 6px 7px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
  text-align: left;
  vertical-align: top;
}

.coverage-table thead th {
  color: #64748b;
  font-size: 0.62rem;
  font-weight: 650;
  white-space: nowrap;
}

.coverage-table tbody th {
  color: #cbd5e1;
  font-weight: 650;
}

.coverage-beat-name {
  display: block;
}

.coverage-distribution {
  white-space: nowrap;
}

.coverage-status-cell {
  min-width: 185px;
}

.coverage-status {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border: 1px solid transparent;
  border-radius: 10px;
  font-size: 0.62rem;
  font-weight: 700;
  white-space: nowrap;
}

.coverage-status-cell small {
  display: block;
  margin-top: 3px;
  color: #64748b;
  font-size: 0.58rem;
  font-weight: 400;
  line-height: 1.35;
}

.coverage-status--balanced {
  border-color: rgba(74, 222, 128, 0.25);
  background: rgba(74, 222, 128, 0.09);
  color: #86efac;
}

.coverage-status--fixed {
  border-color: rgba(148, 163, 184, 0.22);
  background: rgba(148, 163, 184, 0.08);
  color: #cbd5e1;
}

.coverage-status--attention {
  border-color: rgba(245, 158, 11, 0.28);
  background: rgba(245, 158, 11, 0.09);
  color: #fcd34d;
}

.coverage-status--unavailable {
  border-color: rgba(100, 116, 139, 0.2);
  background: rgba(100, 116, 139, 0.07);
  color: #94a3b8;
}

.coverage-planning-context {
  padding-top: 8px;
}

.coverage-context-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 5px 12px;
  color: #94a3b8;
  font-size: 0.65rem;
}

.coverage-context-grid span {
  display: flex;
  gap: 5px;
  min-width: 0;
}

.coverage-context-grid b {
  color: #64748b;
  font-weight: 600;
  white-space: nowrap;
}

.coverage-context-note {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 0.62rem;
  line-height: 1.4;
}

@media (max-width: 760px) {
  .coverage-context-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
```

## F. Presentation Helper

完整当前文件：

```ts
import type {
  CoverageBeatDiagnosticsV1,
  CoverageClassificationV1,
  CoverageDiagnosticsV1,
} from './coverageDiagnostics'

const STATUS_LABELS: Record<CoverageClassificationV1, string> = {
  FIXED_BY_CAPACITY: '容量固定',
  VARIABLE_BALANCED: '均衡',
  VARIABLE_TARGET_NOT_MET: '未达到均衡目标',
}

const STATUS_REASONS: Record<CoverageClassificationV1, string> = {
  FIXED_BY_CAPACITY: '该 Beat 只有 1 个可用主视觉候选，重复使用由候选容量决定。',
  VARIABLE_BALANCED: '当前计划已在可用候选间尽可能均匀分配。',
  VARIABLE_TARGET_NOT_MET: '当前实际分布未达到该 Beat 的均衡覆盖目标。',
}

const TERMINATION_LABELS: Record<string, string> = {
  REQUEST_SATISFIED: '已满足请求数量',
  TRUE_SPACE_EXHAUSTED: '已检查全部候选组合',
  PLANNING_SEARCH_LIMIT_REACHED: '已达到规划搜索上限',
}

export interface CoverageTerminationPresentation {
  label: string
  explanation?: string
}

export function coverageSummary(diagnostics: CoverageDiagnosticsV1): string {
  let balanced = 0
  let fixed = 0
  let targetNotMet = 0
  let unavailable = 0

  for (const beat of diagnostics.beats) {
    if (beat.classification === 'VARIABLE_BALANCED') balanced += 1
    else if (beat.classification === 'FIXED_BY_CAPACITY') fixed += 1
    else if (beat.classification === 'VARIABLE_TARGET_NOT_MET') targetNotMet += 1
    else unavailable += 1
  }

  const parts: string[] = []
  if (targetNotMet > 0) parts.push(`${targetNotMet} 个 Beat 未达到均衡目标`)
  if (balanced > 0) parts.push(`${balanced} 个可变 Beat 均衡`)
  if (fixed > 0) parts.push(`${fixed} 个容量固定`)
  if (unavailable > 0) parts.push(`${unavailable} 个状态不可用`)

  return parts.length > 0 ? `覆盖：${parts.join(' · ')}` : '覆盖：暂无 Beat 覆盖信息'
}

export function beatDisplayName(beat: CoverageBeatDiagnosticsV1): string {
  return beat.beat_identity.trim() || `Beat ${beat.beat_index + 1}`
}

export function distributionText(beat: CoverageBeatDiagnosticsV1): string {
  const counts = beat.selected_histogram.map((entry) => entry.count)
  return counts.length > 0 ? counts.join(' / ') : '—'
}

export function coverageStatusLabel(
  classification: CoverageClassificationV1 | null,
): string {
  return classification === null ? '状态不可用' : STATUS_LABELS[classification]
}

export function coverageStatusReason(
  classification: CoverageClassificationV1 | null,
): string {
  return classification === null
    ? '当前没有可用于正常覆盖分类的候选容量信息。'
    : STATUS_REASONS[classification]
}

export function terminationPresentation(reason: string): CoverageTerminationPresentation {
  const label = TERMINATION_LABELS[reason]
  if (!label) return { label: `规划状态：${reason}` }
  if (reason === 'PLANNING_SEARCH_LIMIT_REACHED') {
    return {
      label,
      explanation: '规划在搜索预算内停止；候选空间仍可能存在未检查组合。',
    }
  }
  return { label }
}

export function rejectionSummary(diagnostics: CoverageDiagnosticsV1): string | undefined {
  const counts = diagnostics.rejection_counts
  if (
    counts.materialization_mismatch_count === 0
    && counts.invalid_plan_count === 0
    && counts.duplicate_fingerprint_reject_count === 0
  ) {
    return undefined
  }

  return `规划过程中跳过：映射不匹配 ${counts.materialization_mismatch_count}`
    + ` · 无效计划 ${counts.invalid_plan_count}`
    + ` · 重复组合 ${counts.duplicate_fingerprint_reject_count}`
}

export function previewSeedSummary(diagnostics: CoverageDiagnosticsV1): string | undefined {
  return diagnostics.preview_seeded
    ? '预览种子已作为第 1 个计划纳入覆盖统计。'
    : undefined
}
```

## G. Presentation Semantics

| Question | Answer | Evidence |
|---|---|---|
| A. Summary only counts backend classifications? | YES | `coverageSummary()` branches only on `beat.classification` and increments counters. |
| B. Any helper infers classification? | NO | No pool-size, histogram-gap, floor/ceil or mathematical classification logic exists. |
| C. Eligible uses `pool_size` directly? | YES | `{{ beat.pool_size }}` |
| D. Used uses `unique_used` directly? | YES | `{{ beat.unique_used }}` |
| E. Unused uses `unused_count` directly? | YES | `{{ beat.unused_count }}` |
| F. Distribution preserves histogram order? | YES | `.map(entry => entry.count)` without sorting. |
| G. Artificial zeroes appended? | NO | Only existing selected entries are joined. |
| H. Target-not-met explanation avoids unsupported cause? | YES | It only says the actual distribution did not meet the target. |
| I. Fixed explanation describes capacity? | YES | It explicitly states only one main-visual candidate exists. |

No frontend reclassification is present.

## H. Planning Context

Exact component source:

```vue
<span>
  <b>计划接受</b>
  {{ diagnostics.accepted_count }} / {{ diagnostics.requested_count }}
</span>

<span>
  <b>已检查组合</b>
  {{ diagnostics.examined_count }} / {{ diagnostics.candidate_space_size }}
</span>

<span>
  <b>搜索预算</b>
  {{ diagnostics.search_budget }}
</span>

<span>
  <b>规划状态</b>
  {{ termination.label }}
</span>

<p v-if="termination.explanation" class="coverage-context-note">
  {{ termination.explanation }}
</p>

<p v-if="rejection" class="coverage-context-note">
  {{ rejection }}
</p>

<p v-if="preview" class="coverage-context-note">
  {{ preview }}
</p>
```

`CoverageDiagnosticsPanel.vue` 和 `coveragePresentation.ts` 均没有引用：

```text
succeededCount
succeeded_count
```

规划接受数没有与渲染成功数混淆。

## I. Internal Data Visibility

对 component/helper 搜索以下字段的结果为空：

```text
normalized_file_hash
accepted_fingerprint_digests
preview_fingerprint_digest
asset_id
variant_planning_policy
balanced_axis_coverage
```

这些内部字段仅存在于测试 fixture 或 Phase 2C 类型中，没有进入面板 template、computed display 或 presentation helper。

结论：没有用户可见的内部 hash、digest、asset ID 或 contract identity。

## J. Failed Task / Collapsed Behavior

任务分类仍为：

```ts
const processingTasks = computed<QueueTask[]>(() =>
  queueStore.tasks.filter(
    t => t.type === 'pending' || t.type === 'running' || t.type === 'failed'
  )
)

const completedTasks = computed<QueueTask[]>(() =>
  queueStore.tasks.filter(t => t.type === 'completed')
)
```

Processing 列表中的 panel 条件：

```vue
<CoverageDiagnosticsPanel
  v-if="item.coverageDiagnostics"
  :diagnostics="item.coverageDiagnostics"
/>
```

没有：

```vue
item.type === 'completed'
```

因此 failed task 只要具有 normalized diagnostics 就可以显示。

默认折叠源码：

```vue
<details class="coverage-panel" @toggle="onToggle">
  <summary class="coverage-summary">
```

`<details>` 没有 `open` 属性；script 没有 mount/open 初始化；默认 collapsed。

## K. Accessibility / Responsive

Accessibility：

```vue
<details>
<summary>
<table>
<th scope="col">
<th scope="row">
```

Focus treatment：

```css
.coverage-summary:focus-visible {
  outline: 2px solid #38bdf8;
  outline-offset: 2px;
}
```

Summary 的可见文字包含实际 coverage 摘要，例如：

```text
覆盖：4 个可变 Beat 均衡 · 1 个容量固定
```

因此 summary 具有任务相关的可访问名称。`查看详情` 被标为 `aria-hidden`，native details 自身仍提供展开状态语义。

横向 containment：

```css
.coverage-panel {
  min-width: 0;
}

.coverage-table-scroll {
  max-width: 100%;
  overflow-x: auto;
}

.coverage-table {
  width: 100%;
  min-width: 660px;
}
```

Queue task root：

```css
.monitor-entry {
  min-width: 0;
}

.task-card {
  min-height: 258px;
  height: auto;
  box-sizing: border-box;
  overflow: hidden;
}
```

窄屏 planning context：

```css
@media (max-width: 760px) {
  .coverage-context-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
```

## L. Presentation Tests

完整当前测试文件：

```js
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import {
  coverageStatusLabel,
  coverageStatusReason,
  coverageSummary,
  distributionText,
  previewSeedSummary,
  rejectionSummary,
  terminationPresentation,
} from '../src/utils/coveragePresentation.ts'

function beat(classification, counts = [1], unusedCount = 0) {
  return {
    beat_index: 0,
    beat_identity: 'hook',
    role: 'X',
    pool_size: counts.length + unusedCount,
    selected_histogram: counts.map((count, index) => ({
      normalized_file_hash: `hash-${index}`,
      asset_id: index + 1,
      count,
    })),
    selected_count: counts.reduce((sum, count) => sum + count, 0),
    unique_used: counts.length,
    unused_count: unusedCount,
    ideal_floor: null,
    ideal_ceil: null,
    max_min_gap: null,
    classification,
  }
}

function diagnostics(beats = []) {
  return {
    type: 'balanced_axis_coverage',
    version: 1,
    variant_planning_policy: 'exact_main_visual_balanced',
    requested_count: 4,
    accepted_count: 4,
    candidate_space_size: 32,
    search_budget: 32,
    examined_count: 4,
    proposal_attempted_count: 3,
    termination_reason: 'REQUEST_SATISFIED',
    preview_seeded: false,
    preview_child_index: null,
    preview_fingerprint_digest: null,
    accepted_fingerprint_digests: [],
    rejection_counts: {
      materialization_mismatch_count: 0,
      invalid_plan_count: 0,
      duplicate_fingerprint_reject_count: 0,
    },
    beats,
  }
}

test('summary counts backend classifications without reclassifying coverage', () => {
  const healthy = diagnostics([
    ...Array.from({ length: 4 }, () => beat('VARIABLE_BALANCED')),
    beat('FIXED_BY_CAPACITY'),
  ])
  assert.equal(coverageSummary(healthy), '覆盖：4 个可变 Beat 均衡 · 1 个容量固定')

  const attention = diagnostics([
    beat('VARIABLE_TARGET_NOT_MET'),
    ...Array.from({ length: 3 }, () => beat('VARIABLE_BALANCED')),
    beat('FIXED_BY_CAPACITY'),
  ])
  assert.equal(
    coverageSummary(attention),
    '覆盖：1 个 Beat 未达到均衡目标 · 3 个可变 Beat 均衡 · 1 个容量固定',
  )

  assert.equal(
    coverageSummary(diagnostics([
      beat('FIXED_BY_CAPACITY'),
      beat('FIXED_BY_CAPACITY'),
    ])),
    '覆盖：2 个容量固定',
  )
  assert.equal(
    coverageSummary(diagnostics([
      beat('VARIABLE_BALANCED'),
      beat(null),
    ])),
    '覆盖：1 个可变 Beat 均衡 · 1 个状态不可用',
  )
  assert.equal(coverageSummary(diagnostics()), '覆盖：暂无 Beat 覆盖信息')
})

test('distribution preserves selected histogram order and does not invent zeroes', () => {
  assert.equal(
    distributionText(beat('VARIABLE_BALANCED', [1, 1, 1, 1])),
    '1 / 1 / 1 / 1',
  )
  assert.equal(
    distributionText(beat('VARIABLE_BALANCED', [1, 1], 2)),
    '1 / 1',
  )
  assert.equal(distributionText(beat(null, [], 2)), '—')
})

test('status labels and reasons map only backend classifications', () => {
  const cases = [
    [
      'FIXED_BY_CAPACITY',
      '容量固定',
      '该 Beat 只有 1 个可用主视觉候选，重复使用由候选容量决定。',
    ],
    [
      'VARIABLE_BALANCED',
      '均衡',
      '当前计划已在可用候选间尽可能均匀分配。',
    ],
    [
      'VARIABLE_TARGET_NOT_MET',
      '未达到均衡目标',
      '当前实际分布未达到该 Beat 的均衡覆盖目标。',
    ],
    [
      null,
      '状态不可用',
      '当前没有可用于正常覆盖分类的候选容量信息。',
    ],
  ]
  for (const [classification, label, reason] of cases) {
    assert.equal(coverageStatusLabel(classification), label)
    assert.equal(coverageStatusReason(classification), reason)
  }
})

test('termination presentation maps known reasons and safely presents unknown values', () => {
  assert.deepEqual(
    terminationPresentation('REQUEST_SATISFIED'),
    { label: '已满足请求数量' },
  )
  assert.deepEqual(
    terminationPresentation('TRUE_SPACE_EXHAUSTED'),
    { label: '已检查全部候选组合' },
  )
  assert.deepEqual(
    terminationPresentation('PLANNING_SEARCH_LIMIT_REACHED'),
    {
      label: '已达到规划搜索上限',
      explanation: '规划在搜索预算内停止；候选空间仍可能存在未检查组合。',
    },
  )
  assert.deepEqual(
    terminationPresentation('FUTURE_REASON'),
    { label: '规划状态：FUTURE_REASON' },
  )
})

test('rejection text is quiet for zeroes and task-level for nonzero counts', () => {
  assert.equal(rejectionSummary(diagnostics()), undefined)
  const value = diagnostics()
  value.rejection_counts = {
    materialization_mismatch_count: 1,
    invalid_plan_count: 0,
    duplicate_fingerprint_reject_count: 2,
  }
  assert.equal(
    rejectionSummary(value),
    '规划过程中跳过：映射不匹配 1 · 无效计划 0 · 重复组合 2',
  )
})

test('preview provenance appears only for a seeded preview and never exposes its digest', () => {
  const value = diagnostics()
  assert.equal(previewSeedSummary(value), undefined)
  value.preview_seeded = true
  value.preview_fingerprint_digest = 'a'.repeat(64)
  const text = previewSeedSummary(value)
  assert.equal(text, '预览种子已作为第 1 个计划纳入覆盖统计。')
  assert.equal(text.includes(value.preview_fingerprint_digest), false)
})

test('QueueView integrates the panel without changing the historical mode badge mapping', () => {
  const queueViewPath = fileURLToPath(
    new URL('../src/views/QueueView.vue', import.meta.url),
  )
  const source = readFileSync(queueViewPath, 'utf8')
  assert.match(
    source,
    /import CoverageDiagnosticsPanel from ['"]\.\.\/components\/CoverageDiagnosticsPanel\.vue['"]/,
  )
  assert.equal(
    (
      source.match(
        /<CoverageDiagnosticsPanel\s+v-if="item\.coverageDiagnostics"/g,
      ) ?? []
    ).length,
    2,
    'completed and failed-terminal list items both render from diagnostics availability',
  )
  assert.doesNotMatch(
    source,
    /v-if="item\.type === 'completed'"[^>]*>\s*<CoverageDiagnosticsPanel/,
  )
  assert.match(
    source,
    /if \(mode === 'director'\) return 'AI起草模式'/,
  )
  assert.match(source, /return '手工战术板模式'/)
})

test('panel source uses disclosure and table semantics without rendering internal identities', () => {
  const panelPath = fileURLToPath(
    new URL('../src/components/CoverageDiagnosticsPanel.vue', import.meta.url),
  )
  const source = readFileSync(panelPath, 'utf8')
  assert.match(source, /<details/)
  assert.match(source, /<summary/)
  assert.match(source, /<table/)
  for (const internalField of [
    'normalized_file_hash',
    'accepted_fingerprint_digests',
    'preview_fingerprint_digest',
    'asset_id',
  ]) {
    assert.equal(source.includes(internalField), false)
  }
})
```

Test classification：

| Test | Type | Proves | Does not prove |
|---|---|---|---|
| Summary | Actual helper execution | Exact classification counting and strings | Vue rendering |
| Distribution | Actual helper execution | Histogram order; no synthetic zeroes | Backend histogram correctness |
| Status labels/reasons | Actual helper execution | Exact mapping and supported wording | Visual appearance |
| Termination | Actual helper execution | Known/unknown mappings | Backend reason generation |
| Rejection | Actual helper execution | Zero suppression/nonzero text | Per-Beat causality |
| Preview | Actual helper execution | Conditional text and digest exclusion | Runtime preview creation |
| Queue integration | Source assertion | Import, two availability conditions, mode-label strings | Mounted component behavior, failed-task browser rendering, resize |
| Panel semantics | Source assertion | Presence of details/summary/table and absence of internal field names | Browser accessibility tree, layout, DynamicScroller remeasurement |

DynamicScroller expansion is not runtime-tested by these regex assertions. Its remeasurement is source-proven through the explicit toggle/dependency chain and the installed library implementation.

## M. Virtualization Necessity / Scope

- Fixed virtualization was insufficient because the old rows had exact fixed sizes of 60px and 270px. Expanded Coverage content has data-dependent height.
- `vue-virtual-scroller ^2.0.0-beta.8` was already in `package.json`.
- The plugin and stylesheet were already globally registered in `main.js`.
- No package or lockfile changed.
- `DynamicScroller` itself had no repository source usage at baseline; the existing QueueView used `RecycleScroller`.
- Processing had to support diagnostics because `processingTasks` explicitly includes `failed`.
- Completed had to support normalized live/historical completed diagnostics.
- Within the current architecture, each tab has one scroller containing both diagnostics and non-diagnostics items. A fixed and dynamic item model cannot be selected independently per row inside the former `RecycleScroller`.
- A different overlay/separate-list architecture could avoid converting both scrollers, but that is not the current implementation and would constitute a redesign.

The conversion therefore matches the two actual status locations where diagnostics can legitimately exist.

## N. Queue Behavior Preservation

The Phase 2D diff does not modify:

- task ordering
- `processingTasks`/`completedTasks` filtering
- historical hydration or merge behavior
- empty-state conditions/text
- asset iteration or media source construction
- carousel paging logic
- task action/delete behavior
- mode mapping
- mode badge markup
- result/outcome derivation

Generation-mode code remains:

```ts
function getModeLabel(task: QueueTask): string {
  const mode = String(
    (task as any).mode || (task as any).generation_mode || ''
  ).toLowerCase()
  if (mode === 'director') return 'AI起草模式'
  if (mode === 'blind') return '极速闭眼裂变'
  return '手工战术板模式'
}

function getModeClass(task: QueueTask): string {
  const mode = String(
    (task as any).mode || (task as any).generation_mode || 'manual'
  ).toLowerCase()
  return mode === 'director' || mode === 'blind'
    ? `mode-badge--${mode}`
    : 'mode-badge--manual'
}
```

Changes beyond panel insertion are limited to virtualization mechanics:

- `RecycleScroller` → `DynamicScroller`
- `DynamicScrollerItem` wrapper
- reactive expansion dependencies
- fixed card height → minimum plus automatic height
- width containment wrapper

## O. Backend / Transport Diff

All commands returned empty:

```text
git diff -- src/api/routes_dsl.py
git diff -- web_ui/src/workers/queueWorker.ts
git diff -- web_ui/src/stores/useQueueStore.ts
git diff -- web_ui/src/utils/coverageDiagnostics.ts
git diff -- web_ui/package.json web_ui/package-lock.json
```

No backend, transport, store, normalizer, dependency, persistence, planner, fingerprint, or DB change exists.

## P. Findings

NONE

The dynamic-height path is explicitly wired and supported by the installed component implementation. Presentation semantics remain backend-authoritative, and no internal diagnostic identity is exposed.

PHASE2D_TARGETED_REVIEW_CLEAN