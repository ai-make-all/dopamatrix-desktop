## 7. Reproduction Evidence Package — REQUIRED BEFORE FORMAL CODE DIAGNOSIS

Before Codex produces its formal root-cause report, reproduce the issue once on the current branch and attach evidence.

### 7.1 Environment

Fill in:

```text
Date/time:
Git branch: fix/creative-duplicate-detection
Git commit:
Run mode: tauri dev / packaged installer
OS:
Tenant:
Project:
Recipe / template:
```

### 7.2 Exact user steps

Record the shortest reproducible flow from opening the product to output creation.

Template:

```text
1. Launch DopaMatrix.
2. Select tenant/project: ...
3. Open: ...
4. Import/select assets: ...
5. Select recipe/template: ...
6. Set batch size: ...
7. Set other options: ...
8. Click: ...
9. Wait for all tasks to finish.
10. Observe outputs: ...
```

### 7.3 Input assets

Record exact filenames and, if visible, asset IDs/hashes:

```text
Asset 1:
Asset 2:
Asset 3:
...
```

Do not rename the source files after reproduction until the investigation is complete.

### 7.4 Output evidence

For each generated output:

```text
Output 1
- UI/task ID:
- filename:
- full path:
- size:
- duration:
- created time:

Output 2
...
```

### 7.5 Duplicate classification

Classify the observed duplicate:

**Type A — file-level exact duplicate**

- SHA-256 is identical

**Type B — visually identical but binary different**

- SHA-256 differs
- content appears the same

**Type C — path/overwrite suspicion**

- multiple tasks reference the same output path/name
- earlier file appears replaced or reused

Do not use "looks the same" as the only diagnostic fact if file-level evidence can be collected.

### 7.6 Screenshots

Capture, where available:

- Matrix/batch settings before generation
- task list while generating
- completed result cards
- duplicate outputs shown side-by-side
- output filenames/paths
E:\dopaworkspace\dopamatrix-desktop\output
- any error/warning
- relevant console/backend log window

Use stable filenames such as:

```text
INV-001-01-batch-settings.png
INV-001-02-task-list.png
INV-001-03-duplicate-results.png
INV-001-04-output-files.png
INV-001-05-backend-log.png
```

### 7.7 Logs

Preserve the log interval covering:

```text
batch submission
→ task creation
→ asset resolution
→ render intent/timeline creation
→ render enqueue
→ FFmpeg/render completion
→ output path returned
```

Do not trim away task IDs, timestamps, asset IDs or output paths.