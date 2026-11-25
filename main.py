
import logging
import os
import sqlite3
from html import escape

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
MAX_USERS = int(os.getenv("MAX_USERS", "10"))
DB_PATH = os.getenv("DB_PATH", "bot_data.sqlite3")
TAG_BATCH_LIMIT = int(os.getenv("TAG_BATCH_LIMIT", "20"))

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                status TEXT DEFAULT 'pending'
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS opted_in (
                chat_id INTEGER,
                user_id INTEGER,
                username TEXT,
                first_name TEXT,
                PRIMARY KEY(chat_id, user_id)
            )
        """)


def is_owner(user_id):
    return user_id == OWNER_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    with get_db() as conn:
        row = conn.execute(
            "SELECT status FROM users WHERE user_id=?",
            (user.id,)
        ).fetchone()

        if not row:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM users "
                "WHERE status IN ('pending', 'approved')"
            ).fetchone()["n"]

            if count >= MAX_USERS and not is_owner(user.id):
                await update.message.reply_text(
                    "Sorry, the maximum user limit has been reached."
                )
                return

            conn.execute(
                "INSERT INTO users(user_id, username, status) "
                "VALUES (?, ?, 'pending')",
                (user.id, user.username or "")
            )
            status = "pending"
        else:
            status = row["status"]

    if is_owner(user.id):
        await update.message.reply_text(
            "Welcome Owner! Use /help to see commands."
        )

    elif status == "approved":
        await update.message.reply_text(
            "Your access is approved. Welcome!"
        )

    elif status == "rejected":
        await update.message.reply_text(
            "Your access request was rejected."
        )

    else:
        await update.message.reply_text(
            "Your request has been submitted successfully.\n"
            "Please wait until the admin approves it."
        )

        try:
            await context.bot.send_message(
                OWNER_ID,
                f"New user request:\n"
                f"ID: {user.id}\n"
                f"Username: @{user.username or 'none'}\n\n"
                f"Approve: /approve {user.id}\n"
                f"Reject: /reject {user.id}"
            )
        except Exception:
            logger.exception("Owner notification failed")


async def help_command(update, context):
    text = (
        "Available Commands:\n\n"
        "/start - Start bot\n"
        "/help - Help menu\n"
        "/join - Opt in to group mentions\n"
        "/leave - Opt out of mentions\n"
        "/tagall MESSAGE - Mention opted-in members\n"
    )

    if is_owner(update.effective_user.id):
        text += (
            "\nOwner Commands:\n"
            "/users - List users\n"
            "/approve ID - Approve user\n"
            "/reject ID - Reject user\n"
            "/revoke ID - Revoke access\n"
        )

    await update.message.reply_text(text)


async def check_access(update):
    user = update.effective_user

    if is_owner(user.id):
        return True

    with get_db() as conn:
        row = conn.execute(
            "SELECT status FROM users WHERE user_id=?",
            (user.id,)
        ).fetchone()

    if not row or row["status"] != "approved":
        await update.message.reply_text(
            "Your access is not approved yet. Please wait for admin approval."
        )
        return False

    return True


async def approve(update, context):
    if not is_owner(update.effective_user.id):
        return

    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text(
            "Usage: /approve USER_ID"
        )
        return

    target = int(context.args[0])

    with get_db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE status='approved'"
        ).fetchone()["n"]

        existing = conn.execute(
            "SELECT status FROM users WHERE user_id=?",
            (target,)
        ).fetchone()

        if not existing:
            await update.message.reply_text("User not found.")
            return

        if existing["status"] != "approved" and count >= MAX_USERS:
            await update.message.reply_text(
                "Maximum approved-user limit reached."
            )
            return

        conn.execute(
            "UPDATE users SET status='approved' WHERE user_id=?",
            (target,)
        )

    await update.message.reply_text(
        f"User {target} approved successfully."
    )

    try:
        await context.bot.send_message(
            target,
            "Your access has been approved!"
        )
    except Exception:
        logger.exception("Approval notification failed")


async def reject(update, context):
    if not is_owner(update.effective_user.id):
        return

    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text(
            "Usage: /reject USER_ID"
        )
        return

    target = int(context.args[0])

    with get_db() as conn:
        conn.execute(
            "UPDATE users SET status='rejected' WHERE user_id=?",
            (target,)
        )

    await update.message.reply_text(
        f"User {target} rejected."
    )

    try:
        await context.bot.send_message(
            target,
            "Your access request was rejected."
        )
    except Exception:
        pass


async def revoke(update, context):
    if not is_owner(update.effective_user.id):
        return

    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text(
            "Usage: /revoke USER_ID"
        )
        return

    target = int(context.args[0])

    with get_db() as conn:
        conn.execute(
            "UPDATE users SET status='rejected' WHERE user_id=?",
            (target,)
        )

    await update.message.reply_text(
        f"Access revoked for {target}."
    )


async def users(update, context):
    if not is_owner(update.effective_user.id):
        return

    with get_db() as conn:
        rows = conn.execute(
            "SELECT user_id, username, status FROM users"
        ).fetchall()

    if not rows:
        await update.message.reply_text("No users found.")
        return

    result = ["Registered Users:"]

    for row in rows:
        result.append(
            f"{row['user_id']} | "
            f"@{row['username'] or 'none'} | "
            f"{row['status']}"
        )

    await update.message.reply_text("\n".join(result))


async def join_group(update, context):
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "Use this command inside a group."
        )
        return

    if not await check_access(update):
        return

    user = update.effective_user

    with get_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO opted_in
            (chat_id, user_id, username, first_name)
            VALUES (?, ?, ?, ?)
            """,
            (
                update.effective_chat.id,
                user.id,
                user.username or "",
                user.first_name or ""
            )
        )

    await update.message.reply_text(
        "You have opted in to group mentions."
    )


