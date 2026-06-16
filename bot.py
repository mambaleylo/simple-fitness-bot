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

class ActivateState(StatesGroup):
    user_id = State()
    days = State()


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


def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏋️ Добавить закреплённую", callback_data="adm:add_permanent")],
        [InlineKeyboardButton(text="📅 Добавить тренировку месяца", callback_data="adm:add_weekly")],
        [InlineKeyboardButton(text="✅ Активировать подписку", callback_data="adm:activate")],
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="adm:users")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:broadcast")],
        [InlineKeyboardButton(text="🗑️ Очистить старые тренировки", callback_data="adm:cleanup")],
    ])


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


def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:cancel")]
    ])


# ========== HELPERS ==========

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def send_admin_panel(target, edit=False):
    text = (
        "🔧 <b>Панель администратора</b>\n\n"
        "Выбери действие:"
    )
    if edit:
        await target.message.edit_text(text, reply_markup=admin_menu(), parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=admin_menu(), parse_mode="HTML")


# ========== COMMANDS ==========

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    add_user(uid, message.from_user.username)
    await message.answer(
        f"🔥 Привет, {message.from_user.first_name}!\n\n"
        "Я твой персональный фитнес-тренер.\n"
        "Каждую неделю выходят новые тренировки по расписанию.\n"
        "Постоянные материалы (разминка и др.) доступны всегда.\n\n"
        "⬇️ Выбери действие:",
        reply_markup=main_menu(uid)
    )


@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await send_admin_panel(message)


@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено.", reply_markup=admin_menu() if is_admin(message.from_user.id) else None)


# ========== USER CALLBACKS ==========

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
            "📭 Закреплённых тренировок пока нет.",
            reply_markup=back_keyboard()
        )
        await callback.answer()
        return
    text = "🏋️ <b>Закреплённые тренировки</b> (доступны всегда):\n\n"
    text += "\n".join(f"• {w['title']} — {w['duration']} мин" for w in workouts)
    await callback.message.edit_text(text, reply_markup=workout_list_keyboard(workouts, "permanent", uid), parse_mode="HTML")
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
    text += "\n".join(f"• {w['title']} — {w['duration']} мин (неделя {w['week_number']})" for w in workouts)
    await callback.message.edit_text(text, reply_markup=workout_list_keyboard(workouts, "weekly", uid), parse_mode="HTML")
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
        buttons.append([InlineKeyboardButton(text="✅ Отметить выполненным", callback_data=f"done:{workout_type}:{workout_id}")])
    back_target = "permanent" if workout_type == "permanent" else "weekly"
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=back_target)])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
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
    callback.data = f"wk:{workout_type}:{workout_id}"
    await cb_show_workout(callback)


@dp.callback_query(F.data == "progress")
async def cb_progress(callback: types.CallbackQuery):
    uid = callback.from_user.id
    with get_db() as conn:
        perm = conn.execute('SELECT COUNT(*) FROM completed_workouts WHERE user_id=? AND workout_type="permanent"', (uid,)).fetchone()[0]
        week = conn.execute('SELECT COUNT(*) FROM completed_workouts WHERE user_id=? AND workout_type="weekly"', (uid,)).fetchone()[0]

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


# ========== ADMIN CALLBACKS ==========

