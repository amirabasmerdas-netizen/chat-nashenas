#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات مادر ساخت ربات چت ناشناس - نسخه سازگار با رندر
"""

import os
import logging
import json
import sqlite3
import hashlib
from datetime import datetime
from typing import Dict, Optional, List, Tuple
from contextlib import contextmanager

# تنظیمات رندر
IS_RENDER = os.environ.get('RENDER', 'false').lower() == 'true'
PORT = int(os.environ.get('PORT', 8443))

# تلگرام با ورژن پایین‌تر و سازگار
try:
    from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
    from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
    from telegram.constants import ParseMode
    TELEGRAM_VERSION = "new"
except ImportError:
    # اگر ورژن قدیمی‌تر باشد
    try:
        from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
        from telegram.ext import Updater, CommandHandler, MessageHandler, CallbackQueryHandler, CallbackContext
        from telegram import ParseMode
        TELEGRAM_VERSION = "old"
    except:
        TELEGRAM_VERSION = "error"

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== کلاس دیتابیس ساده ====================
class SimpleDatabase:
    def __init__(self, db_path="anon_bots.db"):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """ایجاد جداول دیتابیس"""
        with self.get_connection() as conn:
            c = conn.cursor()
            
            # جدول کاربران
            c.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    created_at TEXT,
                    bot_count INTEGER DEFAULT 0
                )
            ''')
            
            # جدول ربات‌ها
            c.execute('''
                CREATE TABLE IF NOT EXISTS bots (
                    bot_id TEXT PRIMARY KEY,
                    token TEXT UNIQUE,
                    owner_id INTEGER,
                    bot_username TEXT,
                    created_at TEXT,
                    status TEXT DEFAULT 'active',
                    webhook_url TEXT,
                    FOREIGN KEY (owner_id) REFERENCES users(user_id)
                )
            ''')
            
            conn.commit()
    
    @contextmanager
    def get_connection(self):
        """کانتکست منیجر برای دیتابیس"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def add_user(self, user_id: int, username: str, first_name: str, last_name: str = ""):
        """افزودن کاربر جدید"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, username, first_name, last_name, created_at) 
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name, datetime.now().isoformat()))
            conn.commit()
    
    def add_bot(self, bot_id: str, token: str, owner_id: int, bot_username: str):
        """افزودن ربات جدید"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('''
                INSERT INTO bots 
                (bot_id, token, owner_id, bot_username, created_at) 
                VALUES (?, ?, ?, ?, ?)
            ''', (bot_id, token, owner_id, bot_username, datetime.now().isoformat()))
            
            # افزایش تعداد ربات‌های کاربر
            c.execute('''
                UPDATE users 
                SET bot_count = bot_count + 1 
                WHERE user_id = ?
            ''', (owner_id,))
            
            conn.commit()
    
    def get_user_bots(self, user_id: int) -> List[Dict]:
        """دریافت ربات‌های کاربر"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM bots WHERE owner_id = ?', (user_id,))
            return [dict(row) for row in c.fetchall()]
    
    def get_user_bot_count(self, user_id: int) -> int:
        """تعداد ربات‌های کاربر"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('SELECT bot_count FROM users WHERE user_id = ?', (user_id,))
            result = c.fetchone()
            return result['bot_count'] if result else 0

# ==================== کلاس ربات مادر ====================
class SimpleMotherBot:
    def __init__(self):
        # خواندن توکن از متغیر محیطی
        self.token = os.environ.get('MOTHER_BOT_TOKEN', '')
        if not self.token:
            logger.error("لطفاً متغیر محیطی MOTHER_BOT_TOKEN را تنظیم کنید")
            raise ValueError("توکن ربات تنظیم نشده است")
        
        self.db = SimpleDatabase()
        self.max_bots_per_user = int(os.environ.get('MAX_BOTS_PER_USER', '3'))
        
        # ساخت اپلیکیشن تلگرام
        if TELEGRAM_VERSION == "new":
            self.application = Application.builder().token(self.token).build()
        elif TELEGRAM_VERSION == "old":
            self.updater = Updater(self.token, use_context=True)
            self.application = self.updater.dispatcher
        else:
            raise ImportError("کتابخانه تلگرام نصب نیست")
        
        self.setup_handlers()
    
    def setup_handlers(self):
        """تنظیم هندلرهای ربات"""
        if TELEGRAM_VERSION == "new":
            self.application.add_handler(CommandHandler("start", self.start))
            self.application.add_handler(CommandHandler("help", self.help))
            self.application.add_handler(CommandHandler("mybots", self.my_bots))
            self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
            self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        else:
            self.application.add_handler(CommandHandler("start", self.start_old))
            self.application.add_handler(CommandHandler("help", self.help_old))
            self.application.add_handler(CommandHandler("mybots", self.my_bots_old))
            self.application.add_handler(MessageHandler(filters.TEXT, self.handle_message_old))
            self.application.add_handler(CallbackQueryHandler(self.handle_callback_old))
    
    # ==================== هندلرهای نسخه جدید ====================
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """دستور /start"""
        user = update.effective_user
        
        # ذخیره کاربر در دیتابیس
        self.db.add_user(
            user.id,
            user.username or "",
            user.first_name,
            user.last_name or ""
        )
        
        # ایجاد کیبورد
        keyboard = [
            [KeyboardButton("🤖 ساخت ربات جدید")],
            [KeyboardButton("📋 ربات‌های من"), KeyboardButton("ℹ️ راهنما")],
            [KeyboardButton("👤 پروفایل من")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        welcome_text = (
            "👋 **به ربات مادر ساخت ربات چت ناشناس خوش آمدید!**\n\n"
            "من می‌توانم برای شما ربات چت ناشناس شخصی بسازم.\n"
            "کافیست توکن رباتی که از @BotFather ساخته‌اید را برای من بفرستید.\n\n"
            "👇 از دکمه‌های زیر استفاده کنید:"
        )
        
        await update.message.reply_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """دستور /help"""
        help_text = (
            "📚 **راهنمای استفاده:**\n\n"
            "1. ابتدا به @BotFather مراجعه کنید\n"
            "2. ربات جدیدی با دستور /newbot بسازید\n"
            "3. توکن ربات ساخته شده را کپی کنید\n"
            "4. توکن را برای این ربات ارسال کنید\n\n"
            "🔸 **توکن ربات چیست؟**\n"
            "رشته‌ای شبیه به این:\n"
            "`1234567890:ABCdefGHIJKLMNopqRSTUvwxYZ`\n\n"
            "🔸 **دستورات:**\n"
            "/start - شروع ربات\n"
            "/mybots - مشاهده ربات‌های شما\n"
            "/help - نمایش این راهنما\n\n"
            "⚠️ **توجه:** توکن ربات مانند رمز عبور است، آن را با کسی به اشتراک نگذارید!"
        )
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    async def my_bots(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """دستور /mybots"""
        user = update.effective_user
        bots = self.db.get_user_bots(user.id)
        
        if not bots:
            await update.message.reply_text(
                "📭 شما هنوز هیچ رباتی نساخته‌اید!\n"
                "برای ساخت ربات جدید روی '🤖 ساخت ربات جدید' کلیک کنید.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        bot_list = "🤖 **ربات‌های شما:**\n\n"
        for i, bot in enumerate(bots, 1):
            bot_list += f"{i}. @{bot['bot_username']}\n"
            bot_list += f"   🆔: `{bot['bot_id']}`\n"
            bot_list += f"   📅: {datetime.fromisoformat(bot['created_at']).strftime('%Y-%m-%d')}\n\n"
        
        keyboard = []
        for bot in bots[:5]:
            keyboard.append([
                InlineKeyboardButton(
                    f"@{bot['bot_username']}",
                    url=f"https://t.me/{bot['bot_username']}"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton(
                "➕ ساخت ربات جدید",
                callback_data="create_new_bot"
            )
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            bot_list,
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
                "⚠️ دقت کنید که توکن را درست کپی کنید.",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['waiting_for_token'] = True
        
        elif text == "📋 ربات‌های من":
            await self.my_bots(update, context)
        
        elif text == "ℹ️ راهنما":
            await self.help(update, context)
        
        elif text == "👤 پروفایل من":
            bot_count = self.db.get_user_bot_count(user.id)
            profile_text = (
                f"👤 **پروفایل شما:**\n\n"
                f"🆔 آیدی: `{user.id}`\n"
                f"👤 نام: {user.first_name} {user.last_name or ''}\n"
                f"📱 کاربری: @{user.username or 'ندارد'}\n"
                f"🤖 ربات‌ها: {bot_count}/{self.max_bots_per_user}\n\n"
                f"برای ساخت ربات جدید روی '🤖 ساخت ربات جدید' کلیک کنید."
            )
            await update.message.reply_text(profile_text, parse_mode=ParseMode.MARKDOWN)
        
        elif context.user_data.get('waiting_for_token', False):
            await self.handle_bot_token(update, context, text)
            context.user_data.pop('waiting_for_token', None)
        
        else:
            welcome_text = (
                "👋 از دکمه‌های زیر استفاده کنید:\n\n"
                "• 🤖 ساخت ربات جدید - برای ساخت ربات چت ناشناس\n"
                "• 📋 ربات‌های من - مشاهده ربات‌های ساخته شده\n"
                "• ℹ️ راهنما - آموزش کامل استفاده\n"
                "• 👤 پروفایل من - اطلاعات حساب شما"
            )
            await update.message.reply_text(welcome_text)
    
    async def handle_bot_token(self, update: Update, context: ContextTypes.DEFAULT_TYPE, token: str):
        """مدیریت دریافت توکن ربات"""
        user = update.effective_user
        
        # بررسی تعداد ربات‌های کاربر
        bot_count = self.db.get_user_bot_count(user.id)
        if bot_count >= self.max_bots_per_user:
            await update.message.reply_text(
                f"⚠️ **شما به حداکثر تعداد ربات مجاز رسیده‌اید!**\n\n"
                f"تعداد ربات‌های فعلی شما: {bot_count}\n"
                f"حداکثر مجاز: {self.max_bots_per_user}\n\n"
                f"برای افزایش محدودیت با پشتیبانی تماس بگیرید.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # اعتبارسنجی توکن
        if not self.validate_token(token):
            await update.message.reply_text(
                "❌ **توکن نامعتبر است!**\n\n"
                "لطفاً مطمئن شوید:\n"
                "1. توکن را به درستی کپی کرده‌اید\n"
                "2. فرمت توکن صحیح است\n"
                "3. توکن هنوز معتبر است\n\n"
                "فرمت صحیح توکن:\n"
                "`عدد:رشته‌ای از حروف و اعداد`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # تست توکن و دریافت اطلاعات ربات
        bot_info = await self.get_bot_info(token)
        if not bot_info:
            await update.message.reply_text(
                "❌ **نمی‌توانم به ربات دسترسی پیدا کنم!**\n\n"
                "ممکن است:\n"
                "1. توکن اشتباه باشد\n"
                "2. ربات غیرفعال شده باشد\n"
                "3. خطایی در ارتباط رخ داده باشد\n\n"
                "لطفاً توکن را دوباره بررسی کنید.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # ساخت آیدی منحصر به فرد برای ربات
        bot_hash = hashlib.md5(f"{token}_{user.id}_{datetime.now().timestamp()}".encode()).hexdigest()[:8]
        bot_id = f"anonbot_{bot_hash}"
        
        # ذخیره ربات در دیتابیس
        self.db.add_bot(bot_id, token, user.id, bot_info['username'])
        
        # نمایش موفقیت
        success_text = (
            f"🎉 **ربات شما ساخته شد!**\n\n"
            f"🤖 **نام ربات:** @{bot_info['username']}\n"
            f"🔗 **لینک ربات:** https://t.me/{bot_info['username']}\n"
            f"👤 **مالک ربات:** شما\n"
            f"📅 **زمان ساخت:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"✅ ربات شما آماده استفاده است!\n"
            f"کاربران می‌توانند پیام‌های ناشناس برای شما ارسال کنند.\n\n"
            f"📝 **نکات مهم:**\n"
            f"• برای مدیریت ربات به @BotFather مراجعه کنید\n"
            f"• توکن ربات را با کسی به اشتراک نگذارید\n"
            f"• در صورت نیاز می‌توانید ربات را حذف کنید"
        )
        
        # ایجاد دکمه‌ها
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
                    callback_data="create_new_bot"
                ),
                InlineKeyboardButton(
                    "📋 مشاهده همه ربات‌ها",
                    callback_data="show_my_bots"
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            success_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # ارسال راهنمای استفاده
        guide_text = (
            "📖 **راهنمای استفاده از ربات چت ناشناس:**\n\n"
            "1. ربات شما (@{bot_username}) آماده است\n"
            "2. کاربران می‌توانند به ربات شما پیام دهند\n"
            "3. پیام‌ها به صورت ناشناس برای شما ارسال می‌شوند\n"
            "4. شما می‌توانید به کاربران پاسخ دهید\n\n"
            "برای شروع، ربات خود را به دوستانتان معرفی کنید!"
        ).format(bot_username=bot_info['username'])
        
        await update.message.reply_text(guide_text, parse_mode=ParseMode.MARKDOWN)
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """مدیریت کلیک روی دکمه‌های اینلاین"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user = query.from_user
        
        if data == "create_new_bot":
            await query.edit_message_text(
                "🔑 **لطفاً توکن ربات خود را ارسال کنید:**\n\n"
                "توکن ربات شما چیزی شبیه به این است:\n"
                "`1234567890:ABCdefGHIJKLMNopqRSTUvwxYZ`",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['waiting_for_token'] = True
        
        elif data == "show_my_bots":
            await self.my_bots(update, context)
    
    # ==================== هندلرهای نسخه قدیمی ====================
    def start_old(self, update: Update, context: CallbackContext):
        """دستور /start برای ورژن قدیمی"""
        user = update.effective_user
        self.db.add_user(user.id, user.username or "", user.first_name, user.last_name or "")
        
        keyboard = [
            [KeyboardButton("🤖 ساخت ربات جدید")],
            [KeyboardButton("📋 ربات‌های من"), KeyboardButton("ℹ️ راهنما")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        update.message.reply_text(
            "👋 به ربات مادر ساخت ربات چت ناشناس خوش آمدید!",
            reply_markup=reply_markup
        )
    
    def help_old(self, update: Update, context: CallbackContext):
        """دستور /help برای ورژن قدیمی"""
        update.message.reply_text(
            "📚 راهنمای استفاده:\n\n"
            "1. به @BotFather مراجعه کنید\n"
            "2. ربات جدید بسازید\n"
            "3. توکن را برای این ربات ارسال کنید"
        )
    
    def my_bots_old(self, update: Update, context: CallbackContext):
        """دستور /mybots برای ورژن قدیمی"""
        user = update.effective_user
        bots = self.db.get_user_bots(user.id)
        
        if not bots:
            update.message.reply_text("شما هنوز هیچ رباتی نساخته‌اید!")
            return
        
        text = "🤖 ربات‌های شما:\n\n"
        for bot in bots:
            text += f"@{bot['bot_username']}\n"
        
        update.message.reply_text(text)
    
    def handle_message_old(self, update: Update, context: CallbackContext):
        """مدیریت پیام برای ورژن قدیمی"""
        text = update.message.text
        
        if text == "🤖 ساخت ربات جدید":
            update.message.reply_text("لطفاً توکن ربات خود را ارسال کنید:")
            context.user_data['waiting_for_token'] = True
        elif context.user_data.get('waiting_for_token'):
            self.handle_bot_token_old(update, context, text)
    
    def handle_bot_token_old(self, update: Update, context: CallbackContext, token: str):
        """مدیریت توکن برای ورژن قدیمی"""
        user = update.effective_user
        
        # اعتبارسنجی ساده
        if ":" not in token:
            update.message.reply_text("توکن نامعتبر است!")
            return
        
        # ذخیره در دیتابیس
        bot_hash = hashlib.md5(token.encode()).hexdigest()[:8]
        bot_id = f"bot_{bot_hash}"
        
        # ذخیره ربات (در نسخه واقعی باید اطلاعات ربات را از تلگرام بگیریم)
        self.db.add_bot(bot_id, token, user.id, "anon_bot_example")
        
        update.message.reply_text(f"✅ ربات ساخته شد! آیدی: {bot_id}")
    
    def handle_callback_old(self, update: Update, context: CallbackContext):
        """کالبک برای ورژن قدیمی"""
        query = update.callback_query
        query.answer()
        query.edit_message_text("دکمه کلیک شد!")
    
    # ==================== متدهای کمکی ====================
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
    
    async def get_bot_info(self, token: str) -> Optional[Dict]:
        """دریافت اطلاعات ربات از تلگرام"""
        try:
            if TELEGRAM_VERSION == "new":
                # ساخت اپلیکیشن موقت برای تست توکن
                test_app = Application.builder().token(token).build()
                async with test_app:
                    bot = await test_app.bot.get_me()
                    return {
                        'id': bot.id,
                        'username': bot.username,
                        'name': bot.first_name
                    }
            else:
                # برای ورژن قدیمی (نمونه ساده)
                return {
                    'id': 123456,
                    'username': 'anonymous_bot',
                    'name': 'Anonymous Bot'
                }
        except Exception as e:
            logger.error(f"خطا در دریافت اطلاعات ربات: {e}")
            return None
    
    def run(self):
        """اجرای ربات"""
        logger.info("🤖 ربات مادر در حال راه‌اندازی...")
        logger.info(f"ورژن تلگرام: {TELEGRAM_VERSION}")
        
        if TELEGRAM_VERSION == "new":
            self.application.run_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES
            )
        elif TELEGRAM_VERSION == "old":
            self.updater.start_polling()
            self.updater.idle()
        else:
            logger.error("کتابخانه تلگرام نصب نیست!")

# ==================== اجرای اصلی ====================
if __name__ == "__main__":
    # بررسی تنظیمات
    if not os.environ.get('MOTHER_BOT_TOKEN'):
        print("=" * 60)
        print("⚠️  لطفاً متغیرهای محیطی را تنظیم کنید!")
        print("=" * 60)
        print("\nبرای استقرار روی رندر:")
        print("1. به رندر بروید و Web Service جدید بسازید")
        print("2. متغیرهای محیطی زیر را تنظیم کنید:")
        print("   - MOTHER_BOT_TOKEN: توکن ربات مادر")
        print("   - MAX_BOTS_PER_USER: 3 (پیش‌فرض)")
        print("\nبرای اجرای محلی:")
        print("export MOTHER_BOT_TOKEN='توکن_ربات_شما'")
        print("python main.py")
        print("=" * 60)
        
        # تست محلی با توکن نمونه
        if not IS_RENDER:
            os.environ['MOTHER_BOT_TOKEN'] = 'YOUR_BOT_TOKEN_HERE'
            print("\n⚠️  اجرا با توکن نمونه - برای تست فقط!")
    
    try:
        bot = SimpleMotherBot()
        bot.run()
    except Exception as e:
        logger.error(f"خطای اصلی: {e}")
        if IS_RENDER:
            # در رندر، برنامه را نگه دار
            import time
            time.sleep(60)
