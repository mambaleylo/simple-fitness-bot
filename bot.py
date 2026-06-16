import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, SCHEDULE_DAYS, SCHEDULE_TIME, ADMIN_IDS
from database import (
    add_user, is_subscribed, get_subscription_days_left,
    activate_subscription, get_permanent_workouts, get_active_weekly_workouts,
    has_completed_workout, mark_workout_done, cleanup_old_workouts,
    add_weekly_workouts, add_permanent_workout, get_all_users, get_db
)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")


# ========== FSM STATES ==========

class AddPermanentState(StatesGroup):
    title = State()
    description = State()
    url = State()
    duration = State()

class AddWeeklyState(StatesGroup):
    title = State()
    description = State()
    url = State()
    duration = State()

class BroadcastState(StatesGroup):
    text = State()


# ========== KEYBOARDS ==========

def main_menu(user_id=None):
    buttons = [
        [InlineKeyboardButton(text="🏋️ Закреплённые тренировки", callback_data="permanent")],
    ]
    if user_id and is_subscribed(user_id):
        days = get_subscription_days_left(user_id)
        buttons.append([InlineKeyboardButton(text="📅 Тренировки месяца", callback_data="weekly")])
        buttons.append([InlineKeyboardButton(text=f"⭐ Подписка активна ({days} дн.)", callback_data="sub_info")])
    else:
        buttons.append([InlineKeyboardButton(text="💎 Купить подписку", callback_data="buy_sub")])
    buttons.append([InlineKeyboardButton(text="📊 Мой прогресс", callback_data="progress")])
    buttons.append([InlineKeyboardButton(text="❓ Помощь", callback_data="help")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def workout_list_keyboard(workouts, workout_type, user_id):
    buttons = []
    for w in workouts:
        done = has_completed_workout(user_id, w["id"], workout_type)
        status = "✅ " if done else "◻️ "
        buttons.append([InlineKeyboardButton(
            text=f"{status}{w['title']} ({w['duration']} мин)",
            callback_data=f"wk:{workout_type}:{w['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_keyboard(target="back"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=target)]
    ])


# ========== COMMANDS ==========

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    add_user(uid, message.from_user.username)
    await message.answer(
        f"🔥 Привет, {message.from_user.first_name}!\n\n"
        "Я твой персональный фитнес-тренер.\n"
        "Каждую неделю выходят новые тренировки по расписанию.\n"
        "Постоянные материалы (разминка, заминка и др.) доступны всегда.\n\n"
        "⬇️ Выбери действие:",
        reply_markup=main_menu(uid)
    )


# ========== MAIN MENU CALLBACKS ==========

@dp.callback_query(F.data == "back")
async def cb_back(callback: types.CallbackQuery):
    await callback.message.edit_text("📋 Главное меню:", reply_markup=main_menu(callback.from_user.id))
    await callback.answer()


@dp.callback_query(F.data == "permanent")
async def cb_permanent(callback: types.CallbackQuery):
    uid = callback.from_user.id
    workouts = get_permanent_workouts()
    if not workouts:
        await callback.message.edit_text(
            "📭 Закреплённых тренировок пока нет.\n\nАдмин добавит их командой /add_permanent",
            reply_markup=back_keyboard()
        )
        await callback.answer()
        return
    text = "🏋️ <b>Закреплённые тренировки</b> (доступны всегда):\n\n"
    text += "\n".join(f"• {w['title']} — {w['duration']} мин" for w in workouts)
    await callback.message.edit_text(
        text,
        reply_markup=workout_list_keyboard(workouts, "permanent", uid),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "weekly")
async def cb_weekly(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if not is_subscribed(uid):
        await callback.answer("❌ Подписка не активна! Купите доступ.", show_alert=True)
        return
    workouts = get_active_weekly_workouts()
    if not workouts:
        await callback.message.edit_text(
            "📭 Тренировки этого месяца ещё не добавлены.\n\n"
            "Они появляются по расписанию: ПН, СР, ПТ в 10:00.",
            reply_markup=back_keyboard()
        )
        await callback.answer()
        return
    text = "📅 <b>Тренировки этого месяца:</b>\n\n"
    text += "\n".join(
        f"• {w['title']} — {w['duration']} мин (неделя {w['week_number']})" for w in workouts
    )
    await callback.message.edit_text(
        text,
        reply_markup=workout_list_keyboard(workouts, "weekly", uid),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("wk:"))
async def cb_show_workout(callback: types.CallbackQuery):
    _, workout_type, wid_str = callback.data.split(":", 2)
    workout_id = int(wid_str)
    uid = callback.from_user.id

    if workout_type == "permanent":
        workouts = get_permanent_workouts()
    else:
        if not is_subscribed(uid):
            await callback.answer("❌ Подписка не активна!", show_alert=True)
            return
        workouts = get_active_weekly_workouts()

    workout = next((w for w in workouts if w["id"] == workout_id), None)
    if not workout:
        await callback.answer("Тренировка не найдена")
        return

    done = has_completed_workout(uid, workout_id, workout_type)
    text = f"🏋️ <b>{workout['title']}</b>\n\n"
    if done:
        text += "✅ <i>Вы уже выполнили эту тренировку</i>\n\n"
    text += f"📝 {workout['description']}\n\n"
    text += f"⏱️ Длительность: {workout['duration']} мин\n"
    if workout["video_url"]:
        text += f"\n🎥 <a href=\"{workout['video_url']}\">Смотреть видео</a>"

    buttons = []
    if not done:
        buttons.append([InlineKeyboardButton(
            text="✅ Отметить выполненным",
            callback_data=f"done:{workout_type}:{workout_id}"
        )])
    back_target = "permanent" if workout_type == "permanent" else "weekly"
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=back_target)])

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("done:"))
async def cb_complete(callback: types.CallbackQuery):
    _, workout_type, wid_str = callback.data.split(":", 2)
    workout_id = int(wid_str)
    uid = callback.from_user.id

    if workout_type == "weekly" and not is_subscribed(uid):
        await callback.answer("❌ Подписка не активна!", show_alert=True)
        return
    if has_completed_workout(uid, workout_id, workout_type):
        await callback.answer("Уже отмечено ранее.", show_alert=True)
        return

    mark_workout_done(uid, workout_id, workout_type)
    await callback.answer("✅ Отлично! Тренировка засчитана!", show_alert=True)
    # Обновить экран тренировки
    callback.data = f"wk:{workout_type}:{workout_id}"
    await cb_show_workout(callback)