@dp.callback_query(F.data == "adm:cancel")
async def adm_cancel(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    await send_admin_panel(callback, edit=True)


@dp.callback_query(F.data == "adm:users")
async def adm_users(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    users = get_all_users()
    if not users:
        await callback.message.edit_text("Пользователей пока нет.", reply_markup=back_keyboard("adm:back"))
        await callback.answer()
        return

    total = len(users)
    active = sum(1 for u in users if is_subscribed(u["user_id"]))
    lines = []
    for u in users[:30]:
        sub = u["subscribed_until"] or "—"
        name = f"@{u['username']}" if u["username"] else str(u["user_id"])
        icon = "⭐" if is_subscribed(u["user_id"]) else "👤"
        lines.append(f"{icon} {name} — до {sub}")

    text = f"👥 <b>Пользователи: {total}</b> (активных подписок: {active})\n\n"
    text += "\n".join(lines)
    if total > 30:
        text += f"\n\n... и ещё {total - 30}"

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="adm:back")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "adm:cleanup")
async def adm_cleanup(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    deleted = cleanup_old_workouts()
    await callback.answer(f"🗑️ Удалено старых тренировок: {deleted}", show_alert=True)
    await send_admin_panel(callback, edit=True)


@dp.callback_query(F.data == "adm:back")
async def adm_back(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await send_admin_panel(callback, edit=True)


# --- Активация подписки ---

@dp.callback_query(F.data == "adm:activate")
async def adm_activate_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(ActivateState.user_id)
    await callback.message.edit_text(
        "✅ <b>Активация подписки</b>\n\nВведи <b>Telegram ID</b> пользователя:\n<i>(Узнать ID можно через @userinfobot)</i>",
        reply_markup=cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(ActivateState.user_id)
async def adm_activate_uid(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
        await state.update_data(user_id=uid)
        await state.set_state(ActivateState.days)
        await message.answer(
            f"Пользователь: <code>{uid}</code>\n\nНа сколько дней активировать? (по умолчанию 30)",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="30 дней", callback_data="adm:days:30"),
                    InlineKeyboardButton(text="60 дней", callback_data="adm:days:60"),
                    InlineKeyboardButton(text="90 дней", callback_data="adm:days:90"),
                ],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:cancel")]
            ]),
            parse_mode="HTML"
        )
    except ValueError:
        await message.answer("❌ ID должен быть числом. Попробуй ещё раз:", reply_markup=cancel_keyboard())


@dp.callback_query(F.data.startswith("adm:days:"))
async def adm_activate_days(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    days = int(callback.data.split(":")[2])
    data = await state.get_data()
    uid = data.get("user_id")
    if not uid:
        await state.clear()
        await send_admin_panel(callback, edit=True)
        return
    add_user(uid, None)
    activate_subscription(uid, days)
    await state.clear()
    # Уведомить пользователя
    try:
        await bot.send_message(uid, f"🎉 Ваша подписка активирована на <b>{days} дней</b>!", parse_mode="HTML")
    except Exception:
        pass
    await callback.message.edit_text(
        f"✅ Подписка для <code>{uid}</code> активирована на <b>{days} дней</b>.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


# --- Добавить закреплённую тренировку ---

@dp.callback_query(F.data == "adm:add_permanent")
async def adm_add_perm_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AddPermanentState.title)
    await callback.message.edit_text(
        "🏋️ <b>Новая закреплённая тренировка</b>\n\nВведи <b>название</b>:",
        reply_markup=cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(AddPermanentState.title)
async def ap_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddPermanentState.description)
    await message.answer("Введи <b>описание</b> тренировки:", reply_markup=cancel_keyboard(), parse_mode="HTML")


@dp.message(AddPermanentState.description)
async def ap_desc(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(AddPermanentState.url)
    await message.answer("Введи <b>ссылку на видео</b> (или напиши <code>нет</code>):", reply_markup=cancel_keyboard(), parse_mode="HTML")


@dp.message(AddPermanentState.url)
async def ap_url(message: types.Message, state: FSMContext):
    url = None if message.text.lower().strip() in ("нет", "no", "-") else message.text.strip()
    await state.update_data(video_url=url)
    await state.set_state(AddPermanentState.duration)
    await message.answer("Введи <b>длительность</b> в минутах:", reply_markup=cancel_keyboard(), parse_mode="HTML")


@dp.message(AddPermanentState.duration)
async def ap_duration(message: types.Message, state: FSMContext):
    try:
        duration = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введи число:", reply_markup=cancel_keyboard())
        return
    data = await state.get_data()
    add_permanent_workout(data["title"], data["description"], data["video_url"], duration)
    await state.clear()
    await message.answer(
        f"✅ Закреплённая тренировка «<b>{data['title']}</b>» добавлена!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
        ]),
        parse_mode="HTML"
    )


