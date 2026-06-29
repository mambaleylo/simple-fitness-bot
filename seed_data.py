"""
Скрипт для наполнения базы демо-контентом.
Запускать: python seed_data.py
Ничего не удаляет — только добавляет, можно запускать повторно.
"""
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

# Таблицы (на случай если БД пустая)
with get_db() as conn:
    conn.execute('''CREATE TABLE IF NOT EXISTS permanent_workouts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
        description TEXT, video_url TEXT, duration INTEGER, order_num INTEGER)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS weekly_workouts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
        description TEXT, video_url TEXT, duration INTEGER,
        week_number INTEGER, added_at DATE DEFAULT CURRENT_DATE)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT,
        subscribed_until DATE, joined_at DATE DEFAULT CURRENT_DATE)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS completed_workouts (
        user_id INTEGER, workout_id INTEGER, workout_type TEXT,
        completed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, workout_id, workout_type))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS nutrition_lectures (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
        description TEXT, video_url TEXT, pdf_file_id TEXT,
        pdf_filename TEXT, order_num INTEGER)''')

# ========== ЗАКРЕПЛЁННЫЕ ТРЕНИРОВКИ (5 штук, по ТЗ заказчика) ==========
permanent = [
    {
        "title": "🔥 Разминка",
        "description": (
            "Обязательная разминка перед любой тренировкой.\n\n"
            "Разогревает мышцы, подготавливает суставы и снижает риск травм.\n\n"
            "Комплекс включает:\n"
            "• Вращения головой, плечами, тазом\n"
            "• Динамические выпады\n"
            "• Махи руками и ногами\n"
            "• Лёгкие прыжки на месте\n\n"
            "⚠️ Не пропускай разминку — это основа безопасной тренировки!"
        ),
        "video_url": "https://www.youtube.com/watch?v=zg0RsSTTovA",
        "duration": 10, "order_num": 1,
    },
    {
        "title": "🧘 Заминка",
        "description": (
            "Заминка помогает восстановиться после нагрузки и повысить гибкость.\n\n"
            "Что включает:\n"
            "• Статическая растяжка всех групп мышц\n"
            "• Упражнения на восстановление дыхания\n"
            "• Расслабление и снятие напряжения\n\n"
            "Делай заминку после каждой тренировки — мышцы скажут спасибо! 💙"
        ),
        "video_url": "https://www.youtube.com/watch?v=4y7Jl0EWRrE",
        "duration": 10, "order_num": 2,
    },
    {
        "title": "🌬️ Дыхание",
        "description": (
            "Дыхательная гимнастика для восстановления и улучшения самочувствия.\n\n"
            "Помогает:\n"
            "• Снизить уровень стресса\n"
            "• Улучшить работу лёгких\n"
            "• Быстрее восстановиться после тренировки\n"
            "• Насытить организм кислородом\n\n"
            "🧘 Делай эту практику в любое время дня, когда нужно успокоиться или восстановить силы."
        ),
        "video_url": "https://www.youtube.com/watch?v=Ec06NY2weyc",
        "duration": 12, "order_num": 3,
    },
    {
        "title": "💗 Тазовое дно",
        "description": (
            "Упражнения для укрепления мышц тазового дна.\n\n"
            "Полезны для:\n"
            "• Профилактики недержания\n"
            "• Восстановления после родов\n"
            "• Улучшения общего тонуса мышц низа живота\n"
            "• Поддержки внутренних органов\n\n"
            "💡 Выполняй медленно и осознанно, без задержки дыхания.\n"
            "⚠️ При болях или дискомфорте — проконсультируйся с врачом."
        ),
        "video_url": "https://www.youtube.com/watch?v=I4KoeOsVUwg",
        "duration": 10, "order_num": 4,
    },
    {
        "title": "⚡ Зарядка",
        "description": (
            "Лёгкая утренняя зарядка для бодрого начала дня.\n\n"
            "Идеально делать сразу после пробуждения!\n\n"
            "Комплекс:\n"
            "• Потягивания лёжа — 1 мин\n"
            "• Скручивания для позвоночника — 10 раз\n"
            "• Кошка-корова — 10 раз\n"
            "• Ходьба на месте — 3 мин\n"
            "• Лёгкие приседания — 2×10\n"
            "• Наклоны в стороны — 2×10\n\n"
            "☀️ 15 минут по утрам = другое настроение на весь день!"
        ),
        "video_url": "https://www.youtube.com/watch?v=zMiUNIZZWMQ",
        "duration": 15, "order_num": 5,
    },
]

