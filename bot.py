import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import (
    BOT_TOKEN, SCHEDULE_DAYS, SCHEDULE_TIME, ADMIN_IDS,
    BEPAID_PROVIDER_TOKEN, SUBSCRIPTION_PRICE, SUBSCRIPTION_DAYS,
    SUBSCRIPTION_WELCOME_TEXT
)
from database import (
    add_user, is_subscribed, get_subscription_days_left,
    activate_subscription, get_permanent_workouts, get_active_weekly_workouts,
    has_completed_workout, mark_workout_done, cleanup_old_workouts,
    add_weekly_workouts, add_permanent_workout, get_all_users, get_db,
    get_nutrition_lectures, get_nutrition_lecture, add_nutrition_lecture,
    delete_nutrition_lecture, get_next_unsent_workout, mark_workout_sent,
    get_permanent_workout, update_permanent_workout, delete_permanent_workout,
    get_weekly_workout, update_weekly_workout, delete_weekly_workout,
    update_nutrition_lecture
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

class AddWeeklyState(StatesGroup):
    title = State()
    description = State()
    url = State()

class BroadcastState(StatesGroup):
    text = State()

class ActivateState(StatesGroup):
    user_id = State()
    days = State()

class AddLectureState(StatesGroup):
    title = State()
    description = State()
    url = State()
    gif = State()
    pdf = State()

class EditFieldState(StatesGroup):
    waiting_value = State()


# ========== KEYBOARDS ==========

def main_menu(user_id=None):
    buttons = [
        [InlineKeyboardButton(text="🏋️ Закреплённые тренировки", callback_data="permanent")],
        [InlineKeyboardButton(text="🍎 Лекции по питанию", callback_data="lectures")],
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
        [InlineKeyboardButton(text="🍎 Добавить лекцию по питанию", callback_data="adm:add_lecture")],
        [InlineKeyboardButton(text="✏️ Редактировать закреплённые", callback_data="adm:edit_permanent_list")],
        [InlineKeyboardButton(text="✏️ Редактировать тренировки месяца", callback_data="adm:edit_weekly_list")],
        [InlineKeyboardButton(text="✏️ Редактировать лекции", callback_data="adm:edit_lecture_list")],
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
            text=f"{status}{w['title']}",
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
    text = "🔧 <b>Панель администратора</b>\n\nВыбери действие:"
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
        "Постоянные материалы (разминка, заминка и др.) доступны всегда.\n\n"
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
    await message.answer("❌ Действие отменено.",
                         reply_markup=admin_menu() if is_admin(message.from_user.id) else None)


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
        await callback.message.edit_text("📭 Закреплённых тренировок пока нет.", reply_markup=back_keyboard())
        await callback.answer()
        return
    text = "🏋️ <b>Закреплённые тренировки</b> (доступны всегда):\n\n"
    text += "\n".join(f"• {w['title']}" for w in workouts)
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
            "📭 Тренировки этого месяца ещё не добавлены.\n\nОни появляются по расписанию: ПН, СР, ПТ в 10:00.",
            reply_markup=back_keyboard()
        )
        await callback.answer()
        return
    text = "📅 <b>Тренировки этого месяца:</b>\n\n"
    text += "\n".join(f"• {w['title']} (неделя {w['week_number']})" for w in workouts)
    await callback.message.edit_text(text, reply_markup=workout_list_keyboard(workouts, "weekly", uid), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "lectures")
async def cb_lectures(callback: types.CallbackQuery):
    """Лекции по питанию — бесплатно, без подписки."""
    lectures = get_nutrition_lectures()
    if not lectures:
        await callback.message.edit_text(
            "📭 Лекции по питанию пока не добавлены.\n\nСкоро здесь появятся материалы 🍎",
            reply_markup=back_keyboard()
        )
        await callback.answer()
        return

    buttons = []
    for lec in lectures:
        pdf_icon = "📄" if lec["pdf_url"] else ""
        buttons.append([InlineKeyboardButton(
            text=f"🍎 {lec['title']} {pdf_icon}",
            callback_data=f"lec:{lec['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back")])

    text = "🍎 <b>Лекции по питанию</b>\n\nДоступны всем бесплатно:\n\n"
    text += "\n".join(f"• {lec['title']}" for lec in lectures)

    await callback.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("lec:"))
