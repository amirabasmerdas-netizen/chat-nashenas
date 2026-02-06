#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات مادر ساخت ربات چت ناشناس - نسخه کاملاً ساده و سازگار با رندر
"""

import os
import logging
import json
import sqlite3
import hashlib
from datetime import datetime
from contextlib import contextmanager

# تنظیمات اولیه
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# تلگرام را import می‌کنیم
try:
    from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
    from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
    from telegram.constants import ParseMode
    TELEGRAM_AVAILABLE = True
    logger.info("کتابخانه تلگرام با موفقیت import شد")
except ImportError as e:
    logger.error(f"خطا در import تلگرام: {e}")
    TELEGRAM_AVAILABLE = False

# ==================== کلاس دیتابیس ====================
class Database:
    def __init__(self, db_path="bot_factory.db"):
        if os.environ.get('RENDER'):
            self.db_path = os.path.join(os.getcwd(), db_path)
        else:
            self.db_path = db_path
        self.init_db()
    
    @contextmanager
    def get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def init_db(self):
        with self.get_conn() as conn:
            c = conn.cursor()
            
            # جدول کاربران
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at TEXT,
                bot_count INTEGER DEFAULT 0
            )''')
            
            # جدول ربات‌ها
            c.execute('''CREATE TABLE IF NOT EXISTS bots (
                bot_id TEXT PRIMARY KEY,
                token TEXT UNIQUE,
                owner_id INTEGER,
                bot_username TEXT,
                created_at TEXT,
                status TEXT DEFAULT 'active',
                FOREIGN KEY (owner_id) REFERENCES users(user_id)
            )''')
            
            conn.commit()
    
    def add_user(self, user_id, username, first_name, last_name=""):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('''INSERT OR IGNORE INTO users 
                       (user_id, username, first_name, last_name, created_at) 
                       VALUES (?, ?, ?, ?, ?)''',
                     (user_id, username or "", first_name, last_name, datetime.now().isoformat()))
            conn.commit()
    
    def add_bot(self, bot_id, token, owner_id, bot_username):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO bots 
                       (bot_id, token, owner_id, bot_username, created_at) 
                       VALUES (?, ?, ?, ?, ?)''',
                     (bot_id, token, owner_id, bot_username, datetime.now().isoformat()))
            
            c.execute('''UPDATE users 
                       SET bot_count = bot_count + 1 
                       WHERE user_id = ?''', (owner_id,))
            
            conn.commit()
    
    def get_user_bots(self, user_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM bots WHERE owner_id = ?', (user_id,))
            return [dict(row) for row in c.fetchall()]
    
    def get_user_bot_count(self, user_id):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute('SELECT bot_count FROM users WHERE user_id = ?', (user_id,))
            row = c.fetchone()
            return row['bot_count'] if row else 0

# ==================== کلاس اصلی ربات ====================
class MotherBot:
    def __init__(self):
        # خواندن توکن از متغیر محیطی
        self.token = os.environ.get('MOTHER_BOT_TOKEN', '')
        if not self.token:
            logger.error("متغیر محیطی MOTHER_BOT_TOKEN تنظیم نشده است!")
            raise ValueError("لطفاً توکن ربات را تنظیم کنید")
        
        self.db = Database()
        self.max_bots = int(os.environ.get('MAX_BOTS_PER_USER', '3'))
        
        if not TELEGRAM_AVAILABLE:
            logger.error("کتابخانه تلگرام در دسترس نیست!")
            raise ImportError("لطفاً python-telegram-bot را نصب کنید")
        
        # ساخت اپلیکیشن
        self.application = Application.builder().token(self.token).build()
        
        # تنظیم هندلرها
        self.setup_handlers()
    
    def setup_handlers(self):
        """تنظیم هندلرهای ربات"""
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help))
        self.application.add_handler(CommandHandler("mybots", self.my_bots))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """دستور /start"""
        user = update.effective_user
        
        # ذخیره کاربر
        self.db.add_user(
            user.id,
            user.username or "",
            user.first_name,
            user.last_name or ""
        )
        
        # ایجاد کیبورد
        keyboard = [
            [KeyboardButton("🤖 ساخت ربات جدید")],
            [KeyboardButton("📋 ربات‌های من")],
            [KeyboardButton("ℹ️ راهنما"), KeyboardButton("👤 پروفایل")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        text = (
            "👋 **به ربات مادر ساخت ربات چت ناشناس خوش آمدید!**\n\n"
            "من می‌توانم برای شما ربات چت ناشناس شخصی بسازم.\n"
            "کاربران می‌توانند پیام‌های ناشناس برای ربات شما ارسال کنند.\n\n"
            "👇 از دکمه‌های زیر استفاده کنید:"
        )
        
        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """دستور /help"""
        text = (
            "📚 **راهنمای استفاده:**\n\n"
            "🔹 **مراحل ساخت ربات:**\n"
            "1. به @BotFather در تلگرام بروید\n"
            "2. دستور /newbot را بزنید\n"
            "3. یک ربات جدید بسازید\n"
            "4. توکن ربات را کپی کنید\n"
            "5. توکن را برای این ربات ارسال کنید\n\n"
            "🔹 **توکن ربات چیست؟**\n"
            "رشته‌ای شبیه به این:\n"
            "`1234567890:ABCdefGHIJKLMNopqRSTUvwxYZ`\n\n"
            "🔹 **دستورات:**\n"
            "/start - شروع کار با ربات\n"
            "/mybots - مشاهده ربات‌های شما\n"
            "/help - نمایش این راهنما\n\n"
            "⚠️ **توجه:**\n"
            "• توکن ربات مانند رمز عبور است\n"
            "• آن را با کسی به اشتراک نگذارید\n"
            "• در صورت گم شدن، می‌توانید از @BotFather توکن جدید بگیرید"
        )
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    async def my_bots(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """دستور /mybots"""
        user = update.effective_user
        bots = self.db.get_user_bots(user.id)
        
        if not bots:
            await update.message.reply_text(
                "📭 **شما هنوز هیچ رباتی نساخته‌اید!**\n\n"
                "برای ساخت اولین ربات، روی '🤖 ساخت ربات جدید' کلیک کنید.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        text = "🤖 **ربات‌های شما:**\n\n"
        for i, bot in enumerate(bots, 1):
            created = datetime.fromisoformat(bot['created_at']).strftime('%Y-%m-%d')
            text += f"{i}. **@{bot['bot_username']}**\n"
            text += f"   🆔: `{bot['bot_id']}`\n"
            text += f"   📅: {created}\n"
            text += f"   🔗: t.me/{bot['bot_username']}\n\n"
        
        # ایجاد دکمه‌ها
        keyboard = []
        for bot in bots[:3]:  # حداکثر 3 ربات در صفحه
            keyboard.append([
                InlineKeyboardButton(
                    f"🔗 @{bot['bot_username']}",
                    url=f"https://t.me/{bot['bot_username']}"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton("➕ ساخت ربات جدید", callback_data="create_bot"),
            InlineKeyboardButton("🔄 بروزرسانی", callback_data="refresh")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """مدیریت پیام‌های متنی"""
        user = update.effective_user
        text = update.message.text
        
        if text == "🤖 ساخت ربات جدید":
            await update.message.reply_text(
                "🔑 **لطفاً توکن ربات خود را ارسال کنید:**\n\n"
                "توکن ربات شما چیزی شبیه به این است:\n"
                "`1234567890:ABCdefGHIJKLMNopqRSTUvwxYZ`\n\n"
                "⚠️ دقت کنید که توکن را درست کپی کرده باشید.",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['waiting_for_token'] = True
        
        elif text == "📋 ربات‌های من":
            await self.my_bots(update, context)
        
        elif text == "ℹ️ راهنما":
            await self.help(update, context)
        
        elif text == "👤 پروفایل":
            bot_count = self.db.get_user_bot_count(user.id)
            text = (
                f"👤 **پروفایل شما:**\n\n"
                f"🆔 آیدی: `{user.id}`\n"
                f"👤 نام: {user.first_name} {user.last_name or ''}\n"
                f"📱 کاربری: @{user.username or 'ندارد'}\n"
                f"🤖 ربات‌ها: {bot_count}/{self.max_bots}\n\n"
                f"برای ساخت ربات جدید روی '🤖 ساخت ربات جدید' کلیک کنید."
            )
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        
        elif context.user_data.get('waiting_for_token'):
            await self.process_bot_token(update, context, text)
            context.user_data.pop('waiting_for_token', None)
        
        else:
            # اگر پیام غیرمنتظره بود، راهنمایی کنیم
            await update.message.reply_text(
                "لطفاً از دکمه‌های زیر استفاده کنید:\n\n"
                "• 🤖 ساخت ربات جدید - برای ساخت ربات\n"
                "• 📋 ربات‌های من - مشاهده ربات‌ها\n"
                "• ℹ️ راهنما - آموزش کامل\n"
                "• 👤 پروفایل - اطلاعات حساب شما"
            )
    
    async def process_bot_token(self, update: Update, context: ContextTypes.DEFAULT_TYPE, token: str):
        """پردازش توکن ربات"""
        user = update.effective_user
        
        # بررسی تعداد ربات‌ها
        bot_count = self.db.get_user_bot_count(user.id)
        if bot_count >= self.max_bots:
            await update.message.reply_text(
                f"⚠️ **شما به حداکثر تعداد ربات مجاز رسیده‌اید!**\n\n"
                f"تعداد ربات‌های شما: {bot_count}\n"
                f"حداکثر مجاز: {self.max_bots}\n\n"
                f"برای افزایش محدودیت با پشتیبانی تماس بگیرید.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # اعتبارسنجی فرمت توکن
        if not self.is_valid_token(token):
            await update.message.reply_text(
                "❌ **توکن نامعتبر است!**\n\n"
                "لطفاً بررسی کنید:\n"
                "1. توکن را درست کپی کرده‌اید\n"
                "2. فرمت توکن صحیح است\n"
                "3. توکن کامل ارسال شده است\n\n"
                "فرمت صحیح: `عدد:رشته‌ای از حروف و اعداد`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # بررسی صحت توکن
        bot_info = await self.get_bot_info(token)
        if not bot_info:
            await update.message.reply_text(
                "❌ **نمی‌توانم به ربات دسترسی پیدا کنم!**\n\n"
                "ممکن است:\n"
                "1. توکن اشتباه باشد\n"
                "2. ربات حذف شده باشد\n"
                "3. خطایی در ارتباط رخ داده باشد\n\n"
                "لطفاً توکن را دوباره بررسی کنید.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # ساخت آیدی منحصر به فرد
        bot_hash = hashlib.md5(f"{token}_{user.id}".encode()).hexdigest()[:8]
        bot_id = f"anon_{bot_hash}"
        
        # ذخیره در دیتابیس
        self.db.add_bot(bot_id, token, user.id, bot_info['username'])
        
        # نمایش موفقیت
        success_text = (
            f"🎉 **ربات شما با موفقیت ساخته شد!**\n\n"
            f"🤖 **ربات:** @{bot_info['username']}\n"
            f"👤 **مالک:** شما\n"
            f"📅 **زمان ساخت:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"✅ ربات شما آماده استفاده است!\n"
            f"کاربران می‌توانند پیام‌های ناشناس برای شما ارسال کنند.\n\n"
            f"🔗 **لینک ربات:** https://t.me/{bot_info['username']}"
        )
        
        # دکمه‌ها
        keyboard = [
            [
                InlineKeyboardButton(
                    "🔗 باز کردن ربات",
                    url=f"https://t.me/{bot_info['username']}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🤖 ساخت ربات دیگر",
                    callback_data="create_bot"
                ),
                InlineKeyboardButton(
                    "📋 مشاهده همه ربات‌ها",
                    callback_data="show_bots"
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            success_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # راهنمای استفاده
        guide_text = (
            f"📖 **چگونه از ربات خود استفاده کنید:**\n\n"
            f"1. ربات شما (@{bot_info['username']}) آماده است\n"
            f"2. دوستانتان را به ربات دعوت کنید\n"
            f"3. آن‌ها می‌توانند پیام ناشناس ارسال کنند\n"
            f"4. شما پیام‌ها را دریافت می‌کنید\n\n"
            f"✨ **نکته:** برای تغییر تنظیمات ربات به @BotFather مراجعه کنید."
        )
        
        await update.message.reply_text(guide_text, parse_mode=ParseMode.MARKDOWN)
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """مدیریت کلیک روی دکمه‌ها"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == "create_bot":
            await query.edit_message_text(
                "🔑 **لطفاً توکن ربات خود را ارسال کنید:**\n\n"
                "توکن ربات شما چیزی شبیه به این است:\n"
                "`1234567890:ABCdefGHIJKLMNopqRSTUvwxYZ`",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['waiting_for_token'] = True
        
        elif data == "show_bots":
            await self.my_bots(update, context)
        
        elif data == "refresh":
            await self.my_bots(update, context)
    
    def is_valid_token(self, token: str) -> bool:
        """اعتبارسنجی فرمت توکن"""
        try:
            parts = token.split(':')
            if len(parts) != 2:
                return False
            if not parts[0].isdigit():
                return False
            if len(parts[1]) < 10:
                return False
            return True
        except:
            return False
    
    async def get_bot_info(self, token: str):
        """دریافت اطلاعات ربات از تلگرام"""
        try:
            # ساخت اپلیکیشن موقت برای تست توکن
            test_app = Application.builder().token(token).build()
            async with test_app:
                bot = await test_app.bot.get_me()
                return {
                    'id': bot.id,
                    'username': bot.username,
                    'name': bot.first_name
                }
        except Exception as e:
            logger.error(f"خطا در دریافت اطلاعات ربات: {e}")
            return None
    
    def run(self):
        """اجرای ربات"""
        logger.info("🤖 ربات مادر در حال راه‌اندازی...")
        logger.info(f"توکن: {self.token[:10]}...")
        logger.info(f"حداکثر ربات هر کاربر: {self.max_bots}")
        
        self.application.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )

