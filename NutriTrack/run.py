from app import create_app, db
from app.models.user import User
from sqlalchemy import text

# 创建Flask应用实例
app = create_app()

def _add_dish_created_by_column():
    """为已有数据库添加 dishes.created_by_user_id 列（仅首次需要）"""
    try:
        db.session.execute(text(
            "ALTER TABLE dishes ADD COLUMN created_by_user_id INTEGER NULL"
        ))
        db.session.commit()
        print("Added column dishes.created_by_user_id")
    except Exception as e:
        db.session.rollback()
        if "Duplicate column" in str(e) or "already exists" in str(e).lower():
            pass  # 列已存在
        else:
            print("Note: dishes.created_by_user_id may already exist or DB dialect differs:", e)

if __name__ == '__main__':
    with app.app_context():
        # Create tables if they don't exist
        db.create_all()
        _add_dish_created_by_column()

        # Create default admin if not exists
        if not User.query.filter_by(username='admin').first():
            print("Creating default admin user...")
            admin = User(username='admin', email='admin@example.com', is_admin=1)
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("Admin created: admin / admin123")

    app.run(
        host="0.0.0.0",  # 关键：允许所有内网IP访问（替代仅本机的127.0.0.1）
        port=5000,  # 显式指定端口（可选，Flask默认就是5000，写出来更清晰）
        debug=True  # 保留原有调试模式
    )