@dp.callback_query(F.data == "progress")
async def cb_progress(callback: types.CallbackQuery):
    uid = callback.from_user.id
    with get_db() as conn:
        perm = conn.execute(
            'SELECT COUNT(*) FROM completed_workouts WHERE user_id=? AND workout_type="permanent"', (uid,)
        ).fetchone()[0]
        week = conn.execute(
            'SELECT COUNT(*) FROM completed_workouts WHERE user_id=? AND workout_type="weekly"', (uid,)
        ).fetchone()[0]

    text = "📊 <b>Твой прогресс</b>\n\n"
    text += f"🏋️ Постоянных тренировок выполнено: <b>{perm}</b>\n"
    if is_subscribed(uid):
        text += f"📅 Тренировок месяца выполнено: <b>{week}</b>\n"
        text += f"⏳ Осталось дней подписки: <b>{get_subscription_days_left(uid)}</b>\n"
    else:
        text += "\n💎 Купи подписку, чтобы получить доступ к новым тренировкам!"

    await callback.message.edit_text(text, reply_markup=back_keyboard(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "buy_sub")
async def cb_buy_sub(callback: types.CallbackQuery):
    text = (
        "💎 <b>Подписка на фитнес-бот</b>\n\n"
        "Цена: <b>500 ₽ / месяц</b>\n\n"
        "Что включено:\n"
        "• Новые тренировки каждую неделю\n"
        "• Доступ ко всем материалам месяца\n"
        "• Автоматическое обновление контента\n\n"
        "Для активации напишите администратору: @admin"
    )
    await callback.message.edit_text(text, reply_markup=back_keyboard(), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "sub_info")
async def cb_sub_info(callback: types.CallbackQuery):
    days = get_subscription_days_left(callback.from_user.id)
    await callback.answer(f"⭐ Осталось дней подписки: {days}", show_alert=True)


@dp.callback_query(F.data == "help")
async def cb_help(callback: types.CallbackQuery):
    days_names = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]
    days_str = ", ".join(days_names[d] for d in SCHEDULE_DAYS)
    text = (
        "❓ <b>Помощь</b>\n\n"
        "Как пользоваться ботом:\n"
        "1. Выбери тип тренировок в меню\n"
        "2. Нажми на тренировку для просмотра\n"
        "3. После выполнения отметь её ✅\n\n"
        f"📅 Новые тренировки выходят: {days_str} в {SCHEDULE_TIME}\n"
        "🔄 В конце каждого месяца контент обновляется\n\n"
        "По вопросам оплаты: @admin"
    )
    await callback.message.edit_text(text, reply_markup=back_keyboard(), parse_mode="HTML")
    await callback.answer()


