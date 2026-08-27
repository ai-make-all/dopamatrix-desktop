# FP-001A
# Targeted Fingerprint Contract Code Review Bundle

## 1. Baseline

```text
branch:
feature/var-001-variation-policy

HEAD:
885cc54dd32cb223c67460e593e9b96c0980cad9

git status --short:
 M src/api/routes_dsl.py
?? doc/investigations/fingerprint/FP-001A-Main-Visual-Planning-Fingerprint-Contract-Hardening-Report.md
?? tests/test_fp001_fingerprint_contract.py

git diff --stat:
 src/api/routes_dsl.py | 64 +++++++++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 64 insertions(+)
```

`git diff --stat` 不显示两个未跟踪文件。

`git diff --check`：

```text
PASS
```

仅有 Git LF→CRLF 工作区提示，没有 whitespace error。

## 2. Production Diff

Production diff 仅涉及 [routes_dsl.py](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:181>)：

```diff
 _MainVisualFingerprint = tuple[tuple[int, str, int, str], ...]

+_MAIN_VISUAL_PLANNING_FINGERPRINT_TYPE = "main_visual_planning"
+_MAIN_VISUAL_PLANNING_FINGERPRINT_VERSION = 1
+_MAIN_VISUAL_PLANNING_SOURCE_HASH_ALGORITHM = "md5"
```

分类：**A. contract constants**

```diff
+@dataclass(frozen=True)
+class _MainVisualPlanningFingerprintContract:
+    fingerprint_type: str
+    fingerprint_version: int
+    source_hash_algorithm: str
+    fingerprint_digest: str
+    components: _MainVisualFingerprint
+    canonical_bytes: bytes
```

分类：**B. contract type/dataclass**

```diff
+def _main_visual_planning_canonical_payload(
+    fingerprint: _MainVisualFingerprint,
+) -> dict[str, Any]:
+    """Return the canonical logical payload for a validated INV fingerprint."""
+    return {
+        "fingerprint_type": _MAIN_VISUAL_PLANNING_FINGERPRINT_TYPE,
+        "fingerprint_version": _MAIN_VISUAL_PLANNING_FINGERPRINT_VERSION,
+        "source_hash_algorithm": _MAIN_VISUAL_PLANNING_SOURCE_HASH_ALGORITHM,
+        "beats": [
+            {
+                "beat_index": beat_index,
+                "beat_identity": beat_identity,
+                "layer_index": layer_index,
+                "normalized_file_hash": normalized_file_hash,
+            }
+            for beat_index, beat_identity, layer_index, normalized_file_hash
+            in fingerprint
+        ],
+    }
```

分类：**C. canonical payload**

```diff
+def _main_visual_planning_canonical_bytes(
+    fingerprint: _MainVisualFingerprint,
+) -> bytes:
+    """Serialize a validated INV fingerprint as deterministic UTF-8 JSON."""
+    payload = _main_visual_planning_canonical_payload(fingerprint)
+    return json.dumps(
+        payload,
+        ensure_ascii=False,
+        sort_keys=True,
+        separators=(",", ":"),
+        allow_nan=False,
+    ).encode("utf-8")
```

分类：**D. canonical serialization**

```diff
+def _main_visual_planning_fingerprint_contract(
+    fingerprint: _MainVisualFingerprint,
+) -> _MainVisualPlanningFingerprintContract:
+    """Build the additive versioned digest contract for a validated INV tuple."""
+    canonical_bytes = _main_visual_planning_canonical_bytes(fingerprint)
+    return _MainVisualPlanningFingerprintContract(
+        fingerprint_type=_MAIN_VISUAL_PLANNING_FINGERPRINT_TYPE,
+        fingerprint_version=_MAIN_VISUAL_PLANNING_FINGERPRINT_VERSION,
+        source_hash_algorithm=_MAIN_VISUAL_PLANNING_SOURCE_HASH_ALGORITHM,
+        fingerprint_digest=hashlib.sha256(canonical_bytes).hexdigest(),
+        components=fingerprint,
+        canonical_bytes=canonical_bytes,
+    )
```

分类：**E. SHA-256 digest builder**

最终 hunk 分类：

| Category | Result |
|---|---|
| A. Contract constants | 1 hunk |
| B. Contract type/dataclass | 1 hunk |
| C. Canonical payload | 1 helper |
| D. Canonical serialization | 1 helper |
| E. SHA-256 builder | 1 helper |
| F. Integration/call-site change | **NONE** |
| G. Unrelated production change | **NONE** |

