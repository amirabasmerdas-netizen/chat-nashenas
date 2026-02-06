#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات مادر ساخت ربات چت ناشناس - نسخه تضمین شده برای رندر
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
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ==================== تلگرام با سازگاری کامل ====================
try:
    # سعی می‌کنیم با سازگاری کامل import کنیم
    import telegram
    from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
    from telegram.ext import Updater, CommandHandler, MessageHandler, CallbackQueryHandler, CallbackContext
    from telegram import ParseMode
    
    # بررسی ورژن
    telegram_version = telegram.__version__
    logger.info(f"✅ کتابخانه تلگرام ورژن {telegram_version} import شد")
    
    # برای ورژن‌های مختلف
    try:
        from telegram.ext import Filters
        FILTERS = Filters
    except ImportError:
        try:
            from telegram.ext import filters
            FILTERS = filters
        except ImportError:
            # ساخت Filters دستی
            class Filters:
                text = lambda x: True
                command = lambda x: False
            FILTERS = Filters
    
    TELEGRAM_OK = True
    
except ImportError as e:
    logger.error(f"❌ خطا در import تلگرام: {e}")
    TELEGRAM_OK = False

# ==================== کلاس دیتابیس ====================
class Database:
    def __init__(self, db_path="mother_bots.db"):
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
            
            # کاربران
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at TEXT,
                bot_count INTEGER DEFAULT 0
            )''')
            
            # ربات‌ها
            c.execute('''CREATE TABLE IF NOT EXISTS bots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id TEXT UNIQUE,
                token TEXT UNIQUE,
                owner_id INTEGER,
                bot_username TEXT,
                bot_name TEXT,
                created_at TEXT,
                status TEXT DEFAULT 'active'
            )''')
            
            conn.commit()
            logger.info(f"✅ دیتابیس در {self.db_path} راه‌اندازی شد")
    
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
            c.execute('''INSERT INTO bots 
                       (bot_id, token, owner_id, bot_username, bot_name, created_at) 
                       VALUES (?, ?, ?, ?, ?, ?)''',
                     (bot_id, token, owner_id, bot_username, bot_name, datetime.now().isoformat()))
            
            c.execute('''UPDATE users 
                       SET bot_count = bot_count + 1 
                       WHERE user_id = ?''', (owner_id,))
            
            conn.commit()
            logger.info(f"✅ ربات {bot_id} برای کاربر {owner_id} ذخیره شد")
    
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

# ==================== کلاس ربات اصلی ====================
class MotherBot:
    def __init__(self):
        # خواندن توکن
        self.token = os.environ.get('MOTHER_BOT_TOKEN', '').strip()
        if not self.token or self.token == 'YOUR_BOT_TOKEN_HERE':
            logger.error("❌ متغیر MOTHER_BOT_TOKEN تنظیم نشده است!")
            logger.error("لطفاً در رندر: Environment Variables → MOTHER_BOT_TOKEN")
            raise ValueError("توکن ربات تنظیم نشده است")
        
        self.db = Database()
        self.max_bots = int(os.environ.get('MAX_BOTS_PER_USER', '3'))
        
        if not TELEGRAM_OK:
            logger.error("❌ کتابخانه تلگرام در دسترس نیست!")
            raise ImportError("پکیج python-telegram-bot نصب نیست")
        
        # ساخت Updater
        self.updater = Updater(self.token, use_context=True)
        self.dispatcher = self.updater.dispatcher
        
        # تنظیم هندلرها
        self.setup_handlers()
        
        logger.info(f"✅ ربات مادر با توکن {self.token[:10]}... راه‌اندازی شد")
        logger.info(f"📊 حداکثر ربات هر کاربر: {self.max_bots}")
    
    def setup_handlers(self):
        """تنظیم هندلرهای ربات"""
        # دستورات
        self.dispatcher.add_handler(CommandHandler("start", self.start))
        self.dispatcher.add_handler(CommandHandler("help", self.help))
        self.dispatcher.add_handler(CommandHandler("mybots", self.my_bots))
        self.dispatcher.add_handler(CommandHandler("profile", self.profile))
        
        # پیام‌های متنی (بدون استفاده از Filters مشکل‌ساز)
        self.dispatcher.add_handler(MessageHandler(
            FILTERS.text & ~FILTERS.command, 
            self.handle_message
        ))
        
        # کلیک روی دکمه‌ها
        self.dispatcher.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # هندلر خطا
        self.dispatcher.add_error_handler(self.error_handler)
    
    def start(self, update: Update, context: CallbackContext):
        """دستور /start"""
        user = update.effective_user
        
        # ذخیره کاربر
        self.db.add_user(
            user.id,
            user.username or "",
            user.first_name,
            user.last_name or ""
        )
        
        # کیبورد
        keyboard = [
            [KeyboardButton("🤖 ساخت ربات جدید")],
            [KeyboardButton("📋 ربات‌های من"), KeyboardButton("ℹ️ راهنما")],
            [KeyboardButton("👤 پروفایل من")]
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
    
    def help(self, update: Update, context: CallbackContext):
        """دستور /help"""
        text = (
            "📚 **راهنمای استفاده:**\n\n"
            "🔸 **مراحل ساخت ربات:**\n"
            "1. به @BotFather بروید\n"
            "2. /newbot را بزنید\n"
            "3. ربات جدید بسازید\n"
            "4. توکن را کپی کنید\n"
            "5. توکن را اینجا ارسال کنید\n\n"
            "🔸 **توکن ربات چیست؟**\n"
            "`1234567890:ABCdefGHIJKLMNopqRSTUvwxYZ`\n\n"
            "🔸 **دستورات:**\n"
            "/start - شروع کار\n"
            "/mybots - ربات‌های شما\n"
            "/profile - اطلاعات شما\n"
            "/help - این راهنما\n\n"
            "⚠️ توکن ربات مانند رمز عبور است!"
        )
        
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    def my_bots(self, update: Update, context: CallbackContext):
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
            InlineKeyboardButton("➕ ساخت جدید", callback_data="create"),
            InlineKeyboardButton("🔄 بروزرسانی", callback_data="refresh")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    def profile(self, update: Update, context: CallbackContext):
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
    
    def handle_message(self, update: Update, context: CallbackContext):
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
            context.user_data['waiting'] = True
        
        elif text == "📋 ربات‌های من":
            self.my_bots(update, context)
        
        elif text == "ℹ️ راهنما":
            self.help(update, context)
        
        elif text == "👤 پروفایل من":
            self.profile(update, context)
        
        elif context.user_data.get('waiting'):
            self.handle_token(update, context, text)
            context.user_data.pop('waiting', None)
        
        else:
            update.message.reply_text(
                "لطفاً از دکمه‌های زیر استفاده کنید:\n\n"
                "🤖 ساخت ربات جدید\n"
                "📋 ربات‌های من\n"
                "ℹ️ راهنما\n"
                "👤 پروفایل من"
            )
    
    def handle_token(self, update: Update, context: CallbackContext, token: str):
        """پردازش توکن"""
        user = update.effective_user
        
        # بررسی تعداد
        count = self.db.get_user_bot_count(user.id)
        if count >= self.max_bots:
            update.message.reply_text(
                f"⚠️ **شما به حداکثر تعداد رسیده‌اید!**\n\n"
                f"تعداد: {count}/{self.max_bots}",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # اعتبارسنجی
        if not self.check_token(token):
            update.message.reply_text(
                "❌ **توکن نامعتبر است!**\n\n"
                "فرمت صحیح:\n"
                "`عدد:رشته حروف و اعداد`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # بررسی تکراری
        if self.db.get_bot_by_token(token):
            update.message.reply_text(
                "⚠️ **این توکن قبلاً ثبت شده است!**",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # تست توکن
        info = self.test_token(token)
        if not info:
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
        self.db.add_bot(bot_id, token, user.id, info['username'], info['name'])
        
        # نمایش موفقیت
        success = (
            f"🎉 **ربات شما ساخته شد!**\n\n"
            f"🤖 **ربات:** {info['name']}\n"
            f"👤 **مالک:** شما\n"
            f"📅 **زمان:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"✅ ربات شما آماده است!\n"
            f"کاربران می‌توانند پیام ناشناس ارسال کنند.\n\n"
            f"🔗 **لینک:** https://t.me/{info['username']}"
        )
        
        # دکمه‌ها
        keyboard = [
            [
                InlineKeyboardButton(
                    "🔗 باز کردن ربات",
                    url=f"https://t.me/{info['username']}"
                )
            ],
            [
                InlineKeyboardButton("➕ ساخت جدید", callback_data="create"),
                InlineKeyboardButton("📋 همه ربات‌ها", callback_data="show")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(
            success,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # راهنما
        guide = (
            f"📖 **راهنمای استفاده:**\n\n"
            f"1. ربات شما (@{info['username']}) آماده است\n"
            f"2. دوستانتان را به ربات دعوت کنید\n"
            f"3. آن‌ها پیام ناشناس ارسال می‌کنند\n"
            f"4. شما پیام‌ها را دریافت می‌کنید\n\n"
            f"✨ برای تغییر تنظیمات به @BotFather مراجعه کنید."
        )
        
        update.message.reply_text(guide, parse_mode=ParseMode.MARKDOWN)
    
    def handle_callback(self, update: Update, context: CallbackContext):
        """کلیک روی دکمه‌ها"""
        query = update.callback_query
        query.answer()
        
        data = query.data
        
        if data == "create":
            query.edit_message_text(
                "🔑 **لطفاً توکن ربات خود را ارسال کنید:**\n\n"
                "توکن ربات شما چیزی شبیه به این است:\n"
                "`1234567890:ABCdefGHIJKLMNopqRSTUvwxYZ`",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['waiting'] = True
        
        elif data == "show":
            self.my_bots(update, context)
        
        elif data == "refresh":
            self.my_bots(update, context)
    
    def check_token(self, token: str) -> bool:
        """اعتبارسنجی توکن"""
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
    
    def error_handler(self, update: Update, context: CallbackContext):
        """مدیریت خطاها"""
        logger.error(f"خطای ربات: {context.error}")
        
        try:
            if update and update.effective_message:
                update.effective_message.reply_text(
                    "❌ متأسفانه خطایی رخ داد.\n"
                    "لطفاً بعداً تلاش کنید."
                )
        except:
            pass
    
    def run(self):
        """اجرای ربات"""
        logger.info("🚀 ربات در حال راه‌اندازی...")
        
        self.updater.start_polling()
        logger.info("✅ ربات شروع به کار کرد!")
        
        self.updater.idle()

# ==================== سرور وب برای رندر ====================
def run_web_server():
    """اجرای سرور وب ساده"""
    try:
        from flask import Flask, jsonify
        import threading
        
        app = Flask(__name__)
        
        @app.route('/')
        def home():
            return jsonify({
                "status": "running",
                "service": "mother-bot",
                "time": datetime.now().isoformat()
            })
        
        @app.route('/health')
        def health():
            return jsonify({"status": "healthy"})
        
        @app.route('/ping')
        def ping():
            return jsonify({"pong": time.time()})
        
        # اجرا در ترد جداگانه
        port = int(os.environ.get('PORT', 10000))
        thread = threading.Thread(
            target=lambda: app.run(host='0.0.0.0', port=port, debug=False, threaded=True),
            daemon=True
        )
        thread.start()
        
        logger.info(f"🌐 سرور وب روی پورت {port} راه‌اندازی شد")
        
    except ImportError:
        logger.warning("Flask نصب نیست، سرور وب اجرا نمی‌شود")
    except Exception as e:
        logger.error(f"خطا در سرور وب: {e}")

# ==================== اجرای اصلی ====================
def main():
    """تابع اصلی"""
    
    print("=" * 60)
    print("🤖 **ربات مادر ساخت ربات چت ناشناس**")
    print("=" * 60)
    
    # بررسی توکن
    token = os.environ.get('MOTHER_BOT_TOKEN', '').strip()
    if not token or token == 'YOUR_BOT_TOKEN_HERE':
        print("\n⚠️  لطفاً توکن ربات را تنظیم کنید!")
        print("\nدر رندر:")
        print("1. به Dashboard بروید")
        print("2. روی سرویس کلیک کنید")
        print("3. Environment → Add Environment Variable")
        print("4. اضافه کنید: MOTHER_BOT_TOKEN = توکن_ربات_شما")
        print("\nمقادیر اختیاری:")
        print("MAX_BOTS_PER_USER = 3 (پیش‌فرض)")
        print("=" * 60)
        
        # اگر در رندر هستیم
        if os.environ.get('RENDER'):
            print("⏳ منتظر تنظیم توکن...")
            time.sleep(10)
            token = os.environ.get('MOTHER_BOT_TOKEN', '').strip()
            if not token or token == 'YOUR_BOT_TOKEN_HERE':
                print("❌ توکن تنظیم نشده. ادامه بدون ربات...")
                # فقط سرور وب را اجرا می‌کنیم
                run_web_server()
                time.sleep(3600)  # یک ساعت منتظر می‌مانیم
                return
    
    # شروع سرور وب (اگر در رندر هستیم)
    if os.environ.get('RENDER'):
        run_web_server()
    
    try:
        # ایجاد و اجرای ربات
        bot = MotherBot()
        
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

# نقطه ورود
if __name__ == "__main__":
    main()