# ========== ADMIN COMMANDS ==========

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    text = (
        "🔧 <b>Панель администратора</b>\n\n"
        "/add_permanent — добавить закреплённую тренировку\n"
        "/add_weekly — добавить тренировку месяца\n"
        "/activate <code>USER_ID [дней]</code> — активировать подписку\n"
        "/users — список пользователей\n"
        "/broadcast — рассылка всем пользователям\n"
        "/cleanup — вручную удалить старые тренировки"
    )
    await message.answer(text, parse_mode="HTML")


# --- /activate ---
@dp.message(Command("activate"))
async def cmd_activate(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /activate USER_ID [дней]\nПример: /activate 123456789 30")
        return
    try:
        uid = int(parts[1])
        days = int(parts[2]) if len(parts) > 2 else 30
        add_user(uid, None)
        activate_subscription(uid, days)
        await message.answer(f"✅ Подписка активирована для {uid} на {days} дней.")
    except ValueError:
        await message.answer("❌ Неверный формат. USER_ID должен быть числом.")


# --- /users ---
@dp.message(Command("users"))
async def cmd_users(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    users = get_all_users()
    if not users:
        await message.answer("Пользователей пока нет.")
        return
    lines = []
    for u in users[:50]:
        sub = u["subscribed_until"] or "нет"
        name = f"@{u['username']}" if u["username"] else str(u["user_id"])
        lines.append(f"• {name} (id: {u['user_id']}) — до {sub}")
    text = f"👥 <b>Пользователи ({len(users)}):</b>\n\n" + "\n".join(lines)
    if len(users) > 50:
        text += f"\n\n... и ещё {len(users) - 50}"
    await message.answer(text, parse_mode="HTML")


# --- /broadcast ---
@dp.message(Command("broadcast"))
async def cmd_broadcast_start(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(BroadcastState.text)
    await message.answer("Введи текст рассылки (или /cancel для отмены):")


@dp.message(BroadcastState.text)
async def cmd_broadcast_send(message: types.Message, state: FSMContext):
    await state.clear()
    users = get_all_users()
    sent, failed = 0, 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], message.text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
    await message.answer(f"📢 Рассылка завершена.\n✅ Отправлено: {sent}\n❌ Ошибок: {failed}")


# --- /cleanup ---
@dp.message(Command("cleanup"))
async def cmd_cleanup(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    deleted = cleanup_old_workouts()
    await message.answer(f"🗑️ Удалено старых тренировок: {deleted}")


# --- /cancel ---
@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено.")


# --- /add_permanent (FSM) ---
@dp.message(Command("add_permanent"))
async def cmd_add_permanent(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AddPermanentState.title)
    await message.answer("Введи <b>название</b> закреплённой тренировки:\n\n/cancel — отмена", parse_mode="HTML")


@dp.message(AddPermanentState.title)
async def ap_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddPermanentState.description)
    await message.answer("Введи <b>описание</b> тренировки:", parse_mode="HTML")


@dp.message(AddPermanentState.description)
async def ap_desc(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(AddPermanentState.url)
    await message.answer("Введи <b>ссылку на видео</b> (или напиши <code>нет</code>):", parse_mode="HTML")


@dp.message(AddPermanentState.url)
async def ap_url(message: types.Message, state: FSMContext):
    url = None if message.text.lower().strip() in ("нет", "no", "-") else message.text.strip()
    await state.update_data(video_url=url)
    await state.set_state(AddPermanentState.duration)
    await message.answer("Введи <b>длительность</b> в минутах (число):", parse_mode="HTML")


@dp.message(AddPermanentState.duration)
async def ap_duration(message: types.Message, state: FSMContext):
    try:
        duration = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введи число (минуты):")
        return
    data = await state.get_data()
    add_permanent_workout(data["title"], data["description"], data["video_url"], duration)
    await state.clear()
    await message.answer(f"✅ Закреплённая тренировка «{data['title']}» добавлена!")


# --- /add_weekly (FSM) ---
@dp.message(Command("add_weekly"))
async def cmd_add_weekly(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AddWeeklyState.title)
    await message.answer("Введи <b>название</b> тренировки месяца:\n\n/cancel — отмена", parse_mode="HTML")


@dp.message(AddWeeklyState.title)
async def aw_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddWeeklyState.description)
    await message.answer("Введи <b>описание</b>:", parse_mode="HTML")


@dp.message(AddWeeklyState.description)
async def aw_desc(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(AddWeeklyState.url)
    await message.answer("Введи <b>ссылку на видео</b> (или <code>нет</code>):", parse_mode="HTML")


@dp.message(AddWeeklyState.url)
async def aw_url(message: types.Message, state: FSMContext):
    url = None if message.text.lower().strip() in ("нет", "no", "-") else message.text.strip()
    await state.update_data(video_url=url)
    await state.set_state(AddWeeklyState.duration)
    await message.answer("Введи <b>длительность</b> в минутах:", parse_mode="HTML")


@dp.message(AddWeeklyState.duration)
async def aw_duration(message: types.Message, state: FSMContext):
    try:
        duration = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введи число:")
        return
    data = await state.get_data()
    add_weekly_workouts([{
        "title": data["title"],
        "description": data["description"],
        "video_url": data["video_url"],
        "duration": duration
    }])
    await state.clear()
    await message.answer(f"✅ Тренировка «{data['title']}» добавлена в тренировки месяца!")


# ========== SCHEDULER JOBS ==========

async def scheduled_cleanup():
    """Запускается 1го числа каждого месяца — удаляет старые тренировки."""
    deleted = cleanup_old_workouts()
    logging.info(f"Scheduled cleanup: удалено {deleted} старых тренировок")
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, f"🗑️ Автоочистка: удалено {deleted} старых тренировок.")
        except Exception:
            pass


async def notify_new_workout():
    """
    Срабатывает по расписанию SCHEDULE_DAYS в SCHEDULE_TIME.
    Уведомляет подписчиков о новых тренировках.
    """
    workouts = get_active_weekly_workouts()
    if not workouts:
        return
    users = get_all_users()
    count = 0
    for u in users:
        if is_subscribed(u["user_id"]):
            try:
                await bot.send_message(
                    u["user_id"],
                    "🔔 <b>Новые тренировки доступны!</b>\n\n"
                    "Открой меню и посмотри свежие тренировки этой недели 💪",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📅 Открыть тренировки", callback_data="weekly")]
                    ])
                )
                count += 1
            except Exception:
                pass
    logging.info(f"Уведомление отправлено {count} подписчикам")


# ========== STARTUP ==========

async def main():
    # Планировщик: уведомления по расписанию
    hour, minute = SCHEDULE_TIME.split(":")
    for day in SCHEDULE_DAYS:
        scheduler.add_job(
            notify_new_workout,
            trigger="cron",
            day_of_week=day,
            hour=int(hour),
            minute=int(minute),
        )
    # Очистка 1го числа каждого месяца в 03:00
    scheduler.add_job(scheduled_cleanup, trigger="cron", day=1, hour=3, minute=0)
    scheduler.start()

    logging.info("🤖 Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