async def cb_show_lecture(callback: types.CallbackQuery):
    lecture_id = int(callback.data.split(":")[1])
    lecture = get_nutrition_lecture(lecture_id)
    if not lecture:
        await callback.answer("Лекция не найдена")
        return

    text = f"🍎 <b>{lecture['title']}</b>\n\n"
    if lecture["description"]:
        text += f"📝 {lecture['description']}\n"
    if lecture["video_url"]:
        text += f"\n🎥 <a href=\"{lecture['video_url']}\">Смотреть видео</a>"
    if lecture["pdf_url"]:
        text += f"\n📄 <a href=\"{lecture['pdf_url']}\">Открыть PDF-материал</a>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="lectures")]
    ])

    # Если есть GIF — отправляем анимацию отдельным сообщением перед текстом
    if lecture.get("gif_file_id"):
        await callback.message.delete()
        await bot.send_animation(
            callback.from_user.id,
            lecture["gif_file_id"],
            caption=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("wk:"))
async def cb_show_workout(callback: types.CallbackQuery):
    _, workout_type, wid_str = callback.data.split(":", 2)
    workout_id = int(wid_str)
    uid = callback.from_user.id

    workouts = get_permanent_workouts() if workout_type == "permanent" else get_active_weekly_workouts()
    if workout_type == "weekly" and not is_subscribed(uid):
        await callback.answer("❌ Подписка не активна!", show_alert=True)
        return

    workout = next((w for w in workouts if w["id"] == workout_id), None)
    if not workout:
        await callback.answer("Тренировка не найдена")
        return

    done = has_completed_workout(uid, workout_id, workout_type)
    text = f"🏋️ <b>{workout['title']}</b>\n\n"
    if done:
        text += "✅ <i>Вы уже выполнили эту тренировку</i>\n\n"
    text += f"📝 {workout['description']}\n\n" if workout['description'] else ""
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
        "По вопросам: @admin"
    )
    await callback.message.edit_text(text, reply_markup=back_keyboard(), parse_mode="HTML")
    await callback.answer()


# ========== ОПЛАТА (bePaid / Telegram Payments) ==========

@dp.callback_query(F.data == "buy_sub")
async def cb_buy_sub(callback: types.CallbackQuery):
    uid = callback.from_user.id

    # Если провайдер не настроен — показываем инструкцию
    if not BEPAID_PROVIDER_TOKEN or BEPAID_PROVIDER_TOKEN == "ВСТАВЬ_PROVIDER_TOKEN":
        text = (
            "💎 <b>Подписка на фитнес-бот</b>\n\n"
            f"Цена: <b>{SUBSCRIPTION_PRICE} BYN / {SUBSCRIPTION_DAYS} дней</b>\n\n"
            "Что включено:\n"
            "• Новые тренировки каждую неделю\n"
            "• Доступ ко всем материалам месяца\n"
            "• Автоматические уведомления\n\n"
            "Для оплаты напишите администратору: @admin"
        )
        await callback.message.edit_text(text, reply_markup=back_keyboard(), parse_mode="HTML")
        await callback.answer()
        return

    # Отправляем инвойс через Telegram Payments
    await callback.message.delete()
    await bot.send_invoice(
        chat_id=uid,
        title="💎 Подписка на фитнес-бот",
        description=(
            f"Доступ к тренировкам на {SUBSCRIPTION_DAYS} дней.\n"
            "Новые тренировки каждую неделю, уведомления по расписанию."
        ),
        payload=f"sub_{uid}_{SUBSCRIPTION_DAYS}",
        provider_token=BEPAID_PROVIDER_TOKEN,
        currency="BYR",
        prices=[LabeledPrice(label=f"Подписка {SUBSCRIPTION_DAYS} дней", amount=SUBSCRIPTION_PRICE * 100)],
        start_parameter="subscribe",
        photo_url="https://i.imgur.com/5k3gPRk.png",
        photo_width=800,
        photo_height=400,
        need_name=False,
        need_phone_number=False,
        need_email=False,
        is_flexible=False,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 Оплатить {SUBSCRIPTION_PRICE} BYN", pay=True)],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
        ])
    )
    await callback.answer()