## 3. Contract Constants

精确定义：

```py
_MAIN_VISUAL_PLANNING_FINGERPRINT_TYPE = "main_visual_planning"
_MAIN_VISUAL_PLANNING_FINGERPRINT_VERSION = 1
_MAIN_VISUAL_PLANNING_SOURCE_HASH_ALGORITHM = "md5"
```

验证：

```text
fingerprint_type:       main_visual_planning
fingerprint_version:    1
source_hash_algorithm:  md5
```

常量为独立字面量，没有从以下内容派生：

- `variant_planning_policy`
- `"exact_main_visual"`
- planner configuration
- request payload

## 4. Contract Object

完整定义：

```py
@dataclass(frozen=True)
class _MainVisualPlanningFingerprintContract:
    fingerprint_type: str
    fingerprint_version: int
    source_hash_algorithm: str
    fingerprint_digest: str
    components: _MainVisualFingerprint
    canonical_bytes: bytes
```

验证：

- `frozen=True`：禁止字段重新赋值。
- `components`：保留 `_MainVisualFingerprint` tuple。
- `canonical_bytes`：`bytes`。
- `fingerprint_digest`：`str`。
- 其余 metadata 为 `str/int`。

是否包含以下对象：

| Object | Present |
|---|---:|
| Mutable list | NO |
| Mutable dict | NO |
| `CompilationPlan` | NO |
| `LocalAsset` | NO |
| File path | NO |

所有实际字段值均为不可变类型。

## 5. Canonical Payload

完整 helper：

```py
def _main_visual_planning_canonical_payload(
    fingerprint: _MainVisualFingerprint,
) -> dict[str, Any]:
    """Return the canonical logical payload for a validated INV fingerprint."""
    return {
        "fingerprint_type": _MAIN_VISUAL_PLANNING_FINGERPRINT_TYPE,
        "fingerprint_version": _MAIN_VISUAL_PLANNING_FINGERPRINT_VERSION,
        "source_hash_algorithm": _MAIN_VISUAL_PLANNING_SOURCE_HASH_ALGORITHM,
        "beats": [
            {
                "beat_index": beat_index,
                "beat_identity": beat_identity,
                "layer_index": layer_index,
                "normalized_file_hash": normalized_file_hash,
            }
            for beat_index, beat_identity, layer_index, normalized_file_hash
            in fingerprint
        ],
    }
```

Tuple 映射：

| Tuple position | Unpacked variable | Payload field |
|---:|---|---|
| `0` | `beat_index` | `beat_index` |
| `1` | `beat_identity` | `beat_identity` |
| `2` | `layer_index` | `layer_index` |
| `3` | `normalized_file_hash` | `normalized_file_hash` |

Helper 没有：

- 再次 strip Beat identity。
- lowercase Beat identity。
- Unicode normalization。
- 再次 normalize source hash。
- 读取 `CompilationPlan`。
- 读取 `LocalAsset`。
- 查询 DB。
- 读取文件。

它只解构并复制已经验证的 tuple。

## 6. Canonical Serialization

完整 helper：

```py
def _main_visual_planning_canonical_bytes(
    fingerprint: _MainVisualFingerprint,
) -> bytes:
    """Serialize a validated INV fingerprint as deterministic UTF-8 JSON."""
    payload = _main_visual_planning_canonical_payload(fingerprint)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
```

精确参数验证：

```text
ensure_ascii=False       YES
sort_keys=True           YES
separators=(",", ":")    YES
allow_nan=False          YES
.encode("utf-8")         YES
```

答案：

A. Alternate canonical serialization path？  
**NO。**

B. Python repr/string tuple serialization？  
**NO。**

C. Delimiter-based serialization？  
**NO。**

## 7. Digest Builder

完整 builder：

```py
def _main_visual_planning_fingerprint_contract(
    fingerprint: _MainVisualFingerprint,
) -> _MainVisualPlanningFingerprintContract:
    """Build the additive versioned digest contract for a validated INV tuple."""
    canonical_bytes = _main_visual_planning_canonical_bytes(fingerprint)
    return _MainVisualPlanningFingerprintContract(
        fingerprint_type=_MAIN_VISUAL_PLANNING_FINGERPRINT_TYPE,
        fingerprint_version=_MAIN_VISUAL_PLANNING_FINGERPRINT_VERSION,
        source_hash_algorithm=_MAIN_VISUAL_PLANNING_SOURCE_HASH_ALGORITHM,
        fingerprint_digest=hashlib.sha256(canonical_bytes).hexdigest(),
        components=fingerprint,
        canonical_bytes=canonical_bytes,
    )
```

