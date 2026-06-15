import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager

DB_NAME = "fitbot.db"

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    """Создает все таблицы при первом запуске"""
    with get_db() as conn:
        # Пользователи и их подписка
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                subscribed_until DATE,
                joined_at DATE DEFAULT CURRENT_DATE
            )
        ''')
        
        # Закрепленные тренировки (всегда доступны)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS permanent_workouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                video_url TEXT,
                duration INTEGER,
                order_num INTEGER
            )
        ''')
        
        # Еженедельные тренировки (живут 1 месяц)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS weekly_workouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                video_url TEXT,
                duration INTEGER,
                week_number INTEGER,
                added_at DATE DEFAULT CURRENT_DATE
            )
        ''')
        
        # Выполненные тренировки (прогресс пользователя)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS completed_workouts (
                user_id INTEGER,
                workout_id INTEGER,
                workout_type TEXT, -- 'permanent' or 'weekly'
                completed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, workout_id, workout_type)
            )
        ''')

def add_user(user_id, username):
    """Добавляет нового пользователя"""
    with get_db() as conn:
        conn.execute(
            'INSERT OR IGNORE INTO users (user_id, username, subscribed_until) VALUES (?, ?, NULL)',
            (user_id, username)
        )

def activate_subscription(user_id, days=30):
    """Активирует подписку на N дней"""
    with get_db() as conn:
        until = (datetime.now() + timedelta(days=days)).date()
        conn.execute(
            'UPDATE users SET subscribed_until = ? WHERE user_id = ?',
            (until, user_id)
        )

def is_subscribed(user_id):
    """Проверяет активна ли подписка"""
    with get_db() as conn:
        result = conn.execute(
            'SELECT subscribed_until FROM users WHERE user_id = ?',
            (user_id,)
        ).fetchone()
        if result and result['subscribed_until']:
            return datetime.now().date() <= datetime.strptime(result['subscribed_until'], '%Y-%m-%d').date()
        return False

def get_subscription_days_left(user_id):
    """Сколько дней осталось по подписке"""
    with get_db() as conn:
        result = conn.execute(
            'SELECT subscribed_until FROM users WHERE user_id = ?',
            (user_id,)
        ).fetchone()
        if result and result['subscribed_until']:
            until = datetime.strptime(result['subscribed_until'], '%Y-%m-%d').date()
            left = (until - datetime.now().date()).days
            return max(0, left)
        return 0

def add_weekly_workouts(workouts_list):
    """Добавляет новые тренировки на неделю"""
    with get_db() as conn:
        # Получаем текущий номер недели года
        week_num = datetime.now().isocalendar()[1]
        for w in workouts_list:
            conn.execute('''
                INSERT INTO weekly_workouts (title, description, video_url, duration, week_number)
                VALUES (?, ?, ?, ?, ?)
            ''', (w['title'], w['description'], w['video_url'], w['duration'], week_num))

def get_active_weekly_workouts():
    """Получает тренировки текущего месяца"""
    with get_db() as conn:
        # Берем тренировки за последние 30 дней
        month_ago = (datetime.now() - timedelta(days=30)).date()
        return conn.execute('''
            SELECT * FROM weekly_workouts 
            WHERE added_at >= ? 
            ORDER BY week_number, id
        ''', (month_ago,)).fetchall()

def cleanup_old_workouts():
    """Удаляет тренировки старше месяца (вызывается автоматически)"""
    with get_db() as conn:
        month_ago = (datetime.now() - timedelta(days=30)).date()
        deleted = conn.execute(
            'DELETE FROM weekly_workouts WHERE added_at < ?',
            (month_ago,)
        ).rowcount
        print(f"🗑️ Удалено старых тренировок: {deleted}")
        return deleted

def get_permanent_workouts():
    """Все закрепленные тренировки (разминка, заминка и т.д.)"""
    with get_db() as conn:
        return conn.execute(
            'SELECT * FROM permanent_workouts ORDER BY order_num'
        ).fetchall()

def add_permanent_workout(title, description, video_url, duration, order_num):
    """Добавить закрепленную тренировку"""
    with get_db() as conn:
        conn.execute('''
            INSERT INTO permanent_workouts (title, description, video_url, duration, order_num)
            VALUES (?, ?, ?, ?, ?)
        ''', (title, description, video_url, duration, order_num))

def mark_workout_done(user_id, workout_id, workout_type):
    """Отмечает тренировку выполненной"""
    with get_db() as conn:
        conn.execute('''
            INSERT OR IGNORE INTO completed_workouts (user_id, workout_id, workout_type)
            VALUES (?, ?, ?)
        ''', (user_id, workout_id, workout_type))

def has_completed_workout(user_id, workout_id, workout_type):
    """Проверял ли пользователь эту тренировку"""
    with get_db() as conn:
        result = conn.execute('''
            SELECT 1 FROM completed_workouts 
            WHERE user_id = ? AND workout_id = ? AND workout_type = ?
        ''', (user_id, workout_id, workout_type)).fetchone()
        return result is not None

# Инициализация БД при импорте
init_db()
