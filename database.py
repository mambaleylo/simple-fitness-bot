import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager

import os
DATA_DIR = os.getenv("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)
DB_NAME = os.path.join(DATA_DIR, "fitbot.db")


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
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                subscribed_until DATE,
                joined_at DATE DEFAULT CURRENT_DATE
            )
        ''')
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
        conn.execute('''
            CREATE TABLE IF NOT EXISTS weekly_workouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                video_url TEXT,
                duration INTEGER,
                week_number INTEGER,
                added_at DATE DEFAULT CURRENT_DATE,
                sent_at DATETIME DEFAULT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS completed_workouts (
                user_id INTEGER,
                workout_id INTEGER,
                workout_type TEXT,
                completed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, workout_id, workout_type)
            )
        ''')
        # Лекции по питанию — доступны всем бесплатно, без привязки к подписке
        conn.execute('''
            CREATE TABLE IF NOT EXISTS nutrition_lectures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                video_url TEXT,
                pdf_file_id TEXT,
                pdf_filename TEXT,
                pdf_url TEXT,
                gif_file_id TEXT,
                order_num INTEGER
            )
        ''')


def add_user(user_id, username):
    with get_db() as conn:
        conn.execute(
            'INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)',
            (user_id, username)
        )
        if username:
            conn.execute(
                'UPDATE users SET username=? WHERE user_id=?',
                (username, user_id)
            )


def get_all_users():
    with get_db() as conn:
        return conn.execute('SELECT * FROM users ORDER BY joined_at DESC').fetchall()


def activate_subscription(user_id, days=30):
    with get_db() as conn:
        row = conn.execute('SELECT subscribed_until FROM users WHERE user_id=?', (user_id,)).fetchone()
        if row and row['subscribed_until']:
            current_end = datetime.strptime(row['subscribed_until'], '%Y-%m-%d').date()
            if current_end >= datetime.now().date():
                new_end = current_end + timedelta(days=days)
            else:
                new_end = datetime.now().date() + timedelta(days=days)
        else:
            new_end = datetime.now().date() + timedelta(days=days)
        conn.execute('UPDATE users SET subscribed_until=? WHERE user_id=?', (str(new_end), user_id))


def is_subscribed(user_id):
    with get_db() as conn:
        row = conn.execute('SELECT subscribed_until FROM users WHERE user_id=?', (user_id,)).fetchone()
        if row and row['subscribed_until']:
            end = datetime.strptime(row['subscribed_until'], '%Y-%m-%d').date()
            return datetime.now().date() <= end
        return False


def get_subscription_days_left(user_id):
    with get_db() as conn:
        row = conn.execute('SELECT subscribed_until FROM users WHERE user_id=?', (user_id,)).fetchone()
        if row and row['subscribed_until']:
            end = datetime.strptime(row['subscribed_until'], '%Y-%m-%d').date()
            return max(0, (end - datetime.now().date()).days)
        return 0


def get_permanent_workouts():
    with get_db() as conn:
        return conn.execute('SELECT * FROM permanent_workouts ORDER BY order_num, id').fetchall()


def add_permanent_workout(title, description, video_url, duration):
    with get_db() as conn:
        row = conn.execute('SELECT COALESCE(MAX(order_num), 0) + 1 AS n FROM permanent_workouts').fetchone()
        order_num = row['n']
        conn.execute(
            'INSERT INTO permanent_workouts (title, description, video_url, duration, order_num) VALUES (?,?,?,?,?)',
            (title, description, video_url, duration, order_num)
        )


def get_permanent_workout(workout_id):
    with get_db() as conn:
        return conn.execute('SELECT * FROM permanent_workouts WHERE id=?', (workout_id,)).fetchone()


def update_permanent_workout(workout_id, field, value):
    with get_db() as conn:
        conn.execute(f'UPDATE permanent_workouts SET {field}=? WHERE id=?', (value, workout_id))


def delete_permanent_workout(workout_id):
    with get_db() as conn:
        conn.execute('DELETE FROM permanent_workouts WHERE id=?', (workout_id,))


def get_active_weekly_workouts():
    with get_db() as conn:
        month_ago = (datetime.now() - timedelta(days=30)).date()
        return conn.execute(
            'SELECT * FROM weekly_workouts WHERE added_at >= ? ORDER BY week_number, id',
            (str(month_ago),)
        ).fetchall()


def get_next_unsent_workout():
    """
    Возвращает следующую неотправленную тренировку (по очерёдности добавления).
    Используется планировщиком: вечером отправляется тренировка на завтра.
    """
    with get_db() as conn:
        month_ago = (datetime.now() - timedelta(days=30)).date()
        return conn.execute(
            'SELECT * FROM weekly_workouts WHERE added_at >= ? AND sent_at IS NULL ORDER BY id LIMIT 1',
            (str(month_ago),)
        ).fetchone()


def mark_workout_sent(workout_id):
    with get_db() as conn:
        conn.execute(
            'UPDATE weekly_workouts SET sent_at = CURRENT_TIMESTAMP WHERE id = ?',
            (workout_id,)
        )


def add_weekly_workouts(workouts_list):
    with get_db() as conn:
        week_num = datetime.now().isocalendar()[1]
        for w in workouts_list:
            conn.execute(
                'INSERT INTO weekly_workouts (title, description, video_url, duration, week_number) VALUES (?,?,?,?,?)',
                (w['title'], w['description'], w['video_url'], w['duration'], week_num)
            )


def cleanup_old_workouts():
    with get_db() as conn:
        month_ago = (datetime.now() - timedelta(days=30)).date()
        deleted = conn.execute(
            'DELETE FROM weekly_workouts WHERE added_at < ?', (str(month_ago),)
        ).rowcount
        return deleted


def get_weekly_workout(workout_id):
    with get_db() as conn:
        return conn.execute('SELECT * FROM weekly_workouts WHERE id=?', (workout_id,)).fetchone()


def update_weekly_workout(workout_id, field, value):
    with get_db() as conn:
        conn.execute(f'UPDATE weekly_workouts SET {field}=? WHERE id=?', (value, workout_id))


def delete_weekly_workout(workout_id):
    with get_db() as conn:
        conn.execute('DELETE FROM weekly_workouts WHERE id=?', (workout_id,))


def mark_workout_done(user_id, workout_id, workout_type):
    with get_db() as conn:
        conn.execute(
            'INSERT OR IGNORE INTO completed_workouts (user_id, workout_id, workout_type) VALUES (?,?,?)',
            (user_id, workout_id, workout_type)
        )


def has_completed_workout(user_id, workout_id, workout_type):
    with get_db() as conn:
        row = conn.execute(
            'SELECT 1 FROM completed_workouts WHERE user_id=? AND workout_id=? AND workout_type=?',
            (user_id, workout_id, workout_type)
        ).fetchone()
        return row is not None


# ========== ЛЕКЦИИ ПО ПИТАНИЮ (бесплатно, без подписки) ==========

def get_nutrition_lectures():
    with get_db() as conn:
        return conn.execute('SELECT * FROM nutrition_lectures ORDER BY order_num, id').fetchall()


def get_nutrition_lecture(lecture_id):
    with get_db() as conn:
        return conn.execute('SELECT * FROM nutrition_lectures WHERE id=?', (lecture_id,)).fetchone()


def add_nutrition_lecture(title, description, video_url, pdf_file_id=None, pdf_filename=None, pdf_url=None, gif_file_id=None):
    with get_db() as conn:
        row = conn.execute('SELECT COALESCE(MAX(order_num), 0) + 1 AS n FROM nutrition_lectures').fetchone()
        order_num = row['n']
        conn.execute(
            'INSERT INTO nutrition_lectures (title, description, video_url, pdf_file_id, pdf_filename, pdf_url, gif_file_id, order_num) VALUES (?,?,?,?,?,?,?,?)',
            (title, description, video_url, pdf_file_id, pdf_filename, pdf_url, gif_file_id, order_num)
        )


def update_nutrition_lecture(lecture_id, field, value):
    with get_db() as conn:
        conn.execute(f'UPDATE nutrition_lectures SET {field}=? WHERE id=?', (value, lecture_id))


def delete_nutrition_lecture(lecture_id):
    with get_db() as conn:
        conn.execute('DELETE FROM nutrition_lectures WHERE id=?', (lecture_id,))


init_db()