方向：

```text
_MainVisualFingerprint
→ _main_visual_planning_canonical_payload()
→ _main_visual_planning_canonical_bytes()
→ hashlib.sha256(canonical_bytes).hexdigest()
```

Digest 不从以下内容计算：

- dict repr
- tuple repr
- 默认格式 JSON
- `CompilationPlan`
- source file

`hexdigest()` 产生 64 位小写 hexadecimal；FP12 对格式和标准库 SHA-256 结果均有直接断言。

## 8. Directionality Audit

生产调用点：

```text
_main_visual_planning_canonical_payload
├─ definition
└─ called by _main_visual_planning_canonical_bytes

_main_visual_planning_canonical_bytes
├─ definition
└─ called by _main_visual_planning_fingerprint_contract

_main_visual_planning_fingerprint_contract
└─ definition only; no production consumer
```

除 helper 内部链路外，所有调用都位于新测试文件。

以下生产路径没有新调用：

- `_exact_main_visual_fingerprint`
- `_preview_selection`
- `_plan_exact_main_visual_variants`
- `used_fingerprints`
- `_plan_exact_main_visual_variants_from_db`
- `render_batch_worker`
- `render_worker`

INV planner acceptance 是否依赖 canonical digest？

**NO。**

当前 digest builder 处于 test-accessible、future-consumer-ready 状态，但没有接入 planner 或 runtime。

## 9. INV Helper Preservation

Production diff 是 `64 insertions, 0 deletions`。

`_MainVisualFingerprint` 在 diff 中仅作为未修改 context 出现：

```py
_MainVisualFingerprint = tuple[tuple[int, str, int, str], ...]
```

`_exact_main_visual_fingerprint()` 的函数体没有任何 changed line。新增 canonical helper 位于其 `return tuple(fingerprint)` 之后。

因此：

- tuple type 未变。
- tuple component order 未变。
- Beat strip 行为未变。
- source hash normalization 未变。
- main layer validation 未变。
- planner equality 未变。

**Semantic change: NONE.**

## 10. Test Source

完整测试文件：[test_fp001_fingerprint_contract.py](</E:/dopaworkspace/dopamatrix-desktop/tests/test_fp001_fingerprint_contract.py:1>)

Fixture/helper 结构：

```py
def _plan(
    hashes: list[str],
    *,
    beat_names: list[str] | None = None,
    y_hash: str | None = None,
) -> CompilationPlan:
    beat_names = beat_names or [f"Beat-{index}" for index in range(len(hashes))]
    beats = []
    for index, (beat_name, file_hash) in enumerate(zip(beat_names, hashes)):
        layers = [
            ResolvedLayer(
                layer_index=0,
                asset_id=index + 1,
                file_path=f"main-{index}.mp4",
                asset_type="video",
                file_hash=file_hash,
            )
        ]
        if y_hash is not None:
            layers.append(
                ResolvedLayer(
                    layer_index=1,
                    asset_id=1000 + index,
                    file_path=f"y-{index}.mp3",
                    asset_type="audio_bgm",
                    file_hash=f"{y_hash}-{index}",
                )
            )
        beats.append(
            BeatCompilationResult(
                beat=beat_name,
                role="body",
                address_mode="locked",
                layers=layers,
                resolved=True,
            )
        )
    return CompilationPlan(
        engine_type="content",
        beats=beats,
        unresolved_beats=[],
        summary=CompilationPlanSummary(
            total_beats=len(beats),
            resolved_beats=len(beats),
            unresolved_beats=0,
        ),
    )


def _fingerprint(plan: CompilationPlan):
    return routes_dsl._exact_main_visual_fingerprint(plan)


def _contract(plan: CompilationPlan):
    return routes_dsl._main_visual_planning_fingerprint_contract(
        _fingerprint(plan)
    )
```

Test mapping：