# ========== ЛЕКЦИИ ПО ПИТАНИЮ (3 штуки, бесплатно, без подписки) ==========
lectures = [
    {
        "title": "Лекция 1: Основы правильного питания",
        "description": (
            "Базовые принципы сбалансированного питания.\n\n"
            "В лекции:\n"
            "• Что такое БЖУ и зачем считать калории\n"
            "• Как составить рацион на день\n"
            "• Частые ошибки в питании\n"
            "• Питьевой режим\n\n"
            "🍎 Эта лекция — фундамент для всех остальных материалов по питанию."
        ),
        "video_url": None,
        "order_num": 1,
    },
    {
        "title": "Лекция 2: Питание до и после тренировки",
        "description": (
            "Как питаться, чтобы тренировки давали максимальный результат.\n\n"
            "В лекции:\n"
            "• Что съесть перед тренировкой\n"
            "• Питание в окно после тренировки\n"
            "• Можно ли тренироваться натощак\n"
            "• Примеры лёгких перекусов\n\n"
            "💪 Правильное питание усиливает эффект от тренировок в разы!"
        ),
        "video_url": None,
        "order_num": 2,
    },
    {
        "title": "Лекция 3: Срывы и как с ними справляться",
        "description": (
            "Психология питания и работа со срывами.\n\n"
            "В лекции:\n"
            "• Почему случаются срывы и как их избежать\n"
            "• Как вернуться в режим без чувства вины\n"
            "• Гибкий подход к питанию вместо жёстких диет\n"
            "• Долгосрочная мотивация\n\n"
            "🧠 Питание — это не только про еду, но и про отношения с собой."
        ),
        "video_url": None,
        "order_num": 3,
    },
    {
        "title": "💧 Питьевой режим",
        "description": (
            "Базовые правила питьевого режима для тренирующихся.\n\n"
            "• Пей 200–250 мл воды каждые 15–20 минут тренировки\n"
            "• После тренировки — минимум 400–500 мл\n"
            "• Ориентируйся на чувство жажды и цвет мочи\n"
            "• Утром натощак — стакан воды для запуска организма\n\n"
            "💧 Вода — основа восстановления и хорошего самочувствия."
        ),
        "video_url": None,
        "order_num": 4,
    },
    {
        "title": "📋 Ориентир-план питания",
        "description": (
            "Примерный план питания на день — просто как ориентир.\n\n"
            "⚠️ Не нужно строго следовать этому плану — он может быть "
            "помощником в первое время, чтобы понять общий принцип построения рациона.\n\n"
            "PDF-файл с примерным планом загружается отдельно через /admin."
        ),
        "video_url": None,
        "order_num": 5,
    },
]

with get_db() as conn:
    for p in permanent:
        conn.execute(
            "INSERT INTO permanent_workouts (title, description, video_url, duration, order_num) VALUES (?,?,?,?,?)",
            (p["title"], p["description"], p["video_url"], p["duration"], p["order_num"])
        )
    print(f"✅ Добавлено закреплённых тренировок: {len(permanent)}")

    for lec in lectures:
        conn.execute(
            "INSERT INTO nutrition_lectures (title, description, video_url, pdf_file_id, pdf_filename, order_num) VALUES (?,?,?,?,?,?)",
            (lec["title"], lec["description"], lec["video_url"], None, None, lec["order_num"])
        )
    print(f"✅ Добавлено лекций по питанию: {len(lectures)}")
    print("   (PDF-файлы к лекциям нужно добавить через /admin → 'Добавить лекцию по питанию',")
    print("    либо прикрепить вручную через бота — текстом отправлять PDF нельзя)")

print("\n🎉 База данных наполнена демо-контентом!")
print("Запусти бот командой: python bot.py")
