import os
import base64
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from openai import OpenAI
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    ContextTypes,
    filters,
)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

user_messages = {}
user_last_outputs = {}

STATS_FILE = "stats.json"
ACCESS_FILE = "access.json"
USAGE_FILE = "usage.json"

ADMIN_ID = 669799237

FREE_DAILY_LIMIT = 3
WEEKLY_STARS = 200
MONTHLY_STARS = 500

START_TEXT = """
💬 Welcome to SheTexted

Send:
• screenshot
• copied chat
• dating app convo

Get:
• best reply
• emotional analysis
• better texting energy
• what she actually means


👇 Send your chat
"""


def load_json(file_name, default):
    try:
        with open(file_name, "r") as f:
            return json.load(f)
    except:
        return default


def save_json(file_name, data):
    with open(file_name, "w") as f:
        json.dump(data, f)


def load_stats():
    return load_json(STATS_FILE, {
        "users": [],
        "messages_today": 0,
        "new_users_today": 0,
        "total_messages": 0,
        "last_reset": ""
    })


def save_stats(stats):
    save_json(STATS_FILE, stats)


def load_access():
    return load_json(ACCESS_FILE, {})


def save_access(access):
    save_json(ACCESS_FILE, access)


def load_usage():
    return load_json(USAGE_FILE, {})


def save_usage(usage):
    save_json(USAGE_FILE, usage)


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def reset_daily_stats(stats):
    today = today_str()

    if stats.get("last_reset") != today:
        stats["messages_today"] = 0
        stats["new_users_today"] = 0
        stats["last_reset"] = today

    if "total_messages" not in stats:
        stats["total_messages"] = 0

    return stats


def track_user(user_id):
    stats = load_stats()
    stats = reset_daily_stats(stats)

    stats["messages_today"] += 1
    stats["total_messages"] += 1

    if user_id not in stats["users"]:
        stats["users"].append(user_id)
        stats["new_users_today"] += 1

    save_stats(stats)


def has_active_pro(user_id):
    access = load_access()
    uid = str(user_id)

    if uid not in access:
        return False

    try:
        expires_at = datetime.fromisoformat(access[uid]["expires_at"])
        return datetime.now() < expires_at
    except:
        return False


def extend_access(user_id, days, plan):
    access = load_access()
    uid = str(user_id)

    now = datetime.now()

    if uid in access:
        try:
            current_expiry = datetime.fromisoformat(access[uid]["expires_at"])
            start_date = max(now, current_expiry)
        except:
            start_date = now
    else:
        start_date = now

    new_expiry = start_date + timedelta(days=days)

    access[uid] = {
        "plan": plan,
        "expires_at": new_expiry.isoformat()
    }

    save_access(access)


def get_free_usage(user_id):
    usage = load_usage()
    uid = str(user_id)
    today = today_str()

    if uid not in usage or usage[uid].get("date") != today:
        usage[uid] = {"date": today, "count": 0}
        save_usage(usage)

    return usage[uid]["count"]


def increment_free_usage(user_id):
    usage = load_usage()
    uid = str(user_id)
    today = today_str()

    if uid not in usage or usage[uid].get("date") != today:
        usage[uid] = {"date": today, "count": 0}

    usage[uid]["count"] += 1
    save_usage(usage)


def can_use_bot(user_id):
    if has_active_pro(user_id):
        return True

    used = get_free_usage(user_id)
    return used < FREE_DAILY_LIMIT


def get_access_text(user_id):
    if has_active_pro(user_id):
        access = load_access()
        uid = str(user_id)
        plan = access[uid]["plan"]
        expires_at = datetime.fromisoformat(access[uid]["expires_at"])
        days_left = max(0, (expires_at - datetime.now()).days)
        return f"Pro {plan.title()} · {days_left} days left"

    used = get_free_usage(user_id)
    remaining = max(0, FREE_DAILY_LIMIT - used)
    return f"Free · {remaining}/{FREE_DAILY_LIMIT} analyses left today"


def extract_best_reply(text):
    try:
        start = text.index("🖤 Best Reply:") + len("🖤 Best Reply:")
        end = text.index("✨ Another Option:")
        return text[start:end].strip().strip('"')
    except:
        return ""