@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    """Подтверждаем платёж перед списанием."""
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def successful_payment(message: types.Message):
    """Платёж прошёл — активируем подписку."""
    uid = message.from_user.id
    payload = message.successful_payment.invoice_payload  # "sub_123456_30"

    try:
        days = int(payload.split("_")[-1])
    except (ValueError, IndexError):
        days = SUBSCRIPTION_DAYS

    activate_subscription(uid, days)

    # Приветственное сообщение от заказчика (текст согласован отдельно)
    await message.answer(
        SUBSCRIPTION_WELCOME_TEXT,
        reply_markup=main_menu(uid),
        parse_mode="HTML"
    )

    # Уведомляем админов
    username = f"@{message.from_user.username}" if message.from_user.username else str(uid)
    amount = message.successful_payment.total_amount // 100
    currency = message.successful_payment.currency
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"💰 <b>Новая оплата!</b>\n\n"
                f"👤 Пользователь: {username} (id: {uid})\n"
                f"💵 Сумма: {amount} {currency}\n"
                f"📅 Подписка на: {days} дней",
                parse_mode="HTML"
            )
        except Exception:
            pass


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
        name = f"@{u['username']}" if u["username"] else str(u["user_id"])
        if is_subscribed(u["user_id"]):
            days_left = get_subscription_days_left(u["user_id"])
            lines.append(f"⭐ {name} — осталось <b>{days_left} дн.</b> (до {u['subscribed_until']})")
        else:
            lines.append(f"👤 {name} — без подписки")

    text = f"👥 <b>Пользователи: {total}</b> (активных подписок: {active})\n\n" + "\n".join(lines)
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


# --- Активация вручную ---

@dp.callback_query(F.data == "adm:activate")
async def adm_activate_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(ActivateState.user_id)
    await callback.message.edit_text(
        "✅ <b>Активация подписки</b>\n\nВведи <b>Telegram ID</b> пользователя:\n<i>(Узнать: @userinfobot)</i>",
        reply_markup=cancel_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@dp.message(ActivateState.user_id)
async def adm_activate_uid(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
        await state.update_data(user_id=uid)
        await state.set_state(ActivateState.days)
        await message.answer(
            f"Пользователь: <code>{uid}</code>\n\nНа сколько дней?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="1 день", callback_data="adm:days:1"),
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
    try:
        await bot.send_message(uid, SUBSCRIPTION_WELCOME_TEXT, parse_mode="HTML")
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


# --- Добавить закреплённую ---

@dp.callback_query(F.data == "adm:add_permanent")
async def adm_add_perm_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AddPermanentState.title)
    await callback.message.edit_text(
        "🏋️ <b>Новая закреплённая тренировка</b>\n\nВведи <b>название</b>:",
        reply_markup=cancel_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@dp.message(AddPermanentState.title)
async def ap_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddPermanentState.description)
    await message.answer(
        "Введи <b>описание</b> (или <code>-</code> чтобы пропустить):",
        reply_markup=cancel_keyboard(), parse_mode="HTML"
    )


@dp.message(AddPermanentState.description)
async def ap_desc(message: types.Message, state: FSMContext):
    desc = None if message.text.strip() in ("-", "нет", "no") else message.text
    await state.update_data(description=desc)
    await state.set_state(AddPermanentState.url)
    await message.answer(
        "Введи <b>ссылку на видео</b> (или <code>-</code>):",
        reply_markup=cancel_keyboard(), parse_mode="HTML"
    )


@dp.message(AddPermanentState.url)
async def ap_url(message: types.Message, state: FSMContext):
    url = None if message.text.lower().strip() in ("нет", "no", "-") else message.text.strip()
    data = await state.get_data()
    add_permanent_workout(data["title"], data["description"], url, 0)
    await state.clear()
    await message.answer(
        f"✅ Тренировка «<b>{data['title']}</b>» добавлена!",
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
        reply_markup=cancel_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@dp.message(AddWeeklyState.title)
async def aw_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddWeeklyState.description)
    await message.answer(
        "Введи <b>описание</b> (или <code>-</code> чтобы пропустить):",
        reply_markup=cancel_keyboard(), parse_mode="HTML"
    )


@dp.message(AddWeeklyState.description)
async def aw_desc(message: types.Message, state: FSMContext):
    desc = None if message.text.strip() in ("-", "нет", "no") else message.text
    await state.update_data(description=desc)
    await state.set_state(AddWeeklyState.url)
    await message.answer(
        "Введи <b>ссылку на видео</b> (или <code>-</code>):",
        reply_markup=cancel_keyboard(), parse_mode="HTML"
    )


@dp.message(AddWeeklyState.url)
async def aw_url(message: types.Message, state: FSMContext):
    url = None if message.text.lower().strip() in ("нет", "no", "-") else message.text.strip()
    data = await state.get_data()
    add_weekly_workouts([{
        "title": data["title"],
        "description": data["description"],
        "video_url": url,
        "duration": 0
    }])
    await state.clear()
    await message.answer(
        f"✅ Тренировка «<b>{data['title']}</b>» добавлена в тренировки месяца!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
        ]),
        parse_mode="HTML"
    )


