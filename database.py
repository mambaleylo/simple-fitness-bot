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
                media_file_id TEXT,
                media_type TEXT,
                order_num INTEGER
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS extra_materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                video_url TEXT,
                media_file_id TEXT,
                media_type TEXT,
                pdf_url TEXT,
                order_num INTEGER
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS body_params (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                weight REAL,
                chest REAL,
                waist REAL,
                hips REAL,
                arm REAL,
                thigh REAL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS body_params_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                weight REAL,
                chest REAL,
                waist REAL,
                hips REAL,
                arm REAL,
                thigh REAL,
                recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS progress_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                file_id TEXT,
                uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Миграции — добавляем недостающие колонки в уже существующие таблицы
        migrations = [
            ("nutrition_lectures", "pdf_url",    "ALTER TABLE nutrition_lectures ADD COLUMN pdf_url TEXT"),
            ("nutrition_lectures", "gif_file_id","ALTER TABLE nutrition_lectures ADD COLUMN gif_file_id TEXT"),
            ("nutrition_lectures", "media_file_id","ALTER TABLE nutrition_lectures ADD COLUMN media_file_id TEXT"),
            ("nutrition_lectures", "media_type","ALTER TABLE nutrition_lectures ADD COLUMN media_type TEXT"),
            ("nutrition_lectures", "pdf_filename","ALTER TABLE nutrition_lectures ADD COLUMN pdf_filename TEXT"),
            ("weekly_workouts",    "sent_at",    "ALTER TABLE weekly_workouts ADD COLUMN sent_at DATETIME DEFAULT NULL"),
        ]
        for table, col, sql in migrations:
            existing = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if col not in existing:
                conn.execute(sql)


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


def get_user_by_username(username: str):
    """Поиск пользователя по юзернейму (без @)."""
    username = username.lstrip('@').lower()
    with get_db() as conn:
        return conn.execute(
            'SELECT * FROM users WHERE LOWER(username)=?', (username,)
        ).fetchone()


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


PERMANENT_ALLOWED_FIELDS = {"title", "description", "video_url", "duration", "order_num"}

def update_permanent_workout(workout_id, field, value):
    if field not in PERMANENT_ALLOWED_FIELDS:
        raise ValueError(f"Недопустимое поле: {field}")
    with get_db() as conn:
        conn.execute(f'UPDATE permanent_workouts SET {field}=? WHERE id=?', (value, workout_id))


def delete_permanent_workout(workout_id):
    with get_db() as conn:
        conn.execute('DELETE FROM permanent_workouts WHERE id=?', (workout_id,))


def get_active_weekly_workouts():
    """Возвращает только уже отправленные тренировки — то что пользователь видит в меню."""
    with get_db() as conn:
        month_ago = (datetime.now() - timedelta(days=30)).date()
        return conn.execute(
            'SELECT * FROM weekly_workouts WHERE added_at >= ? AND sent_at IS NOT NULL ORDER BY sent_at DESC',
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
    """Удаляет только уже отправленные тренировки старше 30 дней.
    Неотправленные (sent_at IS NULL) не трогаем — они ещё в очереди."""
    with get_db() as conn:
        month_ago = (datetime.now() - timedelta(days=30)).date()
        deleted = conn.execute(
            'DELETE FROM weekly_workouts WHERE added_at < ? AND sent_at IS NOT NULL',
            (str(month_ago),)
        ).rowcount
        return deleted


def get_weekly_workout(workout_id):
    with get_db() as conn:
        return conn.execute('SELECT * FROM weekly_workouts WHERE id=?', (workout_id,)).fetchone()


WEEKLY_ALLOWED_FIELDS = {"title", "description", "video_url", "duration", "week_number", "sent_at"}

def update_weekly_workout(workout_id, field, value):
    if field not in WEEKLY_ALLOWED_FIELDS:
        raise ValueError(f"Недопустимое поле: {field}")
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


def add_nutrition_lecture(title, description, video_url, pdf_file_id=None, pdf_filename=None, pdf_url=None, gif_file_id=None, media_file_id=None, media_type=None):
    with get_db() as conn:
        row = conn.execute('SELECT COALESCE(MAX(order_num), 0) + 1 AS n FROM nutrition_lectures').fetchone()
        order_num = row['n']
        conn.execute(
            'INSERT INTO nutrition_lectures (title, description, video_url, pdf_file_id, pdf_filename, pdf_url, gif_file_id, media_file_id, media_type, order_num) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (title, description, video_url, pdf_file_id, pdf_filename, pdf_url, gif_file_id, media_file_id, media_type, order_num)
        )


LECTURE_ALLOWED_FIELDS = {"title", "description", "video_url", "pdf_file_id", "pdf_filename", "pdf_url", "gif_file_id", "media_file_id", "media_type", "order_num"}

def update_nutrition_lecture(lecture_id, field, value):
    if field not in LECTURE_ALLOWED_FIELDS:
        raise ValueError(f"Недопустимое поле: {field}")
    with get_db() as conn:
        conn.execute(f'UPDATE nutrition_lectures SET {field}=? WHERE id=?', (value, lecture_id))


def delete_nutrition_lecture(lecture_id):
    with get_db() as conn:
        conn.execute('DELETE FROM nutrition_lectures WHERE id=?', (lecture_id,))


init_db()


# ========== ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ (отдельный раздел, как лекции) ==========

def get_extra_materials():
    with get_db() as conn:
        return conn.execute('SELECT * FROM extra_materials ORDER BY order_num, id').fetchall()

def get_extra_material(material_id):
    with get_db() as conn:
        return conn.execute('SELECT * FROM extra_materials WHERE id=?', (material_id,)).fetchone()

def add_extra_material(title, description, video_url, media_file_id=None, media_type=None, pdf_url=None):
    with get_db() as conn:
        row = conn.execute('SELECT COALESCE(MAX(order_num), 0) + 1 AS n FROM extra_materials').fetchone()
        conn.execute(
            'INSERT INTO extra_materials (title, description, video_url, media_file_id, media_type, pdf_url, order_num) VALUES (?,?,?,?,?,?,?)',
            (title, description, video_url, media_file_id, media_type, pdf_url, row['n'])
        )

EXTRA_ALLOWED_FIELDS = {"title", "description", "video_url", "media_file_id", "media_type", "pdf_url", "order_num"}

def update_extra_material(material_id, field, value):
    if field not in EXTRA_ALLOWED_FIELDS:
        raise ValueError(f"Недопустимое поле: {field}")
    with get_db() as conn:
        conn.execute(f'UPDATE extra_materials SET {field}=? WHERE id=?', (value, material_id))

def delete_extra_material(material_id):
    with get_db() as conn:
        conn.execute('DELETE FROM extra_materials WHERE id=?', (material_id,))


# ========== ПАРАМЕТРЫ ТЕЛА ==========

def save_body_params(user_id, params: dict):
    """Сохраняет замеры тела и добавляет запись в историю."""
    with get_db() as conn:
        existing = conn.execute('SELECT id FROM body_params WHERE user_id=?', (user_id,)).fetchone()
        if existing:
            sets = ', '.join(f'{k}=?' for k in params)
            conn.execute(f'UPDATE body_params SET {sets}, updated_at=CURRENT_TIMESTAMP WHERE user_id=?',
                        list(params.values()) + [user_id])
        else:
            fields = ', '.join(['user_id'] + list(params.keys()))
            placeholders = ', '.join(['?'] * (1 + len(params)))
            conn.execute(f'INSERT INTO body_params ({fields}) VALUES ({placeholders})',
                        [user_id] + list(params.values()))
        # Сохраняем в историю
        h_fields = ', '.join(['user_id'] + list(params.keys()))
        h_placeholders = ', '.join(['?'] * (1 + len(params)))
        conn.execute(f'INSERT INTO body_params_history ({h_fields}) VALUES ({h_placeholders})',
                    [user_id] + list(params.values()))


def get_body_params_history(user_id, limit=5):
    """Возвращает последние N записей истории параметров."""
    with get_db() as conn:
        return conn.execute(
            'SELECT * FROM body_params_history WHERE user_id=? ORDER BY recorded_at DESC LIMIT ?',
            (user_id, limit)
        ).fetchall()

def get_body_params(user_id):
    with get_db() as conn:
        return conn.execute('SELECT * FROM body_params WHERE user_id=?', (user_id,)).fetchone()

def save_progress_photo(user_id, file_id):
    """Добавляет новое фото прогресса (история сохраняется)."""
    with get_db() as conn:
        conn.execute('INSERT INTO progress_photos (user_id, file_id) VALUES (?,?)', (user_id, file_id))

def get_progress_photo(user_id):
    """Возвращает последнее загруженное фото."""
    with get_db() as conn:
        return conn.execute(
            'SELECT * FROM progress_photos WHERE user_id=? ORDER BY uploaded_at DESC LIMIT 1',
            (user_id,)
        ).fetchone()

def get_progress_photos(user_id, limit=10):
    """Возвращает все фото прогресса (от новых к старым)."""
    with get_db() as conn:
        return conn.execute(
            'SELECT * FROM progress_photos WHERE user_id=? ORDER BY uploaded_at DESC LIMIT ?',
            (user_id, limit)
        ).fetchall()