def extract_another_option(text):
    try:
        start = text.index("✨ Another Option:") + len("✨ Another Option:")

        possible_ends = ["🧠 Why it works:", "📩 Next step:"]
        end_positions = []

        for marker in possible_ends:
            if marker in text[start:]:
                end_positions.append(text.index(marker, start))

        end = min(end_positions) if end_positions else len(text)

        return text[start:end].strip().strip('"')
    except:
        return ""


def after_answer_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("📋 Best Reply", callback_data="copy_best_reply"),
            InlineKeyboardButton("📋 Another Option", callback_data="copy_another_option"),
        ],
        [InlineKeyboardButton("🔁 Give 2 more options", callback_data="regenerate_options")]
    ]

    return InlineKeyboardMarkup(keyboard)


async def show_paywall(message, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Pro Weekly — $3.99/week", callback_data="buy_weekly")],
        [InlineKeyboardButton("⭐ Pro Monthly — $9.99/month", callback_data="buy_monthly")],
    ]

    text = """
You’ve used your 3 free replies today 🖤

Unlock SheTexted Pro:

• Unlimited reply generation
• Screenshot & chat analysis
• Better texting energy
• Smarter, smoother replies
• Dating app conversation help

⭐ Most users choose Monthly
"""

    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def send_invoice(query, context: ContextTypes.DEFAULT_TYPE, plan):
    if plan == "weekly":
        title = "SheTexted Pro Weekly"
        description = "7 days of SheTexted Pro access"
        payload = "weekly_pro"
        stars = WEEKLY_STARS
    else:
        title = "SheTexted Pro Monthly"
        description = "30 days of SheTexted Pro access"
        payload = "monthly_pro"
        stars = MONTHLY_STARS

    await context.bot.send_invoice(
        chat_id=query.message.chat_id,
        title=title,
        description=description,
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(title, stars)],
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    track_user(user_id)

    access_text = get_access_text(user_id)

    await update.message.reply_text(
        START_TEXT + f"\n\n✅ Your access: {access_text}"
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if user_id != ADMIN_ID:
        return

    stats_data = load_stats()
    stats_data = reset_daily_stats(stats_data)
    save_stats(stats_data)

    access = load_access()
    active_pro_users = 0

    for uid in access:
        try:
            expires_at = datetime.fromisoformat(access[uid]["expires_at"])
            if datetime.now() < expires_at:
                active_pro_users += 1
        except:
            pass

    text = (
        f"📊 SheTexted Stats\n\n"
        f"👥 Total users: {len(stats_data['users'])}\n"
        f"🆕 New today: {stats_data['new_users_today']}\n"
        f"💬 Messages today: {stats_data['messages_today']}\n"
        f"📩 Total messages: {stats_data['total_messages']}\n"
        f"💎 Active Pro users: {active_pro_users}"
    )

    await update.message.reply_text(text)


async def extract_text_from_image(photo_file):
    image_bytes = await photo_file.download_as_bytearray()
    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Extract all text from this chat screenshot exactly as written. Preserve names, emojis, timestamps, and message order if visible."
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:image/jpeg;base64,{base64_image}",
                    },
                ],
            }
        ],
    )

    return response.output_text


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    track_user(user_id)

    if not can_use_bot(user_id):
        await show_paywall(update.message, context)
        return

    text = ""

    if update.message.text:
        text = update.message.text

    elif update.message.photo:
        loading = await update.message.reply_text("Reading screenshot...")

        photo = update.message.photo[-1]
        photo_file = await photo.get_file()

        text = await extract_text_from_image(photo_file)

        await loading.delete()

    user_messages[user_id] = text

    keyboard = [
        [
            InlineKeyboardButton("Flirty 🖤", callback_data="flirty"),
            InlineKeyboardButton("Playful 😏", callback_data="playful"),
        ],
        [
            InlineKeyboardButton("Confident 🔥", callback_data="confident"),
            InlineKeyboardButton("Chill 🙂", callback_data="chill"),
        ]
    ]

    remaining = max(0, FREE_DAILY_LIMIT - get_free_usage(user_id))

    if has_active_pro(user_id):
        usage_text = "Pro access active 💎"
    else:
        usage_text = f"Free analyses left today: {remaining}/{FREE_DAILY_LIMIT}"

    await update.message.reply_text(
        f"What vibe do you want?\n\n{usage_text}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def generate_main_answer(user_text, vibe):
    prompt = f"""
You are SheTexted — a socially intelligent AI texting assistant.

The user selected this vibe: {vibe}

Return ONLY this exact format:

🔥 What her message likely means:
Write EXACTLY 2 short natural sentences explaining her vibe and emotional tone.

🖤 Best Reply:
Write the strongest reply the user should send.

✨ Another Option:
Write 1 alternative version with slightly different energy.

🧠 Why it works:
Write ONLY 1 short sentence explaining why the replies work socially.

📩 Next step:
Send another chat for analysis ✨

Rules:
- ONLY give 2 reply options total
- Casual natural English
- Sound human
- Avoid cringe
- Avoid neediness
- Keep answers concise
- Make replies copy-paste ready

Chat:
{user_text}
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        temperature=0.85,
        max_output_tokens=320
    )

    return response.output_text


async def generate_more_options(user_text):
    prompt = f"""
You are SheTexted — a modern AI texting assistant.

Give exactly 2 fresh reply options for this chat.

Return ONLY this exact format:

🖤 Best Reply:
Write 1 strong confident reply.

✨ Another Option:
Write 1 alternative reply with different energy.

Rules:
- Casual English
- No explanations
- Replies must be copy-paste ready

Chat:
{user_text}
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        temperature=0.9,
        max_output_tokens=320
    )

    return response.output_text


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    track_user(user_id)

    if query.data == "buy_weekly":
        await send_invoice(query, context, "weekly")
        return

    if query.data == "buy_monthly":
        await send_invoice(query, context, "monthly")
        return

    if not can_use_bot(user_id):
        await show_paywall(query.message, context)
        return

    user_text = user_messages.get(user_id, "")

    if not user_text:
        await query.message.reply_text("Send me a chat first 🖤")
        return

    if query.data == "copy_best_reply":
        last_output = user_last_outputs.get(user_id, "")
        best_reply = extract_best_reply(last_output)

        if best_reply:
            await query.message.reply_text(
                f"`{best_reply}`",
                parse_mode="Markdown"
            )
        else:
            await query.message.reply_text("No reply found.")
        return

    if query.data == "copy_another_option":
        last_output = user_last_outputs.get(user_id, "")
        another_option = extract_another_option(last_output)

        if another_option:
            await query.message.reply_text(
                f"`{another_option}`",
                parse_mode="Markdown"
            )
        else:
            await query.message.reply_text("No option found.")
        return

    if query.data == "regenerate_options":
        loading_msg = await query.message.reply_text("Generating 2 more options...")
        output = await generate_more_options(user_text)

        user_last_outputs[user_id] = output

        if not has_active_pro(user_id):
            increment_free_usage(user_id)

        await loading_msg.delete()

        await query.message.reply_text(
            output,
            reply_markup=after_answer_keyboard()
        )

        return

    loading_msg = await query.message.reply_text("Analyzing conversation...")

    vibe = query.data
    output = await generate_main_answer(user_text, vibe)

    user_last_outputs[user_id] = output

    if not has_active_pro(user_id):
        increment_free_usage(user_id)

    await loading_msg.delete()

    await query.message.reply_text(
        output,
        reply_markup=after_answer_keyboard()
    )


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    payment = update.message.successful_payment

    if payment.invoice_payload == "weekly_pro":
        extend_access(user_id, 7, "weekly")
        await update.message.reply_text(
            "✅ Payment received!\n\nSheTexted Pro Weekly is active for 7 days 🖤"
        )

    elif payment.invoice_payload == "monthly_pro":
        extend_access(user_id, 30, "monthly")
        await update.message.reply_text(
            "✅ Payment received!\n\nSheTexted Pro Monthly is active for 30 days 🖤"
        )


def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))

    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))

    app.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment_callback
        )
    )

    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO) & ~filters.COMMAND,
            handle_message
        )
    )

    app.add_handler(CallbackQueryHandler(handle_callback))

    print("SheTexted bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()