# --- Добавить лекцию по питанию ---

def skip_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="adm:lec_skip")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:cancel")],
    ])


@dp.callback_query(F.data == "adm:add_lecture")
async def adm_add_lecture_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AddLectureState.url)
    await callback.message.edit_text(
        "🍎 <b>Новая лекция по питанию</b>\n\n"
        "Пришли <b>ссылку на видео</b> (YouTube, Google Drive и т.д.).\n"
        "Название лекции будет взято автоматически из ссылки, или введи вручную на следующем шаге.",
        reply_markup=cancel_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@dp.message(AddLectureState.url)
async def al_url(message: types.Message, state: FSMContext):
    import re, urllib.parse
    url = message.text.strip() if message.text else ""
    # Автоматически извлекаем имя из ссылки (последний сегмент пути или query param)
    try:
        parsed = urllib.parse.urlparse(url)
        path_part = parsed.path.rstrip("/").split("/")[-1]
        # Убираем расширение файла если есть
        name_from_url = re.sub(r'\.[a-zA-Z0-9]+$', '', path_part).replace('-', ' ').replace('_', ' ').strip()
        auto_title = name_from_url[:60] if name_from_url else ""
    except Exception:
        auto_title = ""

    await state.update_data(video_url=url if url else None, auto_title=auto_title)
    await state.set_state(AddLectureState.title)

    hint = f"\n\n<i>Из ссылки получено: «{auto_title}»</i>" if auto_title else ""
    await message.answer(
        f"Введи <b>название</b> лекции{hint}\n\n"
        "Или нажми «⏭️ Пропустить» чтобы использовать авто-название из ссылки:",
        reply_markup=skip_keyboard(), parse_mode="HTML"
    )


@dp.callback_query(F.data == "adm:lec_skip", AddLectureState.title)
async def al_title_skip(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    title = data.get("auto_title") or "Лекция"
    await state.update_data(title=title)
    await state.set_state(AddLectureState.description)
    await callback.message.edit_text(
        f"Название: «<b>{title}</b>»\n\n"
        "Введи <b>описание</b> лекции или нажми «⏭️ Пропустить»:",
        reply_markup=skip_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@dp.message(AddLectureState.title)
async def al_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AddLectureState.description)
    await message.answer(
        "Введи <b>описание</b> лекции или нажми «⏭️ Пропустить»:",
        reply_markup=skip_keyboard(), parse_mode="HTML"
    )


@dp.callback_query(F.data == "adm:lec_skip", AddLectureState.description)
async def al_desc_skip(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(description=None)
    await state.set_state(AddLectureState.gif)
    await callback.message.edit_text(
        "🎞️ Пришли <b>GIF-анимацию</b> для лекции или нажми «⏭️ Пропустить»:",
        reply_markup=skip_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@dp.message(AddLectureState.description)
async def al_desc(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(AddLectureState.gif)
    await message.answer(
        "🎞️ Пришли <b>GIF-анимацию</b> для лекции или нажми «⏭️ Пропустить»:",
        reply_markup=skip_keyboard(), parse_mode="HTML"
    )


@dp.message(AddLectureState.gif, F.animation)
async def al_gif_file(message: types.Message, state: FSMContext):
    await state.update_data(gif_file_id=message.animation.file_id)
    await state.set_state(AddLectureState.pdf)
    await message.answer(
        "📄 Пришли <b>ссылку на PDF</b> (Google Drive) или нажми «⏭️ Пропустить»:",
        reply_markup=skip_keyboard(), parse_mode="HTML"
    )


@dp.callback_query(F.data == "adm:lec_skip", AddLectureState.gif)
async def al_gif_skip(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(gif_file_id=None)
    await state.set_state(AddLectureState.pdf)
    await callback.message.edit_text(
        "📄 Пришли <b>ссылку на PDF</b> (Google Drive) или нажми «⏭️ Пропустить»:",
        reply_markup=skip_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "adm:lec_skip", AddLectureState.pdf)
async def al_pdf_skip(callback: types.CallbackQuery, state: FSMContext):
    await _save_lecture(callback.message, state, pdf_url=None, answer_method="edit")
    await callback.answer()


@dp.message(AddLectureState.pdf)
async def al_pdf_url(message: types.Message, state: FSMContext):
    pdf_url = message.text.strip() if message.text else None
    await _save_lecture(message, state, pdf_url=pdf_url, answer_method="answer")


async def _save_lecture(target, state: FSMContext, pdf_url, answer_method="answer"):
    import re
    data = await state.get_data()
    title = data.get("title") or "Лекция"
    safe_name = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')
    pdf_filename = f"{safe_name}.pdf" if pdf_url else None
    add_nutrition_lecture(
        title, data.get("description"), data.get("video_url"),
        pdf_url=pdf_url, pdf_filename=pdf_filename,
        gif_file_id=data.get("gif_file_id")
    )
    await state.clear()
    suffix = " со ссылкой на PDF" if pdf_url else " (без PDF)"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
    ])
    text = f"✅ Лекция «<b>{title}</b>» добавлена{suffix}!"
    if answer_method == "edit":
        await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


# ========== РЕДАКТИРОВАНИЕ КОНТЕНТА (закреплённые/месяц/лекции) ==========
# content_type: "permanent" | "weekly" | "lecture"

CONTENT_CONFIG = {
    "permanent": {
        "title": "Закреплённые тренировки",
        "get_list": get_permanent_workouts,
        "get_one": get_permanent_workout,
        "update": update_permanent_workout,
        "delete": delete_permanent_workout,
        "fields": [("title", "Название"), ("description", "Описание"),
                   ("video_url", "Ссылка на видео")],
    },
    "weekly": {
        "title": "Тренировки месяца",
        "get_list": get_active_weekly_workouts,
        "get_one": get_weekly_workout,
        "update": update_weekly_workout,
        "delete": delete_weekly_workout,
        "fields": [("title", "Название"), ("description", "Описание"),
                   ("video_url", "Ссылка на видео")],
    },
    "lecture": {
        "title": "Лекции по питанию",
        "get_list": get_nutrition_lectures,
        "get_one": get_nutrition_lecture,
        "update": update_nutrition_lecture,
        "delete": delete_nutrition_lecture,
        "fields": [("title", "Название"), ("description", "Описание"),
                   ("video_url", "Ссылка на видео"), ("pdf_url", "Ссылка на PDF (Google Drive)"), ("gif_file_id", "GIF-анимация (file_id)")],
    },
}


@dp.callback_query(F.data.startswith("adm:edit_") & F.data.endswith("_list"))
async def adm_edit_list(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    content_type = callback.data.replace("adm:edit_", "").replace("_list", "")
    cfg = CONTENT_CONFIG[content_type]
    items = cfg["get_list"]()
    if not items:
        await callback.message.edit_text(
            f"📭 «{cfg['title']}» — пока пусто.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
            ])
        )
        await callback.answer()
        return

    buttons = [
        [InlineKeyboardButton(text=f"✏️ {item['title']}", callback_data=f"adm:edit_item:{content_type}:{item['id']}")]
        for item in items
    ]
    buttons.append([InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")])
    await callback.message.edit_text(
        f"✏️ <b>{cfg['title']}</b>\n\nВыбери, что отредактировать:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("adm:edit_item:"))
async def adm_edit_item(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    _, _, content_type, item_id = callback.data.split(":")
    item_id = int(item_id)
    cfg = CONTENT_CONFIG[content_type]
    item = cfg["get_one"](item_id)
    if not item:
        await callback.answer("Не найдено")
        return

    text = f"✏️ <b>{item['title']}</b>\n\n📝 {item['description']}\n"
    if item["video_url"]:
        text += f"\n🎥 {item['video_url']}"

    buttons = []
    for field, label in cfg["fields"]:
        buttons.append([InlineKeyboardButton(
            text=f"Изменить: {label}",
            callback_data=f"adm:edit_field:{content_type}:{item_id}:{field}"
        )])
    buttons.append([InlineKeyboardButton(
        text="🗑️ Удалить", callback_data=f"adm:delete_item:{content_type}:{item_id}"
    )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"adm:edit_{content_type}_list")])

    await callback.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("adm:edit_field:"))
async def adm_edit_field_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    _, _, content_type, item_id, field = callback.data.split(":")
    cfg = CONTENT_CONFIG[content_type]
    label = dict(cfg["fields"])[field]

    await state.set_state(EditFieldState.waiting_value)
    await state.update_data(content_type=content_type, item_id=int(item_id), field=field)
    await callback.message.edit_text(
        f"Введи новое значение для поля «<b>{label}</b>»:",
        reply_markup=cancel_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@dp.message(EditFieldState.waiting_value)
async def adm_edit_field_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    content_type = data["content_type"]
    item_id = data["item_id"]
    field = data["field"]
    cfg = CONTENT_CONFIG[content_type]

    value = message.text.strip()
    if field == "duration":
        try:
            value = int(value)
        except ValueError:
            await message.answer("❌ Длительность должна быть числом. Попробуй ещё раз:", reply_markup=cancel_keyboard())
            return
    if field in ("video_url", "pdf_url") and value.lower() in ("нет", "no", "-"):
        value = None

    cfg["update"](item_id, field, value)
    await state.clear()
    await message.answer(
        "✅ Изменения сохранены!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К списку", callback_data=f"adm:edit_{content_type}_list")],
            [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
        ])
    )


@dp.callback_query(F.data.startswith("adm:delete_item:"))
async def adm_delete_item_confirm(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    _, _, content_type, item_id = callback.data.split(":")
    await callback.message.edit_text(
        "⚠️ Точно удалить? Это необратимо.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"adm:delete_confirm:{content_type}:{item_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"adm:edit_item:{content_type}:{item_id}")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("adm:delete_confirm:"))
async def adm_delete_item_do(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    _, _, content_type, item_id = callback.data.split(":")
    item_id = int(item_id)
    cfg = CONTENT_CONFIG[content_type]
    cfg["delete"](item_id)
    await callback.message.edit_text(
        "🗑️ Удалено.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К списку", callback_data=f"adm:edit_{content_type}_list")],
            [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
        ])
    )
    await callback.answer("Удалено")


# --- Рассылка ---

@dp.callback_query(F.data == "adm:broadcast")
async def adm_broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(BroadcastState.text)
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\nВведи текст. Поддерживается HTML:\n"
        "<code>&lt;b&gt;жирный&lt;/b&gt;</code>, <code>&lt;i&gt;курсив&lt;/i&gt;</code>",
        reply_markup=cancel_keyboard(), parse_mode="HTML"
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
    logging.info(f"Автоочистка: удалено {deleted}")
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, f"🗑️ Автоочистка: удалено {deleted} старых тренировок.")
        except Exception:
            pass


async def send_tomorrow_workout():
    """
    По расписанию (ВС/ВТ/ЧТ, 20:00): вечером отправляем подписчикам
    тренировку на завтра — следующую неотправленную по очерёдности.
    """
    workout = get_next_unsent_workout()
    if not workout:
        logging.info("Нет новых тренировок для отправки — добавь через /admin")
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    "⚠️ Сегодня вечером нужно отправить тренировку на завтра, "
                    "но новых тренировок в очереди нет. Добавь через /admin."
                )
            except Exception:
                pass
        return

    users = get_all_users()
    text = (
        f"🌙 <b>Тренировка на завтра готова!</b>\n\n"
        f"🏋️ {workout['title']}\n\n"
        "Открой меню, чтобы посмотреть подробности 💪"
    )
    count = 0
    for u in users:
        if is_subscribed(u["user_id"]):
            try:
                await bot.send_message(
                    u["user_id"], text, parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📅 Открыть тренировку", callback_data=f"wk:weekly:{workout['id']}")]
                    ])
                )
                count += 1
            except Exception:
                pass

    mark_workout_sent(workout["id"])
    logging.info(f"Тренировка «{workout['title']}» отправлена {count} подписчикам")


# ========== STARTUP ==========

async def main():
    hour, minute = SCHEDULE_TIME.split(":")
    for day in SCHEDULE_DAYS:
        scheduler.add_job(send_tomorrow_workout, trigger="cron", day_of_week=day, hour=int(hour), minute=int(minute))
    scheduler.add_job(scheduled_cleanup, trigger="cron", day=1, hour=3, minute=0)
    scheduler.start()
    logging.info("🤖 Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