# --- Добавить тренировку месяца ---

@dp.callback_query(F.data == "adm:add_weekly")
async def adm_add_weekly_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AddWeeklyState.title)
    await callback.message.edit_text(
        "📅 <b>Новая тренировка месяца</b>\n\nВведи <b>название</b>:",
        reply_markup=cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(AddWeeklyState.title)
async def aw_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddWeeklyState.description)
    await message.answer("Введи <b>описание</b>:", reply_markup=cancel_keyboard(), parse_mode="HTML")


@dp.message(AddWeeklyState.description)
async def aw_desc(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(AddWeeklyState.url)
    await message.answer("Введи <b>ссылку на видео</b> (или <code>нет</code>):", reply_markup=cancel_keyboard(), parse_mode="HTML")


@dp.message(AddWeeklyState.url)
async def aw_url(message: types.Message, state: FSMContext):
    url = None if message.text.lower().strip() in ("нет", "no", "-") else message.text.strip()
    await state.update_data(video_url=url)
    await state.set_state(AddWeeklyState.duration)
    await message.answer("Введи <b>длительность</b> в минутах:", reply_markup=cancel_keyboard(), parse_mode="HTML")


@dp.message(AddWeeklyState.duration)
async def aw_duration(message: types.Message, state: FSMContext):
    try:
        duration = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введи число:", reply_markup=cancel_keyboard())
        return
    data = await state.get_data()
    add_weekly_workouts([{
        "title": data["title"],
        "description": data["description"],
        "video_url": data["video_url"],
        "duration": duration
    }])
    await state.clear()
    await message.answer(
        f"✅ Тренировка «<b>{data['title']}</b>» добавлена в тренировки месяца!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
        ]),
        parse_mode="HTML"
    )


# --- Рассылка ---

@dp.callback_query(F.data == "adm:broadcast")
async def adm_broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(BroadcastState.text)
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\nВведи текст сообщения.\nПоддерживается HTML: <code>&lt;b&gt;жирный&lt;/b&gt;</code>, <code>&lt;i&gt;курсив&lt;/i&gt;</code>",
        reply_markup=cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(BroadcastState.text)
async def adm_broadcast_send(message: types.Message, state: FSMContext):
    await state.clear()
    users = get_all_users()
    sent, failed = 0, 0
    status_msg = await message.answer("⏳ Отправляю рассылку...")
    for u in users:
        try:
            await bot.send_message(u["user_id"], message.text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
    await status_msg.edit_text(
        f"📢 <b>Рассылка завершена</b>\n\n✅ Отправлено: {sent}\n❌ Ошибок: {failed}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
        ]),
        parse_mode="HTML"
    )


# ========== SCHEDULER ==========

async def scheduled_cleanup():
    deleted = cleanup_old_workouts()
    logging.info(f"Scheduled cleanup: удалено {deleted}")
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, f"🗑️ Автоочистка: удалено {deleted} старых тренировок.")
        except Exception:
            pass


async def notify_new_workout():
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
                    "🔔 <b>Новые тренировки доступны!</b>\n\nОткрой меню и посмотри свежие тренировки 💪",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📅 Открыть тренировки", callback_data="weekly")]
                    ])
                )
                count += 1
            except Exception:
                pass
    logging.info(f"Уведомлено подписчиков: {count}")


# ========== STARTUP ==========

async def main():
    hour, minute = SCHEDULE_TIME.split(":")
    for day in SCHEDULE_DAYS:
        scheduler.add_job(notify_new_workout, trigger="cron", day_of_week=day, hour=int(hour), minute=int(minute))
    scheduler.add_job(scheduled_cleanup, trigger="cron", day=1, hour=3, minute=0)
    scheduler.start()
    logging.info("🤖 Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