# ==================== اجرای اصلی ====================
def main():
    """تابع اصلی اجرا"""
    
    # نمایش راهنما اگر توکن تنظیم نشده
    if not os.environ.get('MOTHER_BOT_TOKEN'):
        print("=" * 60)
        print("🤖 **ربات مادر ساخت ربات چت ناشناس**")
        print("=" * 60)
        print("\n⚠️  لطفاً تنظیمات را کامل کنید:")
        print("\n1. توکن ربات مادر را از @BotFather دریافت کنید")
        print("2. متغیرهای محیطی را تنظیم کنید:")
        print("   export MOTHER_BOT_TOKEN='توکن_ربات_شما'")
        print("   export MAX_BOTS_PER_USER='3'")
        print("\n3. ربات را اجرا کنید:")
        print("   python main.py")
        print("\n4. برای استقرار روی رندر:")
        print("   - فایل‌های زیر را بسازید:")
        print("     • requirements.txt")
        print("     • render.yaml")
        print("   - به گیتهاب آپلود کنید")
        print("   - روی رندر Deploy کنید")
        print("=" * 60)
        
        # تست با توکن نمونه (فقط در محیط توسعه)
        if not os.environ.get('RENDER'):
            os.environ['MOTHER_BOT_TOKEN'] = 'YOUR_BOT_TOKEN_HERE'
            print("\n⚠️  اجرا با توکن نمونه برای تست...")
        else:
            return
    
    try:
        bot = MotherBot()
        bot.run()
    except Exception as e:
        logger.error(f"خطای اصلی: {str(e)}")
        
        # در رندر، منتظر بمان تا لاگ‌ها دیده شوند
        if os.environ.get('RENDER'):
            import time
            time.sleep(10)

if __name__ == "__main__":
    main()
