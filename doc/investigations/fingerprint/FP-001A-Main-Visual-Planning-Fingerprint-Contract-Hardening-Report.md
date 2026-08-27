# FP-001A
# Main Visual Planning Fingerprint Contract Hardening Report

## 1. Baseline

```text
Branch: feature/var-001-variation-policy
HEAD:   885cc54dd32cb223c67460e593e9b96c0980cad9
Status: CLEAN
```

未执行 branch、merge、rebase、commit 或 push。

## 2. Existing INV Contract Preservation

现有 `_MainVisualFingerprint` 和 `_exact_main_visual_fingerprint()` 未作任何修改。Production diff 为纯新增代码。

仍由原 tuple 负责：

- `used_fingerprints`
- preview equality
- planner uniqueness
- candidate enumeration
- capacity/search budget
- warning semantics
- coordinator plan/fingerprint invariant
- authoritative plan handoff

Tuple shape 保持：

```py
tuple[
    tuple[
        int,  # beat_index
        str,  # stripped Beat identity
        int,  # layer_index == 0
        str,  # normalized main-X file_hash
    ],
    ...
]
```

方向性保持为：

```text
CompilationPlan
→ existing _exact_main_visual_fingerprint()
→ existing validated tuple
→ new canonical payload
→ canonical UTF-8 JSON
→ SHA-256 digest
```

现有 tuple 没有改为从新 payload 反向生成。

## 3. Files Changed

- [src/api/routes_dsl.py:181](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:181>)
  - 新增 contract 常量。
  - 新增 frozen dataclass。
  - 新增 canonical payload、canonical bytes 和 SHA-256 contract builder。
  - 未移动或修改 INV helper。

- [tests/test_fp001_fingerprint_contract.py:1](</E:/dopaworkspace/dopamatrix-desktop/tests/test_fp001_fingerprint_contract.py:1>)
  - 新增 15 个 focused tests。
  - 包括 FP1–FP14 和现有 tuple 精确回归断言。

没有修改 frontend、schema、model、DB、resolver、worker、compositor、TTS、subtitle、cover 或 BGM。

## 4. Fingerprint Type / Version

新增不可变常量：

```py
_MAIN_VISUAL_PLANNING_FINGERPRINT_TYPE = "main_visual_planning"
_MAIN_VISUAL_PLANNING_FINGERPRINT_VERSION = 1
_MAIN_VISUAL_PLANNING_SOURCE_HASH_ALGORITHM = "md5"
```

新增内部冻结对象：

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

没有使用 planning policy 名称 `exact_main_visual` 作为 fingerprint type。

## 5. Canonical Payload

新增纯函数：

```py
_main_visual_planning_canonical_payload(
    fingerprint: _MainVisualFingerprint,
) -> dict[str, Any]
```

逻辑结构：

```json
{
  "fingerprint_type": "main_visual_planning",
  "fingerprint_version": 1,
  "source_hash_algorithm": "md5",
  "beats": [
    {
      "beat_index": 0,
      "beat_identity": "Hook",
      "layer_index": 0,
      "normalized_file_hash": "abc123"
    }
  ]
}
```

Payload 直接序列化已验证 tuple：

- 保留 Beat 数组顺序。
- 保留 stripped Beat identity 的大小写和 Unicode。
- 不进一步 lowercase 或 Unicode-normalize Beat identity。
- 不包含 path、asset payload、Y-layer 或 Python repr。

## 6. Canonical Serialization

使用 Python 标准库 `json`：

```py
json.dumps(
    payload,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
).encode("utf-8")
```

契约属性：

- UTF-8。
- 字典 key 确定性排序。
- 无非必要空格。
- Beat array 顺序不变。
- Unicode 原值保留。
- delimiter-like 字符由 JSON escaping 消除歧义。
- 无新增依赖。

## 7. SHA-256 Digest

Contract builder：

```py
fingerprint_digest = hashlib.sha256(canonical_bytes).hexdigest()
```

输出为：

- SHA-256。
- 64 个字符。
- 小写 hexadecimal。
- 无 `sha256:` 前缀。

测试同时验证：

```py
digest == hashlib.sha256(contract.canonical_bytes).hexdigest()
```

## 8. Source Hash Algorithm Semantics

Canonical payload 明确记录：

```text
source_hash_algorithm = "md5"
```

算法语义保持分离：

