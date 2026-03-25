import sqlite3
import os

# 这里请确认你当前 .env 里配置的实际数据库名（过渡期可能还是 clipflow.db）
DB_FILE = "clipflow.db" 

def upgrade_db():
    if not os.path.exists(DB_FILE):
        print(f"❌ 找不到数据库文件: {DB_FILE}，如果是新环境，FastAPI 启动时会自动建表，无需此脚本。")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        # 1. 强行插入新列
        cursor.execute("ALTER TABLE local_assets_inventory ADD COLUMN emotion_tag VARCHAR(50);")
        print("✅ 成功: 已向 local_assets_inventory 表追加 emotion_tag 字段！")
        
        # 2. 建立索引 (对应 models.py 里的 index=True)
        cursor.execute("CREATE INDEX ix_local_assets_inventory_emotion_tag ON local_assets_inventory (emotion_tag);")
        print("✅ 成功: 已为 emotion_tag 建立加速索引！")
        
        conn.commit()
    except sqlite3.OperationalError as e:
        # 如果报错，大概率是之前已经加过了
        print(f"⚠️ 提示: {e} (通常是因为字段或索引已存在，无需重复添加)")
    finally:
        conn.close()

if __name__ == "__main__":
    upgrade_db()