| Test | Actual assertions |
|---|---|
| FP1 | 两次 contract 的 `canonical_bytes` 和 digest 相等 |
| FP2 | 单 main hash 改变，digest 不相等 |
| FP3 | Beat/asset 顺序交换，digest 不相等 |
| FP4 | 仅 `Reveal` → `Product Reveal`，digest 不相等 |
| FP5 | 规范化前后 tuple 相等且 digest 相等 |
| FP6 | 不同 Y-layer 下 tuple 与 digest 均相等 |
| FP7 | payload 长度为 5，并与完整有序 component list 相等 |
| FP8 | 对 1/3/7 Beat 重复序列化 bytes 相等，并验证 Beat 数量 |
| FP9 | constant 和 contract type 均等于 `main_visual_planning` |
| FP10 | constant 和 contract version 均等于 `1` |
| FP11 | constant 和 contract source algorithm 均等于 `md5` |
| FP12 | regex 验证 64 位小写 hex，并与 `hashlib.sha256(bytes)` 相等 |
| FP13 | 与独立指定的 exact bytes literal 相等 |
| FP14 | 两组 delimiter-like/Unicode tuple bytes 不相等，并 JSON round-trip |
| Critical | 直接断言现有 helper 返回 exact tuple 和 tuple component types |

Critical tuple regression：

```py
def test_existing_inv_tuple_shape_and_value_are_unchanged(self):
    plan = _plan(
        ["  AbC123  ", "DEF456"],
        beat_names=[" Reveal ", "CTA"],
    )

    fingerprint = routes_dsl._exact_main_visual_fingerprint(plan)

    self.assertEqual(
        fingerprint,
        (
            (0, "Reveal", 0, "abc123"),
            (1, "CTA", 0, "def456"),
        ),
    )
    self.assertIsInstance(fingerprint, tuple)
    self.assertTrue(
        all(isinstance(component, tuple) for component in fingerprint)
    )
    self.assertEqual(
        routes_dsl._main_visual_planning_fingerprint_contract(
            fingerprint
        ).components,
        fingerprint,
    )
```

## 11. Canonical JSON Evidence

FP13 完整内容：

```py
def test_fp13_canonical_json_has_sorted_keys_and_no_whitespace(self):
    fingerprint = _fingerprint(_plan(["abc"], beat_names=["Hook"]))
    canonical = routes_dsl._main_visual_planning_canonical_bytes(fingerprint)

    self.assertEqual(
        canonical,
        b'{"beats":[{"beat_identity":"Hook","beat_index":0,'
        b'"layer_index":0,"normalized_file_hash":"abc"}],'
        b'"fingerprint_type":"main_visual_planning",'
        b'"fingerprint_version":1,"source_hash_algorithm":"md5"}',
    )
```

该测试使用独立 hard-coded bytes literal。

它没有使用另一次 `json.dumps()` 计算 expected value，因此不是生产 helper 与自身比较。

## 12. Unicode / Delimiter Evidence

FP14 完整内容：

```py
def test_fp14_delimiter_like_and_unicode_values_are_unambiguous(self):
    left = ((0, "揭示|A:B,\\\"", 0, "c|d:e"),)
    right = ((0, "揭示", 0, "A:B,\\\"|c|d:e"),)

    left_bytes = routes_dsl._main_visual_planning_canonical_bytes(left)
    right_bytes = routes_dsl._main_visual_planning_canonical_bytes(right)

    self.assertNotEqual(left_bytes, right_bytes)
    self.assertEqual(
        json.loads(left_bytes.decode("utf-8"))["beats"][0],
        {
            "beat_index": 0,
            "beat_identity": "揭示|A:B,\\\"",
            "layer_index": 0,
            "normalized_file_hash": "c|d:e",
        },
    )
```

困难值覆盖：

- Unicode：`揭示`
- Quote：`\"`
- Backslash：`\`
- Pipe delimiter：`|`
- Colon：`:`
- Comma：`,`

两种可能在简单 delimiter-concatenation 中产生边界歧义的 components 得到不同 canonical bytes；JSON round-trip 恢复原始字段。

## 13. Dynamic Beat Evidence

FP7：

```py
def test_fp7_five_dynamic_beats_preserve_ordered_components(self):
    names = ["Hook", "Context", "Build", "Reveal", "CTA"]
    hashes = [f"hash-{index}" for index in range(5)]
    fingerprint = _fingerprint(_plan(hashes, beat_names=names))
    payload = routes_dsl._main_visual_planning_canonical_payload(fingerprint)

    self.assertEqual(len(payload["beats"]), 5)
    self.assertEqual(
        payload["beats"],
        [
            {
                "beat_index": index,
                "beat_identity": names[index],
                "layer_index": 0,
                "normalized_file_hash": hashes[index],
            }
            for index in range(5)
        ],
    )
