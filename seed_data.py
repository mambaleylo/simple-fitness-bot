"""
Скрипт для наполнения базы демо-контентом.
Запускать ОДИН РАЗ: python seed_data.py
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

# ========== ЗАКРЕПЛЁННЫЕ ТРЕНИРОВКИ ==========
permanent = [
    {
        "title": "🔥 Разминка — разогрев всего тела",
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
        "duration": 10,
        "order_num": 1,
    },
    {
        "title": "🧘 Заминка — растяжка после тренировки",
        "description": (
            "Заминка помогает восстановиться после нагрузки и повысить гибкость.\n\n"
            "Что включает:\n"
            "• Статическая растяжка всех групп мышц\n"
            "• Упражнения на восстановление дыхания\n"
            "• Расслабление и снятие напряжения\n\n"
            "Делай заминку после каждой тренировки — мышцы скажут спасибо! 💙"
        ),
        "video_url": "https://www.youtube.com/watch?v=4y7Jl0EWRrE",
        "duration": 10,
        "order_num": 2,
    },
    {
        "title": "💧 Питьевой режим и восстановление",
        "description": (
            "Базовые правила восстановления после тренировки:\n\n"
            "💧 Вода:\n"
            "• Пей 200–250 мл воды каждые 15–20 минут тренировки\n"
            "• После тренировки — минимум 400–500 мл\n\n"
            "🍌 Питание:\n"
            "• В течение 30–40 минут после тренировки съешь что-то лёгкое\n"
            "• Идеально: банан, творог, яйца или протеиновый коктейль\n\n"
            "😴 Сон:\n"
            "• Мышцы растут во сне — старайся спать 7–8 часов\n\n"
            "Следи за этими простыми правилами — и результат придёт быстрее! 🚀"
        ),
        "video_url": None,
        "duration": 5,
        "order_num": 3,
    },
]

# ========== ТРЕНИРОВКИ МЕСЯЦА ==========
# Имитируем добавление в разные дни (через разные added_at)
weekly = [
    # Неделя 1
    {
        "title": "🏃 Кардио стоя — без прыжков",
        "description": (
            "Эффективное кардио без прыжков — подходит даже для тех, кто живёт на верхних этажах!\n\n"
            "Что тебя ждёт:\n"
            "• Ходьба с высоким подниманием колен\n"
            "• Шаги в стороны с махами руками\n"
            "• Боковые касания\n"
            "• Марш на месте в ускоренном темпе\n\n"
            "🔥 Сжигаем до 200 ккал за тренировку!\n"
            "✅ Без инвентаря, без прыжков, без шума от соседей 😄"
        ),
        "video_url": "https://www.youtube.com/watch?v=DovFPtNm_Ms",
        "duration": 20,
        "week": 1,
        "days_ago": 21,
    },
    {
        "title": "🍑 Ягодицы и бёдра — базовый уровень",
        "description": (
            "Тренировка на ягодицы и бёдра для начинающих.\n\n"
            "Упражнения:\n"
            "• Приседания — 3 подхода по 15 раз\n"
            "• Выпады вперёд — 3×12 на каждую ногу\n"
            "• Ягодичный мостик — 3×20\n"
            "• Отведение ноги назад стоя — 3×15\n"
            "• Пульсирующие приседания — 2×30 сек\n\n"
            "💪 Выполняй упражнения медленно, чувствуй мышцы!\n"
            "🛑 Отдых между подходами — 30–45 секунд."
        ),
        "video_url": "https://www.youtube.com/watch?v=JFtx-7wnRaE",
        "duration": 25,
        "week": 1,
        "days_ago": 19,
    },
    # Неделя 2
    {
        "title": "💪 Верхняя часть тела — руки и спина",
        "description": (
            "Тренировка на руки, плечи и спину без гантелей.\n\n"
            "Программа:\n"
            "• Отжимания от пола (или от стены) — 3×10\n"
            "• Обратные отжимания от стула — 3×12\n"
            "• Планка с касанием плеч — 3×20\n"
            "• Супермен (подъём рук и ног лёжа) — 3×15\n"
            "• Разведение рук стоя с паузой — 3×20 сек\n\n"
            "🎯 Держи спину прямо во всех упражнениях!\n"
            "⏱️ Отдых 45 секунд между подходами."
        ),
        "video_url": "https://www.youtube.com/watch?v=7fQ-KkOKL7w",
        "duration": 25,
        "week": 2,
        "days_ago": 14,
    },
    {
        "title": "🔥 HIIT — интервальная жиросжигающая",
        "description": (
            "Высокоинтенсивная интервальная тренировка для максимального сжигания жира.\n\n"
            "Формат: 40 сек работа / 20 сек отдых, 4 круга\n\n"
            "Упражнения:\n"
            "• Берпи\n"
            "• Прыжки с расстановкой ног\n"
            "• Скалолаз\n"
            "• Прыжковые приседания\n"
            "• Бег на месте с высоким подниманием колен\n\n"
            "🔥 До 300 ккал за 20 минут!\n"
            "⚠️ Обязательно сделай разминку перед этой тренировкой!"
        ),
        "video_url": "https://www.youtube.com/watch?v=CHPKAbsPOo0",
        "duration": 20,
        "week": 2,
        "days_ago": 12,
    },
    # Неделя 3
    {
        "title": "🧘 Пилатес — пресс и кор",
        "description": (
            "Мягкая, но эффективная тренировка на пресс и глубокие мышцы кора.\n\n"
            "Программа:\n"
            "• Скручивания — 3×20\n"
            "• Подъём ног лёжа — 3×15\n"
            "• «Велосипед» — 3×30 сек\n"
            "• Планка на локтях — 3×30–60 сек\n"
            "• Боковая планка — 3×20 сек на каждую сторону\n"
            "• Мёртвый жук — 3×10 на каждую сторону\n\n"
            "💡 Следи за дыханием — выдох на усилие!\n"
            "🎯 Не торопись, качество важнее скорости."
        ),
        "video_url": "https://www.youtube.com/watch?v=rb3-BMof2lg",
        "duration": 30,
        "week": 3,
        "days_ago": 7,
    },
    {
        "title": "🏋️ Фулбоди — всё тело за 20 минут",
        "description": (
            "Комплексная тренировка на всё тело без инвентаря.\n\n"
            "Формат: 45 сек работа / 15 сек отдых\n\n"
            "Упражнения:\n"
            "• Приседания\n"
            "• Отжимания\n"
            "• Выпады с чередованием ног\n"
            "• Планка\n"
            "• Ягодичный мостик\n"
            "• Скалолаз\n"
            "• Прыжки на месте\n\n"
            "✅ Подходит для любого уровня подготовки!\n"
            "🔄 Повтори 3 круга с отдыхом 1 минуту между кругами."
        ),
        "video_url": "https://www.youtube.com/watch?v=JFtx-7wnRaE",
        "duration": 20,
        "week": 3,
        "days_ago": 5,
    },
    # Неделя 4 (текущая)
    {
        "title": "🦵 Ноги — приседания и выпады",
        "description": (
            "Интенсивная тренировка на ноги и ягодицы.\n\n"
            "Программа:\n"
            "• Приседания сумо — 4×15\n"
            "• Болгарские выпады — 3×12 на ногу\n"
            "• Приседания на одной ноге (пистолетик облегчённый) — 3×8\n"
            "• Зашагивания на стул — 3×12 на ногу\n"
            "• Ягодичный мостик на одной ноге — 3×15\n\n"
            "🔥 Эта тренировка будет ощущаться ещё 2 дня 😄\n"
            "💧 Не забудь выпить воду после!"
        ),
        "video_url": "https://www.youtube.com/watch?v=W0GL3u3Y-NQ",
        "duration": 35,
        "week": 4,
        "days_ago": 2,
    },
    {
        "title": "🌅 Утренняя зарядка — лёгкий старт",
        "description": (
            "Мягкая утренняя тренировка для бодрого начала дня.\n\n"
            "Идеально делать сразу после пробуждения!\n\n"
            "Комплекс:\n"
            "• Потягивания лёжа — 1 мин\n"
            "• Скручивания для позвоночника — 10 раз\n"
            "• Кошка-корова — 10 раз\n"
            "• Ходьба на месте — 3 мин\n"
            "• Лёгкие приседания — 2×10\n"
            "• Наклоны в стороны — 2×10\n\n"
            "☀️ 15 минут по утрам = полностью другое настроение на весь день!"
        ),
        "video_url": "https://www.youtube.com/watch?v=zMiUNIZZWMQ",
        "duration": 15,
        "week": 4,
        "days_ago": 0,
    },
]

# Вставляем постоянные тренировки
with get_db() as conn:

    for p in permanent:
        conn.execute(
            "INSERT INTO permanent_workouts (title, description, video_url, duration, order_num) VALUES (?,?,?,?,?)",
            (p["title"], p["description"], p["video_url"], p["duration"], p["order_num"])
        )
    print(f"✅ Добавлено закреплённых тренировок: {len(permanent)}")

    # Вставляем тренировки месяца с реальными датами добавления
    for w in weekly:
        added = (datetime.now() - timedelta(days=w["days_ago"])).date()
        conn.execute(
            "INSERT INTO weekly_workouts (title, description, video_url, duration, week_number, added_at) VALUES (?,?,?,?,?,?)",
            (w["title"], w["description"], w["video_url"], w["duration"], w["week"], str(added))
        )
    print(f"✅ Добавлено тренировок месяца: {len(weekly)}")

print("\n🎉 База данных наполнена демо-контентом!")
print("Запусти бот командой: python bot.py")