async def leave_group(update, context):
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "Use this command inside a group."
        )
        return

    user = update.effective_user

    with get_db() as conn:
        conn.execute(
            "DELETE FROM opted_in WHERE chat_id=? AND user_id=?",
            (update.effective_chat.id, user.id)
        )

    await update.message.reply_text(
        "You have opted out of group mentions."
    )


async def tagall(update, context):
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "This command only works in groups."
        )
        return

    if not await check_access(update):
        return

    member = await context.bot.get_chat_member(
        update.effective_chat.id,
        update.effective_user.id
    )

    if member.status not in ("administrator", "creator"):
        await update.message.reply_text(
            "Only group administrators can use /tagall."
        )
        return

    message = " ".join(context.args).strip()

    if not message:
        await update.message.reply_text(
            "Usage: /tagall Your message"
        )
        return

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT user_id, username, first_name
            FROM opted_in
            WHERE chat_id=?
            ORDER BY user_id
            """,
            (update.effective_chat.id,)
        ).fetchall()

    if not rows:
        await update.message.reply_text(
            "No opted-in members found. Members can use /join."
        )
        return

    rows = rows[:TAG_BATCH_LIMIT]

    mentions = []

    for row in rows:
        name = row["first_name"] or row["username"] or "Member"

        mentions.append(
            f'<a href="tg://user?id={row["user_id"]}">'
            f'{escape(name)}</a>'
        )

    response = (
        f"{escape(message)}\n\n"
        + " ".join(mentions)
    )

    await update.message.reply_text(
        response,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )


async def post_init(application):
    await application.bot.set_my_commands([
        ("start", "Start bot"),
        ("help", "Help"),
        ("join", "Opt in to mentions"),
        ("leave", "Opt out of mentions"),
        ("tagall", "Mention opted-in members"),
    ])


def main():
    init_db()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(CommandHandler("revoke", revoke))
    app.add_handler(CommandHandler("users", users))
    app.add_handler(CommandHandler("join", join_group))
    app.add_handler(CommandHandler("leave", leave_group))
    app.add_handler(CommandHandler("tagall", tagall))

    logger.info("Telegram bot starting...")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
