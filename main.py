#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات مادر ساخت ربات چت ناشناس - نسخه فوق‌العاده ساده
"""

import os
import sys
import logging
import sqlite3
import hashlib
import time
from datetime import datetime
from contextlib import contextmanager

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# ==================== کلاس دیتابیس ====================
class Database:
    def __init__(self, db_path="bots.db"):
        self.db_path = db_path
        self.init_db()
    
    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def init_db(self):
        with self.get_connection() as conn:
            c = conn.cursor()
            
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at TEXT,
                bot_count INTEGER DEFAULT 0
            )''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS bots (
                bot_id TEXT PRIMARY KEY,
                token TEXT UNIQUE,
                owner_id INTEGER,
                bot_username TEXT,
                bot_name TEXT,
                created_at TEXT,
                status TEXT DEFAULT 'active'
            )''')
            
            conn.commit()
    
    def add_user(self, user_id, username, first_name, last_name=""):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('''INSERT OR IGNORE INTO users 
                       (user_id, username, first_name, last_name, created_at) 
                       VALUES (?, ?, ?, ?, ?)''',
                     (user_id, username or "", first_name, last_name, datetime.now().isoformat()))
            conn.commit()
    
    def add_bot(self, bot_id, token, owner_id, bot_username, bot_name):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('''INSERT OR REPLACE INTO bots 
                       (bot_id, token, owner_id, bot_username, bot_name, created_at) 
                       VALUES (?, ?, ?, ?, ?, ?)''',
                     (bot_id, token, owner_id, bot_username, bot_name, datetime.now().isoformat()))
            
            c.execute('''UPDATE users 
                       SET bot_count = bot_count + 1 
                       WHERE user_id = ?''', (owner_id,))
            
            conn.commit()
    
    def get_user_bots(self, user_id):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM bots WHERE owner_id = ? ORDER BY created_at DESC', (user_id,))
            return [dict(row) for row in c.fetchall()]
    
    def get_user_bot_count(self, user_id):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('SELECT bot_count FROM users WHERE user_id = ?', (user_id,))
            row = c.fetchone()
            return row['bot_count'] if row else 0
    
    def get_bot_by_token(self, token):
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM bots WHERE token = ?', (token,))
            row = c.fetchone()
            return dict(row) if row else None

# ==================== تلگرام را import می‌کنیم ====================
try:
    # برای Python 3.13 و بالاتر
    import warnings
    warnings.filterwarnings("ignore")
    
    from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
    from telegram.ext import Updater, CommandHandler, MessageHandler, CallbackQueryHandler, CallbackContext, Filters
    from telegram import ParseMode
    import telegram
    
    logger.info("✅ کتابخانه تلگرام با موفقیت import شد")
    TELEGRAM_OK = True
    
except ImportError as e:
    logger.error(f"❌ خطا در import تلگرام: {e}")
    TELEGRAM_OK = False

# ==================== کلاس ربات اصلی ====================
class SimpleMotherBot:
    def __init__(self):
        # خواندن توکن از محیط
        self.token = os.environ.get('MOTHER_BOT_TOKEN', '').strip()
        if not self.token or self.token == 'YOUR_BOT_TOKEN_HERE':
            logger.error("❌ لطفاً توکن ربات را تنظیم کنید!")
            logger.error("مقدار: MOTHER_BOT_TOKEN")
            raise ValueError("توکن تنظیم نشده است")
        
        self.db = Database()
        self.max_bots = int(os.environ.get('MAX_BOTS_PER_USER', '3'))
        
        if not TELEGRAM_OK:
            logger.error("❌ کتابخانه تلگرام در دسترس نیست!")
            raise ImportError("لطفاً python-telegram-bot را نصب کنید")
        
        # ایجاد Updater
        self.updater = Updater(self.token, use_context=True)
        self.dispatcher = self.updater.dispatcher
        
        # تنظیم هندلرها
        self.setup_handlers()
        
        logger.info(f"✅ ربات با توکن {self.token[:10]}... راه‌اندازی شد")
    
    def setup_handlers(self):
        """تنظیم هندلرهای ربات"""
        # دستورات
        self.dispatcher.add_handler(CommandHandler("start", self.cmd_start))
        self.dispatcher.add_handler(CommandHandler("help", self.cmd_help))
        self.dispatcher.add_handler(CommandHandler("mybots", self.cmd_mybots))
        self.dispatcher.add_handler(CommandHandler("profile", self.cmd_profile))
        
        # پیام‌های متنی
        self.dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, self.handle_text))
        
        # کلیک روی دکمه‌ها
        self.dispatcher.add_handler(CallbackQueryHandler(self.handle_callback))
    
    def cmd_start(self, update: Update, context: CallbackContext):
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
            "کاربران می‌توانند پیام‌های ناشناس برای شما ارسال کنند.\n\n"
            "👇 از دکمه‌های زیر استفاده کنید:"
        )
        
        update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    def cmd_help(self, update: Update, context: CallbackContext):
        """دستور /help"""
        text = (
            "📚 **راهنمای استفاده:**\n\n"
            "1. به @BotFather بروید\n"
            "2. دستور /newbot را بزنید\n"
            "3. یک ربات جدید بسازید\n"
            "4. توکن ربات را کپی کنید\n"
            "5. توکن را برای این ربات ارسال کنید\n\n"
            "📌 **توکن ربات:**\n"
            "`1234567890:ABCdefGHIJKLMNopqRSTUvwxYZ`\n\n"
            "🔹 **دستورات:**\n"
            "/start - شروع کار\n"
            "/mybots - ربات‌های شما\n"
            "/profile - اطلاعات شما\n"
            "/help - این راهنما\n\n"
            "⚠️ **توجه:** توکن ربات مانند رمز عبور است!"
        )
        
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    def cmd_mybots(self, update: Update, context: CallbackContext):
        """دستور /mybots"""
        user = update.effective_user
        bots = self.db.get_user_bots(user.id)
        
        if not bots:
            update.message.reply_text(
                "📭 **شما هنوز هیچ رباتی نساخته‌اید!**\n\n"
                "برای ساخت اولین ربات، روی '🤖 ساخت ربات جدید' کلیک کنید.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        text = "🤖 **ربات‌های شما:**\n\n"
        for i, bot in enumerate(bots, 1):
            created = datetime.fromisoformat(bot['created_at']).strftime('%Y-%m-%d')
            text += f"{i}. **{bot['bot_name']}**\n"
            text += f"   👤: @{bot['bot_username']}\n"
            text += f"   📅: {created}\n\n"
        
        # دکمه‌ها
        keyboard = []
        for bot in bots[:3]:
            keyboard.append([
                InlineKeyboardButton(
                    f"🔗 {bot['bot_name']}",
                    url=f"https://t.me/{bot['bot_username']}"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton("➕ ساخت جدید", callback_data="create_bot"),
            InlineKeyboardButton("🔄 بروزرسانی", callback_data="refresh")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    def cmd_profile(self, update: Update, context: CallbackContext):
        """دستور /profile"""
        user = update.effective_user
        bot_count = self.db.get_user_bot_count(user.id)
        
        text = (
            f"👤 **پروفایل شما:**\n\n"
            f"🆔 آیدی: `{user.id}`\n"
            f"👤 نام: {user.first_name} {user.last_name or ''}\n"
            f"📱 کاربری: @{user.username or 'ندارد'}\n"
            f"🤖 ربات‌ها: {bot_count}/{self.max_bots}\n\n"
            f"برای ساخت ربات جدید روی '🤖 ساخت ربات جدید' کلیک کنید."
        )
        
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    def handle_text(self, update: Update, context: CallbackContext):
        """مدیریت پیام‌های متنی"""
        user = update.effective_user
        text = update.message.text
        
        if text == "🤖 ساخت ربات جدید":
            update.message.reply_text(
                "🔑 **لطفاً توکن ربات خود را ارسال کنید:**\n\n"
                "توکن ربات شما چیزی شبیه به این است:\n"
                "`1234567890:ABCdefGHIJKLMNopqRSTUvwxYZ`",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['waiting_for_token'] = True
        
        elif text == "📋 ربات‌های من":
            self.cmd_mybots(update, context)
        
        elif text == "ℹ️ راهنما":
            self.cmd_help(update, context)
        
        elif text == "👤 پروفایل":
            self.cmd_profile(update, context)
        
        elif context.user_data.get('waiting_for_token'):
            self.process_token(update, context, text)
            context.user_data.pop('waiting_for_token', None)
        
        else:
            update.message.reply_text(
                "لطفاً از دکمه‌های زیر استفاده کنید:\n\n"
                "• 🤖 ساخت ربات جدید\n"
                "• 📋 ربات‌های من\n"
                "• ℹ️ راهنما\n"
                "• 👤 پروفایل"
            )
    
    def process_token(self, update: Update, context: CallbackContext, token: str):
        """پردازش توکن ربات"""
        user = update.effective_user
        
        # بررسی تعداد
        bot_count = self.db.get_user_bot_count(user.id)
        if bot_count >= self.max_bots:
            update.message.reply_text(
                f"⚠️ **شما به حداکثر تعداد ربات رسیده‌اید!**\n\n"
                f"تعداد ربات‌ها: {bot_count}\n"
                f"حداکثر مجاز: {self.max_bots}",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # اعتبارسنجی
        if not self.validate_token(token):
            update.message.reply_text(
                "❌ **توکن نامعتبر است!**\n\n"
                "فرمت صحیح:\n"
                "`عدد:رشته‌ای از حروف و اعداد`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # بررسی تکراری نبودن
        if self.db.get_bot_by_token(token):
            update.message.reply_text(
                "⚠️ **این توکن قبلاً ثبت شده است!**",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # تست توکن
        bot_info = self.test_token(token)
        if not bot_info:
            update.message.reply_text(
                "❌ **نمی‌توانم به ربات دسترسی پیدا کنم!**\n\n"
                "لطفاً توکن را بررسی کنید.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # ساخت آیدی
        bot_hash = hashlib.md5(f"{token}_{user.id}_{int(time.time())}".encode()).hexdigest()[:8]
        bot_id = f"bot_{bot_hash}"
        
        # ذخیره
        self.db.add_bot(bot_id, token, user.id, bot_info['username'], bot_info['name'])
        
        # نمایش موفقیت
        success_text = (
            f"🎉 **ربات شما ساخته شد!**\n\n"
            f"🤖 **ربات:** {bot_info['name']}\n"
            f"👤 **مالک:** شما\n"
            f"📅 **زمان:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"✅ ربات شما آماده است!\n"
            f"کاربران می‌توانند پیام ناشناس ارسال کنند.\n\n"
            f"🔗 **لینک:** https://t.me/{bot_info['username']}"
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
                InlineKeyboardButton("➕ ساخت جدید", callback_data="create_bot"),
                InlineKeyboardButton("📋 همه ربات‌ها", callback_data="show_bots")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(
            success_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # راهنما
        guide = (
            f"📖 **راهنمای استفاده:**\n\n"
            f"1. ربات شما (@{bot_info['username']}) آماده است\n"
            f"2. دوستانتان را به ربات دعوت کنید\n"
            f"3. آن‌ها پیام ناشناس ارسال می‌کنند\n"
            f"4. شما پیام‌ها را دریافت می‌کنید\n\n"
            f"✨ برای تغییر تنظیمات به @BotFather مراجعه کنید."
        )
        
        update.message.reply_text(guide, parse_mode=ParseMode.MARKDOWN)
    
    def handle_callback(self, update: Update, context: CallbackContext):
        """مدیریت کلیک روی دکمه‌ها"""
        query = update.callback_query
        query.answer()
        
        data = query.data
        
        if data == "create_bot":
            query.edit_message_text(
                "🔑 **لطفاً توکن ربات خود را ارسال کنید:**\n\n"
                "توکن ربات شما چیزی شبیه به این است:\n"
                "`1234567890:ABCdefGHIJKLMNopqRSTUvwxYZ`",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['waiting_for_token'] = True
        
        elif data == "show_bots":
            self.cmd_mybots(update, context)
        
        elif data == "refresh":
            self.cmd_mybots(update, context)
    
    def validate_token(self, token: str) -> bool:
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
    
    def test_token(self, token: str):
        """تست توکن"""
        try:
            test_updater = Updater(token, use_context=True)
            bot = test_updater.bot.get_me()
            
            return {
                'id': bot.id,
                'username': bot.username,
                'name': bot.first_name
            }
        except Exception as e:
            logger.error(f"خطا در تست توکن: {e}")
            return None
    
    def run(self):
        """اجرای ربات"""
        logger.info("🚀 ربات در حال راه‌اندازی...")
        
        # شروع پولینگ
        self.updater.start_polling()
        logger.info("✅ ربات شروع به کار کرد!")
        
        # نگه داشتن برنامه
        self.updater.idle()

# ==================== اجرای اصلی ====================
def main():
    """تابع اصلی"""
    
    print("=" * 60)
    print("🤖 **ربات مادر ساخت ربات چت ناشناس**")
    print("=" * 60)
    
    # بررسی توکن
    token = os.environ.get('MOTHER_BOT_TOKEN', '').strip()
    if not token or token == 'YOUR_BOT_TOKEN_HERE':
        print("\n⚠️  لطفاً توکن ربات را تنظیم کنید:")
        print("\nدر رندر:")
        print("1. به Dashboard بروید")
        print("2. روی سرویس خود کلیک کنید")
        print("3. به تب Environment بروید")
        print("4. متغیر جدید اضافه کنید:")
        print("   KEY: MOTHER_BOT_TOKEN")
        print("   VALUE: توکن_ربات_شما")
        print("\nمحلی:")
        print("export MOTHER_BOT_TOKEN='توکن_ربات_شما'")
        print("=" * 60)
        
        # اگر در رندر هستیم
        if os.environ.get('RENDER'):
            print("⏳ منتظر تنظیم توکن...")
            time.sleep(30)
            token = os.environ.get('MOTHER_BOT_TOKEN', '').strip()
            if not token or token == 'YOUR_BOT_TOKEN_HERE':
                print("❌ توکن تنظیم نشده. خروج...")
                return
    
    try:
        # ایجاد و اجرای ربات
        bot = SimpleMotherBot()
        
        print(f"\n✅ ربات راه‌اندازی شد")
        print(f"🔐 توکن: {token[:10]}...")
        print(f"📊 حداکثر ربات: {bot.max_bots}")
        print("=" * 60)
        print("\n🎯 به تلگرام بروید و /start را بزنید")
        print("=" * 60)
        
        bot.run()
        
    except Exception as e:
        logger.error(f"❌ خطا: {str(e)}")
        
        # در رندر منتظر می‌مانیم
        if os.environ.get('RENDER'):
            time.sleep(30)

if __name__ == "__main__":
    main()
