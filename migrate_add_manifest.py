"""
migrate_add_manifest.py
───────────────────────
Phase 9.6.1 DB Patch — 无损热升级：为 local_assets_inventory 追加 manifest 列。

支持多租户架构：自动扫描 data/ 目录下所有 dopamatrix_*.db 文件并逐一升级。
幂等安全：若列已存在，优雅跳过，不影响任何现有数据。

运行方式（从项目根目录执行）：
    python migrate_add_manifest.py
"""

import glob
import os
import sqlite3
import sys

# Windows 终端强制 UTF-8 输出，避免 emoji 引发 GBK 编码错误
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_PATCHES: list[tuple[str, str, str]] = [
    # (table, column, column_ddl_type)
    ("local_assets_inventory", "manifest",       "TEXT"),
    ("task_history",           "prompt_details", "TEXT"),  # Phase 9.11.4: beats JSON 台词回显
]


def _apply_patch(conn: sqlite3.Connection, label: str, table: str, column: str, col_type: str) -> None:
    try:
        conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {col_type}')
        conn.commit()
        print(f"  🚀 [{label}] {table}.{column} 热升级成功！")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print(f"  ✅ [{label}] {table}.{column} 已存在，跳过")
        elif "no such table" in str(e).lower():
            print(f"  ⏭️  [{label}] 表 {table} 不存在（旧库无此表），跳过")
        else:
            print(f"  ❌ [{label}] {table}.{column} 迁移失败：{e}")


def migrate_db(db_path: str) -> None:
    label = os.path.basename(db_path)
    try:
        conn = sqlite3.connect(db_path)
        for table, column, col_type in _PATCHES:
            _apply_patch(conn, label, table, column, col_type)
        conn.close()
    except Exception as e:
        print(f"  ❌ [{label}] 未知错误：{e}")


def main() -> None:
    # 从脚本所在目录（项目根）定位 data/ 文件夹
    root     = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(root, "data")

    db_files = sorted(glob.glob(os.path.join(data_dir, "dopamatrix_*.db")))

    if not db_files:
        print(f"⚠️  在 {data_dir} 下未找到任何租户数据库文件，无需迁移。")
        print("    （首次启动后将由 evolve_schema 自动处理新建数据库。）")
        return

    print(f"🔍 发现 {len(db_files)} 个租户数据库，开始迁移...\n")
    for db_path in db_files:
        migrate_db(db_path)

    print("\n✨ 全部迁移任务完成。")


if __name__ == "__main__":
    main()
