import sqlite3
import os

# Phase 9.6.3 更名：全局共享库统一为 dopamatrix.db
DB_FILE = "dopamatrix.db"

def upgrade_db():
    if not os.path.exists(DB_FILE):
        print(f"❌ 找不到数据库文件: {DB_FILE}，如果是新环境，FastAPI 启动时会自动建表，无需此脚本。")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        cursor.execute("ALTER TABLE local_assets_inventory ADD COLUMN manifest JSON;")
        conn.commit()
        print("✅ 成功: 已向 local_assets_inventory 表追加 manifest 字段！")

    except sqlite3.OperationalError as e:
        # 如果报错，大概率是之前已经加过了
        print(f"⚠️ 提示: {e} (通常是因为字段或索引已存在，无需重复添加)")
    finally:
        conn.close()

if __name__ == "__main__":
    upgrade_db()