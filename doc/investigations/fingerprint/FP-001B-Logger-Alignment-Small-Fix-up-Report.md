# FP-001B
# Logger Alignment Small Fix-up Report

## 1. Root Cause

`FP001B_INFO_LOGGER_SUPPRESSED`

FP observability previously使用 `routes_dsl` 的 stdlib logger，而实际后端 INFO sink 是项目 Loguru logger。

## 2. Files Changed

- [src/api/routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:75)
- [tests/test_fp001_fingerprint_observability.py](E:/dopaworkspace/dopamatrix-desktop/tests/test_fp001_fingerprint_observability.py:489)

未修改其他生产文件。

## 3. Logger Alignment

新增明确别名：

```python
from src.core.logger import logger as fingerprint_logger
```

仅以下 FP observability 输出改用该 logger：

```python
fingerprint_logger.warning(...)
fingerprint_logger.info(...)
```

未配置新 handler，未再次调用 `setup_logger()`，未引入新依赖。

## 4. Existing Routes_DSL Logger Preservation

原定义保持不变：

```python
logger = logging.getLogger(__name__)
```

所有非 FP 的历史 `routes_dsl` 日志调用仍使用该 stdlib logger。

生产代码中 `fingerprint_logger` 仅有：

- 1 个导入
- 1 个 FP diagnostic WARNING
- 1 个 VariantFingerprint INFO

`FP_LOGGER_ALIGNMENT_LOCAL_ONLY`

## 5. VariantFingerprint INFO Format

改为符合项目 Loguru 习惯的预构建单字符串：

```python
event_json = json.dumps(
    event,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
)
fingerprint_logger.info(f"[VariantFingerprint] {event_json}")
```

事件仍只输出一次，JSON 字段及 digest contract 未改变。

FL1 实际提取并解析 `[VariantFingerprint] ` 后的 JSON，验证：

```text
event = VariantFingerprint
fingerprint_type = main_visual_planning
fingerprint_version = 1
```

## 6. Diagnostic Logger Alignment

以下诊断均改用项目 Loguru sink：

- `FINGERPRINT_OBSERVABILITY_MISSING`
- `FINGERPRINT_OBSERVABILITY_MISMATCH`
- `FINGERPRINT_OBSERVABILITY_FAILED`

诊断 detail 仍限制为 300 字符。未增加 product warning、WebSocket 字段、TaskHistory 字段或 child failure。

## 7. Non-Blocking Semantics

原安全边界保留：

- INFO 抛异常：进入 `FINGERPRINT_OBSERVABILITY_FAILED`
- diagnostic logger 抛异常：内部吞掉
- INFO 与 diagnostic 同时失败：不递归、不逃逸
- render worker 继续原有成功路径

## 8. Tests Added

| Test | Evidence |
|---|---|
| FL1 | 正常事件使用专用 Loguru logger，并可解析有效 JSON |
| FL2 | 正常 FP INFO 不通过旧 stdlib logger 输出 |
| FL3 | mismatch diagnostic 使用 Loguru，render 成功 |
| FL4 | missing diagnostic 使用 Loguru，render 成功 |
| FL5 | contract failure 使用 Loguru diagnostic，render 成功 |
| FL6 | Loguru INFO 异常不导致 render 失败 |
| FL7 | INFO 与 diagnostic logger 同时异常时不逃逸、不递归 |
| FL8 | `routes_dsl.logger` 仍是 `logging.getLogger(__name__)` |

FO1–FO19 全部保留并通过。

定向 observability 测试：

```text
Ran 27 tests
OK
```

## 9. FP Regression

```text
Ran 42 tests
OK
```

包含：

- FP-001A contract tests
- FO1–FO19
- FL1–FL8

## 10. INV Regression

```text
Ran 82 tests
OK
```

INV tuple、planner acceptance、capacity/search、preview equality及 authoritative handoff 均未改变。

## 11. Scope Audit

确认：

- `_MainVisualFingerprint` 未改
- `_exact_main_visual_fingerprint` 未改
- canonical payload/bytes/digest 未改
- event payload字段未改
- worker handoff及 authoritative recomputation 未改
- exactly-once INFO 未改
- DB、TaskHistory、schema、frontend 未改
- UI badge 未改
- 无全局 logger migration
- 无新依赖
- `py_compile`：通过
- `git diff --check`：通过，仅现存 LF→CRLF 提示

`FP_LOGGER_ALIGNMENT_LOCAL_ONLY`

## 12. Review Findings

`NONE`

## 13. Final Git Status

```text
 M src/api/routes_dsl.py
?? doc/investigations/fingerprint/FP-001B-Runtime-Fingerprint-Observability-Implementation-Report.md
?? doc/investigations/fingerprint/FP-001B-Runtime-VariantFingerprint-Reachability-Audit.md
?? doc/investigations/fingerprint/FP-001B-Small-Fix-up-Report.md
?? doc/investigations/fingerprint/FP-001B-Targeted-Runtime-Observability-Code-Review-Bundle.md
?? tests/test_fp001_fingerprint_observability.py
```

未启动 backend，未 commit，未 push。

FP001B_LOGGER_ALIGNMENT_PASS