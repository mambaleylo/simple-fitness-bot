import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, SCHEDULE_DAYS, SCHEDULE_TIME
from database import *

# Настройка бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Состояния для FSM (ожидание ввода)
class AddWorkoutState(StatesGroup):
    waiting_for_title = State()
    waiting_for_description = State()
    waiting_for_url = State()
    waiting_for_duration = State()

# ========== КЛАВИАТУРЫ ==========
def main_menu(user_id=None):
    """Главное меню (меняется если есть подписка)"""
    buttons = [
        [InlineKeyboardButton(text="🏋️ Закрепленные тренировки", callback_data="permanent")],
    ]
    
    if user_id and is_subscribed(user_id):
        buttons.append([InlineKeyboardButton(text="📅 Активные тренировки", callback_data="weekly")])
        days = get_subscription_days_left(user_id)
        buttons.append([InlineKeyboardButton(text=f"⭐ Подписка активна ({days} дн.)", callback_data="subscription_info")])
    else:
        buttons.append([InlineKeyboardButton(text="💎 Купить подписку", callback_data="buy_subscription")])
    
    buttons.append([InlineKeyboardButton(text="📊 Мой прогресс", callback_data="progress")])
    buttons.append([InlineKeyboardButton(text="❓ Помощь", callback_data="help")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def workout_list_keyboard(workouts, workout_type):
    """Клавиатура со списком тренировок"""
    buttons = []
    for w in workouts:
        status = "✅ " if has_completed_workout(user_id, w['id'], workout_type) else "◻️ "
        buttons.append([InlineKeyboardButton(
            text=f"{status}{w['title']} ({w['duration']} мин)",
            callback_data=f"workout_{workout_type}_{w['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    
    add_user(user_id, username)
    
    await message.answer(
        f"🔥 Привет, {message.from_user.first_name}!\n\n"
        f"Я твой персональный фитнес-тренер.\n"
        f"Каждую неделю я выдаю новые тренировки по расписанию.\n"
        f"Доступны постоянные тренировки (разминка, заминка) и ежемесячный контент.\n\n"
        f"⬇️ Выбери действие в меню:",
        reply_markup=main_menu(user_id)
    )

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📋 Главное меню:",
        reply_markup=main_menu(callback.from_user.id)
    )
    await callback.answer()

@dp.callback_query(F.data == "permanent")
async def show_permanent(callback: types.CallbackQuery):
    workouts = get_permanent_workouts()
    if not workouts:
        await callback.message.edit_text("📭 Пока нет закрепленных тренировок.", reply_markup=main_menu(callback.from_user.id))
        await callback.answer()
        return
    
    await callback.message.edit_text(
        "🏋️ **Закрепленные тренировки** (доступны всегда):\n\n" +
        "\n".join([f"• {w['title']} — {w['duration']} мин" for w in workouts]),
        reply_markup=workout_list_keyboard(workouts, "permanent")
    )
    await callback.answer()

@dp.callback_query(F.data == "weekly")
async def show_weekly(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_subscribed(user_id):
        await callback.answer("❌ Подписка не активна! Купите подписку для доступа.", show_alert=True)
        return
    
    workouts = get_active_weekly_workouts()
    if not workouts:
        await callback.message.edit_text(
            "📭 Новые тренировки появятся на этой неделе!\n\n"
            "Следи за расписанием — они приходят автоматически.",
            reply_markup=main_menu(user_id)
        )
        await callback.answer()
        return
    
    await callback.message.edit_text(
        "📅 **Активные тренировки этого месяца:**\n\n" +
        "\n".join([f"• {w['title']} — {w['duration']} мин (неделя {w['week_number']})" for w in workouts]),
        reply_markup=workout_list_keyboard(workouts, "weekly")
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("workout_"))
async def show_workout(callback: types.CallbackQuery):
    _, workout_type, workout_id = callback.data.split("_")
    workout_id = int(workout_id)
    
    if workout_type == "permanent":
        workouts = get_permanent_workouts()
    else:
        if not is_subscribed(callback.from_user.id):
            await callback.answer("❌ Подписка не активна!", show_alert=True)
            return
        workouts = get_active_weekly_workouts()
    
    workout = next((w for w in workouts if w['id'] == workout_id), None)
    if not workout:
        await callback.answer("Тренировка не найдена")
        return
    
    completed_status = "✅ Вы уже выполнили эту тренировку\n\n" if has_completed_workout(callback.from_user.id, workout_id, workout_type) else ""
    
    text = f"🏋️ **{workout['title']}**\n\n{completed_status}"
    text += f"📝 {workout['description']}\n\n"
    text += f"⏱️ Длительность: {workout['duration']} минут\n"
    if workout['video_url']:
        text += f"\n🎥 Видео: {workout['video_url']}"
    
    buttons = []
    if not has_completed_workout(callback.from_user.id, workout_id, workout_type):
        buttons.append([InlineKeyboardButton(text="✅ Отметить выполненным", callback_data=f"complete_{workout_type}_{workout_id}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=workout_type if workout_type == "permanent" else "weekly")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith("complete_"))
async def complete_workout(callback: types.CallbackQuery):
    _, workout_type, workout_id = callback.data.split("_")
    workout_id = int(workout_id)
    
    if not is_subscribed(callback.from_user.id) and workout_type == "weekly":
        await callback.answer("❌ Подписка не активна!", show_alert=True)
        return
    
    if has_completed_workout(callback.from_user.id, workout_id, workout_type):
        await callback.answer("Вы уже отмечали эту тренировку", show_alert=True)
        return
    
    mark_workout_done(callback.from_user.id, workout_id, workout_type)
    await callback.answer("✅ Отлично! Тренировка отмечена. Так держать!", show_alert=True)
    await show_workout(callback)

@dp.callback_query(F.data == "progress")
async def show_progress(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    permanent_done = 0
    weekly_done = 0
    
    # Считаем выполненные тренировки
    with get_db() as conn:
        permanent_done = conn.execute(
            'SELECT COUNT(*) FROM completed_workouts WHERE user_id = ? AND workout_type = "permanent"',
            (user_id,)
        ).fetchone()[0]
        weekly_done = conn.execute(
            'SELECT COUNT(*) FROM completed_workouts WHERE user_id = ? AND workout_type = "weekly"',
            (user_id,)
        ).fetchone()[0]
    
    text = f"📊 **Твой прогресс**\n\n"
    text += f"🏋️ Выполнено постоянных тренировок: {permanent_done}\n"
    if is_subscribed(user_id):
        text += f"📅 Выполнено еженедельных: {weekly_done}\n"
        text += f"⏳ Осталось дней подписки: {get_subscription_days_left(user_id)}\n"
    else:
        text += f"\n💎 Купи подписку, чтобы получить доступ к новым тренировкам!"
    
    await callback.message.edit_text(text, reply_markup=main_menu(user_id))
    await callback.answer()

@dp.callback_query(F.data == "buy_subscription")
async def buy_subscription(callback: types.CallbackQuery):
    text = "💎 **Подписка на фитнес-бот**\n\n"
    text += "Цена: 500 ₽ / месяц\n\n"
    text += "Что ты получишь:\n"
    text += "• Новые тренировки каждую неделю\n"
    text += "• Доступ ко всем материалам месяца\n"
    text += "• Автоматическое обновление контента\n\n"
    text += "⚡ Оплата: (нужно подключить платежную систему)\n"
    text += "Пока что напишите @admin для активации"
    
    buttons = [[InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data == "subscription_info")
async def sub_info(callback: types.CallbackQuery):
    days = get_subscription_days_left(callback.from_user.id)
    await callback.answer(f"Осталось дней подписки: {days}", show_alert=True)

@dp.callback_query(F.data == "help")
async def show_help(callback: types.CallbackQuery):
    text = "❓ **Помощь**\n\n"
    text += "Как пользоваться ботом:\n"
    text += "1. В меню выбери тип тренировок\n"
    text += "2. Нажми на тренировку для просмотра\n"
    text += "3. После выполнения отметь ее ✅\n\n"
    text += "📅 Новые тренировки приходят по расписанию:\n"
    text += f"• Дни: {', '.join(['ПН','ВТ','СР','ЧТ','ПТ','СБ','ВС'][d] for d in SCHEDULE_DAYS)}\n"
    text += f"• Время: {SCHEDULE_TIME}\n\n"
    text += "🔄 Каждый месяц старые тренировки удаляются"
    
    await callback.message.edit_text(text, reply_markup=main_menu(callback.from_user.id))
    await callback.answer()

# ========== АДМИНСКИЕ КОМАНДЫ (только для владельца) ==========
ADMIN_IDS = [181970023]  # ВСТАВЬ СВОЙ TELEGRAM ID

@dp.message(Command("add_permanent"))
async def add_permanent_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Недостаточно прав")
        return
    await state.set_state(AddWorkoutState.waiting_for_title)
    await message.answer("Введи название закрепленной тренировки:")

@dp.message(AddWorkoutState.waiting_for_title)
async def add_permanent_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddWorkoutState.waiting_for_description)
    await message.answer("Введи описание:")

@dp.message(AddWorkoutState.waiting_for_description)
async def add_permanent_desc(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(AddWorkoutState.waiting_for_url)
    await message.answer("Введи ссылку на видео (или 'нет'):")

@dp.message(AddWorkoutState.waiting_for_url)
async def add_permanent_url(message: types.Message, state: FSMContext):
    url = None if message.text.lower() == 'нет' else message.text
    await state.update_data(video_url=url)
    await state.set_state(AddWorkoutState.waiting_for_duration)
    await message.answer("Введи длительность в минутах:")

@dp.message(AddWorkoutState.waiting_for_duration)
async def add_permanent_duration(message: types.Message, state: FSMContext):
    try:
        duration = int(message.text)
        data = await state.get_data()
        
        with get_db() as conn:
            # Получаем следующий order_num
            result = conn.execute('SELECT COALESCE(MAX(order_num), 0) + 1 as next FROM permanent_workouts').fetchone()
            order_num = result['next']
            conn.execute(
                'INSERT INTO permanent_workouts (title, description, video_url, duration, order_num) VALUES (?, ?, ?, ?, ?)',
                (data['title'], data['description'], data['video_url'], duration, order_num)
            )
        
        await message.answer(f"✅ Закрепленная тренировка '{data['title']}' добавлена!")
        await state.clear()
    except ValueError:
        await message.answer("❌ Введи число (минуты)")

@dp.message(Command("add_weekly"))
async def add_weekly(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Недостаточно прав")
        return
    # Формат: /add_weekly Название | Описание | url | 15
    try:
        parts = message.text.split("|")
        if len(parts) < 4:
            await message.answer("❌ Формат: /add_weekly Название | Описание | url | минуты")
            return
        
        title = parts[0].replace("/add_weekly", "").strip()
        description = parts[1].strip()
        url = parts[2].strip()
        duration = int(parts[3].strip())
        
        add_weekly_workouts([{
            'title': title,
            'description': description,
            'video_url': url if url != 'нет' else None,
            'duration': duration
        }])
        await message.answer(f"✅ Добавлена недельная тренировка: {title}")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# ========== ЗАПУСК ==========
async def main():
    print("🤖 Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
