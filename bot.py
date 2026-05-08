import os
from dotenv import load_dotenv
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

user_messages = {}

START_TEXT = """
Hey 👋

Send me her message, and I’ll help you understand what it means and what to reply.
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(START_TEXT)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text

    user_messages[user_id] = text

    keyboard = [
        [
            InlineKeyboardButton("Playful 😭", callback_data="playful"),
            InlineKeyboardButton("Confident 😏", callback_data="confident"),
            InlineKeyboardButton("Chill 🙂", callback_data="chill"),
        ]
    ]

    await update.message.reply_text(
        "What vibe do you want?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_vibe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.message.reply_text("Thinking...")

    user_id = query.from_user.id
    vibe = query.data
    user_text = user_messages.get(user_id, "")

    prompt = f"""
You are SheTexted.

Return ONLY this exact format:

What her message likely means:
Write a natural explanation in maximum 2 sentences about her vibe, intentions, and emotional tone.
Sound emotionally intelligent and human, not robotic.

Best reply:
"1 natural confident text."

Another option:
"1 natural confident text."

Why it works:
Write 1-3 short sentences explaining why these replies work emotionally and socially.

Rules:
- No other sections
- No bullet points
- No long essays
- No emotional dynamic section
- No mistakes to avoid section
- No energy the user should give section
- Sound modern and natural
- Casual English
- Slightly detailed but easy to read
- Match the requested vibe
- Do not overanalyze too much

Message:
{user_text}

Vibe:
{vibe}
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        temperature=0.4,
        max_output_tokens=180
    )

    await query.message.reply_text(response.output_text)

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_vibe))

    print("SheTexted bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()