| 概念 | 算法 |
|---|---|
| Main-X source asset identity | 完整文件 MD5 |
| Planning fingerprint digest | SHA-256 |

未重新 hash 文件，未修改 DAM、`LocalAsset` 或 import flow。

## 9. Dynamic Beat Behavior

Canonical helper 遍历既有 fingerprint tuple，没有固定 Beat 数量。

测试覆盖：

- 1 Beat
- 3 Beats
- 5 Beats
- 7 Beats

5-Beat 测试证明 payload 恰好包含五个按原顺序排列的 components。任意 Beat 数量重复序列化会产生相同 canonical bytes。

## 10. Tests Added

| ID | Test evidence |
|---|---|
| FP1 | 同一 tuple 产生相同 canonical bytes 和 digest |
| FP2 | 单一 main hash 改变导致 digest 改变 |
| FP3 | Beat 顺序改变导致 digest 改变 |
| FP4 | 仅 Beat identity 改变导致 digest 改变 |
| FP5 | hash 大小写/空格经现有 helper 规范化后 tuple 和 digest 相同 |
| FP6 | Y-layer 改变不影响 tuple 或 digest |
| FP7 | 5 个动态 Beat 生成五个有序 components |
| FP8 | 1/3/7 任意 Beat 数量确定性序列化 |
| FP9 | fingerprint type 明确为 `main_visual_planning` |
| FP10 | fingerprint version 等于 `1` |
| FP11 | source hash algorithm 等于 `md5` |
| FP12 | digest 为 64 位小写 SHA-256 hex，并与标准库计算一致 |
| FP13 | exact canonical JSON 验证 key 顺序及无空白行为 |
| FP14 | Unicode、引号、反斜杠及 delimiter-like 字符序列化无歧义 |

额外 critical regression：

```py
(
    (0, "Reveal", 0, "abc123"),
    (1, "CTA", 0, "def456"),
)
```

直接断言 `_exact_main_visual_fingerprint()` 返回值、tuple shape 和规范化结果保持不变。

Focused suite：

```text
Ran 15 tests
OK
```

## 11. INV-001 Regression

执行：

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_inv001_*.py" -q
```

结果：

```text
Ran 82 tests in 0.746s
OK
```

测试中出现的模拟失败日志、FFmpeg 缺失信息和 deprecation warnings 属于既有测试路径，不影响 suite 结果。

其他检查：

```text
py_compile:      PASS
git diff --check: PASS
```

`git diff --check` 仅显示 Git 的 LF→CRLF 工作区提示，不存在 whitespace error。

## 12. Scope Audit

| Check | Result |
|---|---|
| A. Current tuple helper unchanged | YES |
| B. Tuple shape unchanged | YES |
| C. `used_fingerprints` unchanged | YES |
| D. Preview equality unchanged | YES |
| E. Planner capacity/search unchanged | YES |
| F. Canonical payload deterministic | YES |
| G. Digest deterministic | YES |
| H. Source algorithm explicitly `md5` | YES |
| I. Digest algorithm SHA-256 | YES |
| J. No worker logging | YES |
| K. No Historical Ledger | YES |
| L. No stable Beat-ID invention | YES |

FP-001A 未修改：

- `render_worker` signature
- `_ChildWork` handoff
- runtime INFO/DEBUG logs
- planner acceptance
- coordinator uniqueness
- resolver
- DB schema
- dependencies

新 contract builder 的输入边界是已经由现有 helper 验证的 `_MainVisualFingerprint`。尚未接入运行时 handoff；该工作保留给 FP-001B。

## 13. Known Deferred Risks

- Beat identity durability：当前 digest 有意冻结现有 Beat string 语义；rename 会改变 digest。
- Source mutation：外部文件可能在存储 MD5 后被原地替换。
- Visual-sequence fingerprint：未实现；未来必须使用独立 fingerprint type。
- Planning-structure fingerprint：未实现；没有发明 stable Beat ID。
- Historical Ledger：未实现 DB schema、index 或 persistence。
- Runtime observability：未传递或记录 child-bound digest。

## 14. Review Findings

**NONE**

未发现 scope expansion、INV regression 或新依赖需求。

## 15. Git Status

```text
 M src/api/routes_dsl.py
?? tests/test_fp001_fingerprint_contract.py
```

仅包含预期的 FP-001A production addition 和 focused test file。

未 commit，未 push。未启动 FP-001B 或 VAR-001。