```

不仅断言长度，也断言全部五个 components 的完整顺序和值。

FP8：

```py
def test_fp8_arbitrary_beat_counts_are_deterministic(self):
    for beat_count in (1, 3, 7):
        with self.subTest(beat_count=beat_count):
            plan = _plan([f"hash-{index}" for index in range(beat_count)])
            fingerprint = _fingerprint(plan)
            first = routes_dsl._main_visual_planning_canonical_bytes(fingerprint)
            second = routes_dsl._main_visual_planning_canonical_bytes(fingerprint)

            self.assertEqual(first, second)
            self.assertEqual(
                len(json.loads(first.decode("utf-8"))["beats"]),
                beat_count,
            )
```

覆盖 1、3、7 Beat，并直接验证重复 serialization 的确定性。

## 14. Source vs Digest Algorithm

Source metadata：

```py
_MAIN_VISUAL_PLANNING_SOURCE_HASH_ALGORITHM = "md5"
```

Digest implementation：

```py
hashlib.sha256(canonical_bytes).hexdigest()
```

FP11 验证 source metadata：

```py
self.assertEqual(contract.source_hash_algorithm, "md5")
```

FP12 验证 digest：

```py
self.assertRegex(digest, re.compile(r"^[0-9a-f]{64}$"))
self.assertEqual(
    digest,
    hashlib.sha256(contract.canonical_bytes).hexdigest(),
)
```

结论：

```text
source identity algorithm: MD5
fingerprint digest algorithm: SHA-256
```

没有读取 source file，也没有对 source file 执行 SHA-256。

## 15. Immutability

Contract 的所有存储字段均不可变：

- Frozen dataclass 阻止属性重新赋值。
- `components` 是 tuple of tuples。
- tuple component 是 `int/str`。
- `canonical_bytes` 是 bytes。
- metadata/digest 是 `str/int`。

`_main_visual_planning_canonical_payload()` 返回新的可变 dict/list。这不构成当前 correctness 问题，因为：

- payload 没有存入 contract。
- canonical helper 每次创建新 payload。
- contract 保存的是已经生成的 immutable bytes 和 digest。
- 调用方修改先前返回的 payload 不会改变 contract 的 bytes、digest 或 components。

## 16. Production Call-Site Audit

所有 production matches：

| Match | Classification |
|---|---|
| `_MAIN_VISUAL_PLANNING_FINGERPRINT_TYPE` | Definition + payload/builder metadata |
| `_MAIN_VISUAL_PLANNING_FINGERPRINT_VERSION` | Definition + payload/builder metadata |
| `_MAIN_VISUAL_PLANNING_SOURCE_HASH_ALGORITHM` | Definition + payload/builder metadata |
| `_MainVisualPlanningFingerprintContract` | Type definition + builder return |
| `main_visual_planning` | Constant literal only |
| `canonical_bytes` | Contract field, local builder value, SHA-256 input |
| `fingerprint_digest` | Contract field and builder assignment |

Consumers:

```text
Planner decision consumer: NONE
Runtime consumer:          NONE
DB persistence:            NONE
Runtime logging:           NONE
Frontend/API exposure:     NONE
```

## 17. Scope Audit

Tracked production diff only modifies `src/api/routes_dsl.py` with additions.

No changes to:

- `dsl_parser.py`
- `schemas.py`
- `models.py`
- frontend
- `render_worker`
- `_ChildWork`
- DB/schema/migrations
- TTS
- Subtitle
- Compositor
- Cover
- BGM
- requirements/dependencies

The untracked Markdown report was already present at this review’s baseline and is not part of the production diff.

## 18. Test Results

Focused tests:

```text
Ran 15 tests in 0.004s
OK
```

INV regression:

```text
Ran 82 tests in 0.853s
OK
```

Python compilation:

```text
src/api/routes_dsl.py: PASS
tests/test_fp001_fingerprint_contract.py: PASS
```

`git diff --check`：

```text
PASS
```

既有 test logs 中的模拟 failure、FFmpeg 信息及 deprecation warnings 不构成 test failure。

## 19. Review Findings

**NONE**

```text
F integration/call-site changes: NONE
G unrelated production changes: NONE
INV semantic changes:          NONE
```

## 20. Final Git Status

```text
branch:
feature/var-001-variation-policy

HEAD:
885cc54dd32cb223c67460e593e9b96c0980cad9

status:
 M src/api/routes_dsl.py
?? doc/investigations/fingerprint/FP-001A-Main-Visual-Planning-Fingerprint-Contract-Hardening-Report.md
?? tests/test_fp001_fingerprint_contract.py

diff stat:
 src/api/routes_dsl.py | 64 +++++++++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 64 insertions(+)
```

最终状态与本次只读审查开始时一致。未修改文件，未 commit，未 push，未启动 FP-001B 或 VAR-001。