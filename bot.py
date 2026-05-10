import os
import base64
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
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

STATS_FILE = "stats.json"
ACCESS_FILE = "access.json"
USAGE_FILE = "usage.json"

ADMIN_ID = 669799237

FREE_DAILY_LIMIT = 3
WEEKLY_STARS = 200
MONTHLY_STARS = 500

START_TEXT = """
💬 Welcome to SheTexted

Send a screenshot or copy your chat.

I’ll analyze:
• what she actually means
• best reply for your goal
• emotional tone
• flirting signals
• mixed energy

Free users get 3 analyses per day.

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
        usage[uid] = {
            "date": today,
            "count": 0
        }
        save_usage(usage)

    return usage[uid]["count"]


def increment_free_usage(user_id):
    usage = load_usage()
    uid = str(user_id)
    today = today_str()

    if uid not in usage or usage[uid].get("date") != today:
        usage[uid] = {
            "date": today,
            "count": 0
        }

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


def after_answer_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔁 Give 3 more options", callback_data="regenerate_options")],
        [InlineKeyboardButton("🧠 What she really means", callback_data="meaning_only")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def show_paywall(message, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Pro Weekly — $3.99/week", callback_data="buy_weekly")],
        [InlineKeyboardButton("⭐ Pro Monthly — $9.99/month", callback_data="buy_monthly")],
    ]

    text = """
You’ve used your 3 free analyses today 🖤

Unlock SheTexted Pro:

• Unlimited AI replies
• Chat screenshot analysis
• Flirty, playful, confident & chill replies
• Deep message meaning
• Dating app support

⭐ Monthly is the best value.
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

Your personality:
- emotionally sharp
- modern dating-aware
- confident but not cringe
- direct but not rude
- playful when appropriate
- never robotic
- never overly therapeutic
- never manipulative
- never pickup-artist style

Your job:
Analyze the emotional dynamics of the chat, the hidden intention, attraction level, tension, effort, and the best social move.
Sound like a smart friend who understands texting, dating apps, flirting, mixed signals, ghosting, exes, and situationships.

The user selected this vibe: {vibe}

Return ONLY this exact format with emojis and spacing:

🔥 What her message likely means:
Write 2 natural sentences. Explain her vibe, emotional tone, interest level, and social dynamic. Be specific to the message. Avoid generic phrases like "she seems interested" unless the chat clearly shows that.

🖤 Best Reply:
"Write 1 short natural text the user can send. Make it confident, human, and matched to the selected vibe."

🔥 Bolder Option:
"Write 1 slightly more playful or confident version. It should still feel natural and not too much."

🙂 Chill Option:
"Write 1 calm, low-pressure version. It should feel easy, smooth, and not needy."

🧠 Why it works:
Write 2 short sentences explaining why these replies work emotionally and socially. Mention confidence, pressure, curiosity, tension, playfulness, or clarity only when relevant.

📩 Next step:
Send another chat for analysis ✨

Rules:
- Always give exactly 3 reply options
- No other sections
- No bullet points
- No long essays
- Casual English
- Sound like a real person, not ChatGPT
- Do not overhype
- Do not say "high value"
- Do not be needy
- Do not be aggressive
- Do not make the user look desperate
- If her energy is low, do not pretend it is high
- If she is dry, call it out calmly
- If she is warm, make the reply smooth and confident
- If context is unclear, say it naturally without overexplaining
- Always give replies that can actually be copied and sent
- Always end with the Next step section exactly as shown

Chat:
{user_text}
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        temperature=0.85,
        max_output_tokens=340
    )

    return response.output_text


async def generate_more_options(user_text):
    prompt = f"""
You are SheTexted — a modern AI texting assistant.

Give exactly 3 fresh reply options for this chat.

Format exactly:

🖤 Best Reply:
"Write 1 short confident reply."

🔥 Bolder Option:
"Write 1 more playful/flirty reply."

🙂 Chill Option:
"Write 1 calm low-pressure reply."

Rules:
- Casual English
- Make all 3 options different
- No explanations
- No bullet points
- Replies must be copy-paste ready
- Do not sound needy
- Do not sound aggressive
- Do not overdo it

Chat:
{user_text}
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        temperature=0.9,
        max_output_tokens=240
    )

    return response.output_text


async def generate_meaning_only(user_text):
    prompt = f"""
You are SheTexted — a socially intelligent AI texting assistant.

Analyze what her message really means.

Return exactly this format:

🧠 What she really means:
Write 3-4 natural sentences explaining her vibe, emotional tone, interest level, and hidden intention.

🚩 Watch out for:
Write 1 short sentence about any red flag, mixed signal, low effort, or unclear energy. If there is no red flag, say that calmly.

✅ Best move:
Write 1 short sentence explaining what the user should do next.

Rules:
- Casual English
- Be honest
- If her energy is low, say it calmly
- If she seems interested, explain why
- Do not overhype
- Do not sound robotic
- No long essay

Chat:
{user_text}
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        temperature=0.75,
        max_output_tokens=260
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

    if query.data == "regenerate_options":
        loading_msg = await query.message.reply_text("Generating 3 more options...")
        output = await generate_more_options(user_text)

        if not has_active_pro(user_id):
            increment_free_usage(user_id)

        await loading_msg.delete()
        await query.message.reply_text(
            output,
            reply_markup=after_answer_keyboard()
        )
        return

    if query.data == "meaning_only":
        loading_msg = await query.message.reply_text("Reading the vibe...")
        output = await generate_meaning_only(user_text)

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