#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات مادر ساخت ربات‌های چت ناشناس - نسخه متصل به رندر (Render.com)
با پشتیبانی از Webhook و کاملاً آماده برای استقرار روی Render
"""

import os
import logging
import json
import asyncio
import aiohttp
import sqlite3
import threading
import queue
import signal
import sys
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
from dataclasses import dataclass, asdict
from contextlib import contextmanager
import hashlib

# ==================== تنظیمات محیطی رندر ====================
# خواندن متغیرهای محیطی از Render
RENDER = os.environ.get('RENDER', 'false').lower() == 'true'
IS_PRODUCTION = os.environ.get('ENVIRONMENT', 'development') == 'production'
PORT = int(os.environ.get('PORT', 8443))  # پورت پیش‌فرض برای رندر
WEBHOOK_URL = os.environ.get('RENDER_EXTERNAL_URL', '')  # آدرس وب‌سایت روی رندر

# ==================== تنظیمات تلگرام ====================
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode, ChatAction
from telegram.error import TelegramError

# ==================== تنظیمات لاگ برای رندر ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('mother_bot_render.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)  # خروجی به stdout برای رندر
    ]
)
logger = logging.getLogger(__name__)

# ==================== انوم‌ها و کلاس‌های پایه ====================
class BotStatus(Enum):
    """وضعیت ربات"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    PENDING = "pending"
    ERROR = "error"

class UserRole(Enum):
    """نقش کاربر"""
    OWNER = "owner"
    ADMIN = "admin"
    USER = "user"
    BANNED = "banned"

class MessageType(Enum):
    """انواع پیام"""
    TEXT = "text"
    PHOTO = "photo"
    DOCUMENT = "document"
    ANONYMOUS = "anonymous"
    SYSTEM = "system"

# ==================== کلاس مدیریت دیتابیس برای رندر ====================
class RenderDatabaseManager:
    """مدیریت دیتابیس SQLite برای رندر"""
    
    def __init__(self, db_path: str = "render_bot_data.db"):
        # در رندر از مسیر پایدار استفاده می‌کنیم
        if RENDER:
            self.db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), db_path)
        else:
            self.db_path = db_path
        
        self._init_database()
        self._setup_backup_scheduler()
    
    def _init_database(self):
        """ایجاد جداول دیتابیس"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # جدول ربات‌ها
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bots (
                    token TEXT PRIMARY KEY,
                    owner_id INTEGER NOT NULL,
                    bot_id TEXT UNIQUE NOT NULL,
                    bot_username TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    webhook_url TEXT,
                    total_messages INTEGER DEFAULT 0,
                    total_users INTEGER DEFAULT 0,
                    last_activity TEXT,
                    settings TEXT NOT NULL,
                    render_service_id TEXT,
                    render_service_url TEXT
                )
            ''')
            
            # جدول کاربران
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT NOT NULL,
                    last_name TEXT,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    owned_bots TEXT,
                    subscription_end TEXT,
                    email TEXT,
                    phone TEXT
                )
            ''')
            
            # جدول پیام‌های ناشناس
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS anonymous_messages (
                    message_id TEXT PRIMARY KEY,
                    bot_id TEXT NOT NULL,
                    from_user_id INTEGER NOT NULL,
                    to_user_id INTEGER NOT NULL,
                    message_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    is_read INTEGER DEFAULT 0,
                    reply_to TEXT,
                    FOREIGN KEY (bot_id) REFERENCES bots (bot_id)
                )
            ''')
            
            # جدول آمار روزانه
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    messages_count INTEGER DEFAULT 0,
                    users_count INTEGER DEFAULT 0,
                    UNIQUE(bot_id, date),
                    FOREIGN KEY (bot_id) REFERENCES bots (bot_id)
                )
            ''')
            
            # جدول لاگ سیستم
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    source TEXT
                )
            ''')
            
            conn.commit()
        
        logger.info(f"دیتابیس در مسیر {self.db_path} راه‌اندازی شد.")
    
    def _setup_backup_scheduler(self):
        """تنظیم زمان‌بند پشتیبان‌گیری"""
        if RENDER:
            # در رندر هر 6 ساعت یکبار پشتیبان بگیر
            import schedule
            import time
            
            def backup_database():
                backup_file = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                try:
                    import shutil
                    shutil.copy2(self.db_path, backup_file)
                    logger.info(f"پشتیبان‌گیری انجام شد: {backup_file}")
                except Exception as e:
                    logger.error(f"خطا در پشتیبان‌گیری: {e}")
            
            schedule.every(6).hours.do(backup_database)
            
            def run_scheduler():
                while True:
                    schedule.run_pending()
                    time.sleep(60)
            
            scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
            scheduler_thread.start()
    
    @contextmanager
    def _get_connection(self):
        """کانتکست منیجر برای اتصال به دیتابیس"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        except Exception as e:
            logger.error(f"خطای دیتابیس: {e}")
            raise
        finally:
            conn.close()
    
    def log_system_event(self, level: str, message: str, source: str = "system"):
        """ثبت رویداد در سیستم"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO system_logs (level, message, timestamp, source)
                VALUES (?, ?, ?, ?)
            ''', (level, message, datetime.now().isoformat(), source))
            conn.commit()
    
    # === متدهای اصلی دیتابیس ===
    
    def save_bot(self, bot_data: dict):
        """ذخیره ربات جدید"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO bots 
                (token, owner_id, bot_id, bot_username, created_at, status, 
                 webhook_url, total_messages, total_users, last_activity, 
                 settings, render_service_id, render_service_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                bot_data['token'],
                bot_data['owner_id'],
                bot_data['bot_id'],
                bot_data['bot_username'],
                bot_data['created_at'],
                bot_data['status'],
                bot_data.get('webhook_url'),
                bot_data.get('total_messages', 0),
                bot_data.get('total_users', 0),
                bot_data.get('last_activity'),
                json.dumps(bot_data.get('settings', {})),
                bot_data.get('render_service_id'),
                bot_data.get('render_service_url')
            ))
            conn.commit()
    
    def get_bot(self, bot_id: str) -> Optional[Dict]:
        """دریافت تنظیمات ربات"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM bots WHERE bot_id = ?', (bot_id,))
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            return None
    
    def get_user_bots(self, user_id: int) -> List[Dict]:
        """دریافت ربات‌های یک کاربر"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM bots WHERE owner_id = ?', (user_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def update_bot_status(self, bot_id: str, status: str):
        """بروزرسانی وضعیت ربات"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE bots SET status = ?, last_activity = ? WHERE bot_id = ?
            ''', (status, datetime.now().isoformat(), bot_id))
            conn.commit()
    
    def get_active_bots(self) -> List[Dict]:
        """دریافت ربات‌های فعال"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM bots WHERE status = ?', (BotStatus.ACTIVE.value,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def get_system_stats(self) -> Dict:
        """دریافت آمار سیستم"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            stats = {}
            
            # تعداد کل ربات‌ها
            cursor.execute('SELECT COUNT(*) as count FROM bots')
            stats['total_bots'] = cursor.fetchone()['count']
            
            # ربات‌های فعال
            cursor.execute('SELECT COUNT(*) as count FROM bots WHERE status = ?', (BotStatus.ACTIVE.value,))
            stats['active_bots'] = cursor.fetchone()['count']
            
            # تعداد کاربران
            cursor.execute('SELECT COUNT(*) as count FROM users')
            stats['total_users'] = cursor.fetchone()['count']
            
            # تعداد پیام‌ها
            cursor.execute('SELECT SUM(total_messages) as total FROM bots')
            stats['total_messages'] = cursor.fetchone()['total'] or 0
            
            return stats

# ==================== کلاس رندر برای رندر ====================
class RenderMessageRenderer:
    """
    کلاس رندر مخصوص رندر - تمام متغیرها قابل تنظیم از طریق محیط
    """
    
    def __init__(self, db_manager: RenderDatabaseManager):
        self.db = db_manager
        
        # خواندن تنظیمات از متغیرهای محیطی
        self.MOTHER_CONFIG = {
            "token": os.environ.get('MOTHER_BOT_TOKEN', 'YOUR_MOTHER_BOT_TOKEN_HERE'),
            "admin_ids": self._parse_admin_ids(os.environ.get('ADMIN_IDS', '123456789')),
            "max_bots_per_user": int(os.environ.get('MAX_BOTS_PER_USER', '3')),
            "bot_name_prefix": os.environ.get('BOT_NAME_PREFIX', 'AnonymousBot_'),
            "webhook_url": os.environ.get('WEBHOOK_BASE_URL', ''),
            "subscription_days": int(os.environ.get('SUBSCRIPTION_DAYS', '30')),
            "rate_limit": int(os.environ.get('RATE_LIMIT', '3')),
            "enable_webhook": os.environ.get('ENABLE_WEBHOOK', 'true').lower() == 'true',
        }
        
        # متغیرهای متن پیام‌ها
        self.MESSAGES = {
            "welcome": self._get_message("WELCOME_MESSAGE", 
                "👑 **به ربات مادر ساخت ربات چت ناشناس خوش آمدید!**\n\n"
                "من می‌توانم برای شما ربات چت ناشناس شخصی‌سازی شده بسازم.\n"
                "کافیست توکن رباتی که از @BotFather ساخته‌اید را برای من بفرستید."),
            
            "bot_created": self._get_message("BOT_CREATED_MESSAGE",
                "🎉 **ربات چت ناشناس شما ساخته شد!**\n\n"
                "🤖 **ربات:** @{bot_username}\n"
                "👤 **مالک:** شما\n"
                "📅 **ساخته شده در:** {created_at}\n\n"
                "✅ ربات شما آماده استفاده است!\n"
                "کاربران می‌توانند پیام‌های ناشناس برای شما ارسال کنند."),
            
            "send_token": self._get_message("SEND_TOKEN_MESSAGE",
                "🔑 **لطفاً توکن ربات خود را ارسال کنید:**\n\n"
                "توکن ربات شما چیزی شبیه به این است:\n"
                "`1234567890:ABCdefGHIJKLMNopqRSTUvwxYZ`\n\n"
                "⚠️ **توجه:** توکن ربات مانند رمز عبور است، آن را با کسی به اشتراک نگذارید!"),
        }
        
        # فرمت‌ها
        self.FORMATS = {
            "datetime": os.environ.get('DATETIME_FORMAT', '%Y-%m-%d %H:%M:%S'),
            "date": os.environ.get('DATE_FORMAT', '%Y-%m-%d'),
        }
    
    def _parse_admin_ids(self, ids_str: str) -> List[int]:
        """تبدیل رشته آیدی‌ها به لیست"""
        try:
            return [int(id.strip()) for id in ids_str.split(',')]
        except:
            return [123456789]  # مقدار پیش‌فرض
    
    def _get_message(self, env_var: str, default: str) -> str:
        """خواندن پیام از متغیر محیطی"""
        return os.environ.get(f'MESSAGE_{env_var}', default)
    
    def render_welcome(self, user_id: int) -> Tuple[str, ReplyKeyboardMarkup]:
        """رندر صفحه خوشامدگویی"""
        welcome_text = self.MESSAGES["welcome"]
        
        # ساخت کیبورد
        buttons = [
            [KeyboardButton("🤖 ساخت ربات جدید")],
            [KeyboardButton("📋 ربات‌های من"), KeyboardButton("📊 آمار من")],
            [KeyboardButton("ℹ️ راهنمای استفاده")]
        ]
        
        # بررسی ادمین بودن
        if user_id in self.MOTHER_CONFIG["admin_ids"]:
            buttons.append([KeyboardButton("👑 پنل مدیریت")])
        
        reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        
        return welcome_text, reply_markup
    
    def render_bot_created(self, bot_username: str, owner_name: str) -> Tuple[str, InlineKeyboardMarkup]:
        """رندر تأیید ساخت ربات"""
        created_at = datetime.now().strftime(self.FORMATS["datetime"])
        
        bot_info = self.MESSAGES["bot_created"].format(
            bot_username=bot_username,
            created_at=created_at
        )
        
        # ساخت اینلاین کیبورد
        keyboard = [
            [
                InlineKeyboardButton(
                    "🔗 لینک ربات",
                    url=f"https://t.me/{bot_username}"
                )
            ],
            [
                InlineKeyboardButton(
                    "⚙️ مدیریت ربات",
                    callback_data=f"manage_{bot_username}"
                ),
                InlineKeyboardButton(
                    "📊 آمار ربات",
                    callback_data=f"stats_{bot_username}"
                )
            ]
        ]
        
        inline_markup = InlineKeyboardMarkup(keyboard)
        
        return bot_info, inline_markup

# ==================== کلاس مدیریت رندر API ====================
class RenderAPIManager:
    """مدیریت API رندر برای ساخت سرویس‌های جدید"""
    
    def __init__(self):
        self.api_key = os.environ.get('RENDER_API_KEY', '')
        self.base_url = "https://api.render.com/v1"
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
    
    async def create_bot_service(self, bot_token: str, bot_username: str) -> Optional[Dict]:
        """ایجاد سرویس جدید برای ربات روی رندر"""
        if not self.api_key:
            logger.warning("کلید API رندر تنظیم نشده است.")
            return None
        
        try:
            service_name = f"anon-bot-{bot_username.lower()}"
            webhook_url = os.environ.get('WEBHOOK_BASE_URL', '')
            
            if not webhook_url:
                logger.error("آدرس وب‌هوک تنظیم نشده است.")
                return None
            
            payload = {
                "name": service_name,
                "type": "web_service",
                "runtime": "python",
                "repo": "https://github.com/your-repo/anon-bot-template",
                "branch": "main",
                "rootDir": ".",
                "buildCommand": "pip install -r requirements.txt",
                "startCommand": f"python bot_runner.py --token {bot_token}",
                "plan": "starter",
                "numInstances": 1,
                "envVars": [
                    {
                        "key": "BOT_TOKEN",
                        "value": bot_token
                    },
                    {
                        "key": "WEBHOOK_URL",
                        "value": f"{webhook_url}/{bot_token}"
                    },
                    {
                        "key": "PORT",
                        "value": "10000"
                    }
                ]
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/services",
                    headers=self.headers,
                    json=payload
                ) as response:
                    if response.status == 201:
                        data = await response.json()
                        logger.info(f"سرویس برای ربات @{bot_username} ساخته شد.")
                        return data
                    else:
                        error_text = await response.text()
                        logger.error(f"خطا در ساخت سرویس: {error_text}")
                        return None
        
        except Exception as e:
            logger.error(f"خطا در تماس با API رندر: {e}")
            return None

# ==================== کلاس ربات مادر برای رندر ====================
class RenderMotherBot:
    """ربات مادر اصلی برای استقرار روی رندر"""
    
    def __init__(self):
        self.db = RenderDatabaseManager()
        self.renderer = RenderMessageRenderer(self.db)
        self.render_api = RenderAPIManager()
        
        # اطمینان از وجود توکن
        self.token = self.renderer.MOTHER_CONFIG["token"]
        if self.token == 'YOUR_MOTHER_BOT_TOKEN_HERE':
            logger.critical("لطفاً توکن ربات مادر را تنظیم کنید!")
            logger.critical("متغیر محیطی MOTHER_BOT_TOKEN را تنظیم کنید.")
            sys.exit(1)
        
        # ساخت اپلیکیشن تلگرام
        self.application = Application.builder().token(self.token).build()
        
        # تنظیم هندلرها
        self.setup_handlers()
        
        # صف برای مدیریت ربات‌های فرزند
        self.bot_queue = queue.Queue()
        self.child_bots = {}
        self.is_running = False
        
        # شروع مدیریت‌کننده ربات‌ها
        self.start_bot_manager()
        
        # ثبت هندلر برای خاتمه
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)
    
    def start_bot_manager(self):
        """شروع مدیر ربات‌های فرزند"""
        def manager_worker():
            self.is_running = True
            while self.is_running:
                try:
                    task = self.bot_queue.get(timeout=5)
                    if task:
                        task_type, data = task
                        
                        if task_type == "start_bot":
                            asyncio.run(self.start_child_bot(data))
                        
                        elif task_type == "stop_bot":
                            asyncio.run(self.stop_child_bot(data))
                
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"خطا در مدیر ربات‌ها: {e}")
        
        manager_thread = threading.Thread(target=manager_worker, daemon=True)
        manager_thread.start()
        logger.info("مدیر ربات‌های فرزند راه‌اندازی شد.")
    
    async def start_child_bot(self, bot_data: Dict):
        """راه‌اندازی ربات فرزند"""
        try:
            bot_id = bot_data['bot_id']
            token = bot_data['token']
            
            logger.info(f"در حال راه‌اندازی ربات فرزند: {bot_id}")
            
            # بروزرسانی وضعیت ربات
            self.db.update_bot_status(bot_id, BotStatus.ACTIVE.value)
            self.db.log_system_event("INFO", f"ربات {bot_id} راه‌اندازی شد", "bot_manager")
            
            # اگر API رندر فعال است، سرویس بساز
            if self.render_api.api_key and bot_data.get('render_service_id') is None:
                service_info = await self.render_api.create_bot_service(token, bot_data['bot_username'])
                if service_info:
                    # ذخیره اطلاعات سرویس
                    with self.db._get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute('''
                            UPDATE bots 
                            SET render_service_id = ?, render_service_url = ?
                            WHERE bot_id = ?
                        ''', (service_info.get('id'), service_info.get('serviceUrl'), bot_id))
                        conn.commit()
            
            logger.info(f"ربات فرزند {bot_id} با موفقیت راه‌اندازی شد.")
            
        except Exception as e:
            logger.error(f"خطا در راه‌اندازی ربات فرزند: {e}")
            self.db.update_bot_status(bot_data['bot_id'], BotStatus.ERROR.value)
            self.db.log_system_event("ERROR", f"خطا در راه‌اندازی ربات: {str(e)}", "bot_manager")
    
    async def stop_child_bot(self, bot_id: str):
        """توقف ربات فرزند"""
        try:
            logger.info(f"در حال توقف ربات فرزند: {bot_id}")
            self.db.update_bot_status(bot_id, BotStatus.INACTIVE.value)
            self.db.log_system_event("INFO", f"ربات {bot_id} متوقف شد", "bot_manager")
            
            # TODO: توقف سرویس روی رندر (اگر نیاز باشد)
            
            logger.info(f"ربات فرزند {bot_id} با موفقیت متوقف شد.")
            
        except Exception as e:
            logger.error(f"خطا در توقف ربات فرزند: {e}")
            self.db.log_system_event("ERROR", f"خطا در توقف ربات: {str(e)}", "bot_manager")
    
    async def validate_bot_token(self, token: str) -> Optional[Dict]:
        """اعتبارسنجی توکن ربات"""
        try:
            # تست ساده توکن
            parts = token.split(':')
            if len(parts) != 2 or not parts[0].isdigit():
                return None
            
            # دریافت اطلاعات ربات از تلگرام
            test_app = Application.builder().token(token).build()
            
            async with test_app:
                bot = await test_app.bot.get_me()
                
                return {
                    "is_valid": True,
                    "bot_id": str(bot.id),
                    "bot_username": bot.username,
                    "bot_name": bot.first_name
                }
        
        except Exception as e:
            logger.error(f"خطا در اعتبارسنجی توکن: {e}")
            return None
    
    async def create_child_bot(self, token: str, owner_id: int) -> Optional[Dict]:
        """ایجاد ربات فرزند جدید"""
        try:
            # اعتبارسنجی توکن
            bot_info = await self.validate_bot_token(token)
            if not bot_info:
                return None
            
            # بررسی تعداد ربات‌های کاربر
            user_bots = self.db.get_user_bots(owner_id)
            max_bots = self.renderer.MOTHER_CONFIG["max_bots_per_user"]
            
            if len(user_bots) >= max_bots:
                return None
            
            # ایجاد آیدی منحصر به فرد
            bot_hash = hashlib.md5(f"{token}_{owner_id}_{datetime.now().timestamp()}".encode()).hexdigest()[:8]
            bot_id = f"{self.renderer.MOTHER_CONFIG['bot_name_prefix']}{bot_hash}"
            
            # تنظیمات ربات
            bot_data = {
                "token": token,
                "owner_id": owner_id,
                "bot_id": bot_id,
                "bot_username": bot_info["bot_username"],
                "created_at": datetime.now().isoformat(),
                "status": BotStatus.PENDING.value,
                "webhook_url": f"{self.renderer.MOTHER_CONFIG['webhook_url']}/{token}" if self.renderer.MOTHER_CONFIG['webhook_url'] else None,
                "total_messages": 0,
                "total_users": 0,
                "settings": json.dumps({
                    "welcome_message": "👋 به ربات چت ناشناس خوش آمدید!",
                    "auto_reply": False,
                    "max_message_length": 2000,
                    "allow_media": True,
                    "notify_owner": True
                })
            }
            
            # ذخیره در دیتابیس
            self.db.save_bot(bot_data)
            
            # افزودن به صف راه‌اندازی
            self.bot_queue.put(("start_bot", bot_data))
            
            # ثبت در سیستم
            self.db.log_system_event("INFO", 
                f"ربات جدید ساخته شد: {bot_id} برای کاربر {owner_id}", 
                "bot_creation")
            
            return bot_data
            
        except Exception as e:
            logger.error(f"خطا در ساخت ربات فرزند: {e}")
            self.db.log_system_event("ERROR", 
                f"خطا در ساخت ربات برای کاربر {owner_id}: {str(e)}", 
                "bot_creation")
            return None
    
    # ==================== هندلرهای تلگرام ====================
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """دستور /start"""
        user = update.effective_user
        
        # ذخیره/بروزرسانی کاربر
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, username, first_name, last_name, role, created_at, owned_bots)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                user.id,
                user.username or "",
                user.first_name,
                user.last_name or "",
                UserRole.USER.value,
                datetime.now().isoformat(),
                json.dumps([])
            ))
            conn.commit()
        
        # نمایش صفحه خوشامدگویی
        welcome_text, reply_markup = self.renderer.render_welcome(user.id)
        
        await update.message.reply_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """مدیریت پیام‌های متنی"""
        user = update.effective_user
        message_text = update.message.text
        
        # بررسی ادمین بودن
        is_admin = user.id in self.renderer.MOTHER_CONFIG["admin_ids"]
        
        if message_text == "🤖 ساخت ربات جدید":
            # درخواست توکن
            send_token_msg = self.renderer.MESSAGES["send_token"]
            await update.message.reply_text(
                send_token_msg,
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['waiting_for_token'] = True
        
        elif message_text == "📋 ربات‌های من":
            # نمایش ربات‌های کاربر
            bots = self.db.get_user_bots(user.id)
            
            if not bots:
                await update.message.reply_text(
                    "📭 شما هنوز هیچ رباتی نساخته‌اید!",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                response = "🤖 **ربات‌های شما:**\n\n"
                for bot in bots:
                    status_icon = "🟢" if bot['status'] == BotStatus.ACTIVE.value else "🔴"
                    response += f"{status_icon} @{bot['bot_username']}\n"
                    response += f"   📊 پیام‌ها: {bot['total_messages']}\n"
                    response += f"   👥 کاربران: {bot['total_users']}\n\n"
                
                await update.message.reply_text(
                    response,
                    parse_mode=ParseMode.MARKDOWN
                )
        
        elif message_text == "📊 آمار من":
            # نمایش آمار کاربر
            bots = self.db.get_user_bots(user.id)
            
            total_messages = sum(bot['total_messages'] for bot in bots)
            total_users = sum(bot['total_users'] for bot in bots)
            
            stats_text = f"📈 **آمار شما:**\n\n"
            stats_text += f"🤖 **تعداد ربات‌ها:** {len(bots)}\n"
            stats_text += f"📨 **کل پیام‌ها:** {total_messages}\n"
            stats_text += f"👥 **کل کاربران:** {total_users}\n"
            
            await update.message.reply_text(
                stats_text,
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif message_text == "👑 پنل مدیریت" and is_admin:
            # پنل مدیریت
            stats = self.db.get_system_stats()
            
            admin_text = f"👑 **پنل مدیریت سیستم**\n\n"
            admin_text += f"🤖 **کل ربات‌ها:** {stats['total_bots']}\n"
            admin_text += f"🟢 **ربات‌های فعال:** {stats['active_bots']}\n"
            admin_text += f"👥 **کل کاربران:** {stats['total_users']}\n"
            admin_text += f"📨 **کل پیام‌ها:** {stats['total_messages']}\n\n"
            admin_text += "👇 برای مدیریت بیشتر از دستورات زیر استفاده کنید:\n"
            admin_text += "/allbots - مشاهده همه ربات‌ها\n"
            admin_text += "/allusers - مشاهده همه کاربران\n"
            admin_text += "/systemlogs - مشاهده لاگ سیستم"
            
            await update.message.reply_text(
                admin_text,
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif context.user_data.get('waiting_for_token', False):
            # دریافت توکن ربات
            await self._handle_bot_token(update, context, message_text)
            context.user_data.pop('waiting_for_token', None)
        
        else:
            # نمایش راهنما
            help_text = "ℹ️ **راهنمای استفاده:**\n\n"
            help_text += "برای ساخت ربات چت ناشناس:\n"
            help_text += "1. روی 'ساخت ربات جدید' کلیک کنید\n"
            help_text += "2. توکن ربات خود را از @BotFather دریافت کنید\n"
            help_text += "3. توکن را برای این ربات ارسال کنید\n"
            help_text += "4. ربات شما ساخته و راه‌اندازی می‌شود!\n\n"
            help_text += "📌 توکن ربات چیزی شبیه به این است:\n"
            help_text += "`1234567890:ABCdefGHIJKLMNopqRSTUvwxYZ`"
            
            await update.message.reply_text(
                help_text,
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def _handle_bot_token(self, update: Update, context: ContextTypes.DEFAULT_TYPE, token: str):
        """مدیریت دریافت توکن ربات"""
        user = update.effective_user
        
        # نمایش پیام در حال پردازش
        processing_msg = await update.message.reply_text(
            "🔄 در حال پردازش توکن...\nلطفاً صبر کنید.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        try:
            # اعتبارسنجی توکن
            bot_info = await self.validate_bot_token(token)
            
            if not bot_info:
                await processing_msg.edit_text(
                    "❌ **توکن نامعتبر است!**\n\n"
                    "لطفاً مطمئن شوید توکن را به درستی کپی کرده‌اید.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            # ساخت ربات فرزند
            bot_data = await self.create_child_bot(token, user.id)
            
            if not bot_data:
                await processing_msg.edit_text(
                    "❌ **خطا در ساخت ربات!**\n\n"
                    "ممکن است به حداکثر تعداد ربات مجاز رسیده باشید.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            # نمایش موفقیت
            bot_created_msg, inline_markup = self.renderer.render_bot_created(
                bot_data['bot_username'],
                user.first_name
            )
            
            await processing_msg.edit_text(
                bot_created_msg,
                reply_markup=inline_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
            # لاگ موفقیت
            self.db.log_system_event("SUCCESS", 
                f"کاربر {user.id} ربات @{bot_data['bot_username']} را ساخت", 
                "user_action")
            
        except Exception as e:
            logger.error(f"خطا در ساخت ربات: {e}")
            await processing_msg.edit_text(
                "❌ **خطا در ساخت ربات!**\n\n"
                "لطفاً بعداً مجدداً تلاش کنید یا با پشتیبانی تماس بگیرید.",
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """مدیریت کلیک روی دکمه‌های اینلاین"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user = update.effective_user
        
        if data.startswith("manage_"):
            bot_username = data.replace("manage_", "")
            
            # یافتن ربات
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM bots WHERE bot_username = ?', (bot_username,))
                bot = cursor.fetchone()
                
                if bot:
                    bot = dict(bot)
                    
                    keyboard = [
                        [
                            InlineKeyboardButton(
                                "⏹️ توقف ربات",
                                callback_data=f"stop_{bot['bot_id']}"
                            ),
                            InlineKeyboardButton(
                                "▶️ راه‌اندازی مجدد",
                                callback_data=f"restart_{bot['bot_id']}"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "🗑️ حذف ربات",
                                callback_data=f"delete_{bot['bot_id']}"
                            ),
                            InlineKeyboardButton(
                                "📊 آمار دقیق",
                                callback_data=f"detailed_stats_{bot['bot_id']}"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "🔙 بازگشت",
                                callback_data="back_to_main"
                            )
                        ]
                    ]
                    
                    inline_markup = InlineKeyboardMarkup(keyboard)
                    
                    status_text = {
                        BotStatus.ACTIVE.value: "🟢 فعال",
                        BotStatus.INACTIVE.value: "🔴 غیرفعال",
                        BotStatus.PENDING.value: "🟡 در انتظار",
                        BotStatus.ERROR.value: "🔵 خطا"
                    }
                    
                    bot_info = f"⚙️ **مدیریت ربات:** @{bot['bot_username']}\n\n"
                    bot_info += f"🆔 **آیدی:** `{bot['bot_id']}`\n"
                    bot_info += f"📅 **ساخته شده:** {datetime.fromisoformat(bot['created_at']).strftime('%Y-%m-%d %H:%M')}\n"
                    bot_info += f"🔰 **وضعیت:** {status_text.get(bot['status'], 'نامشخص')}\n"
                    bot_info += f"📊 **آمار:** {bot['total_messages']} پیام, {bot['total_users']} کاربر\n\n"
                    bot_info += "👇 برای مدیریت ربات از دکمه‌های زیر استفاده کنید:"
                    
                    await query.edit_message_text(
                        bot_info,
                        reply_markup=inline_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
        
        elif data.startswith("stop_"):
            bot_id = data.replace("stop_", "")
            self.bot_queue.put(("stop_bot", bot_id))
            
            await query.edit_message_text(
                "⏹️ **ربات در حال توقف است...**\n\n"
                "لطفاً چند لحظه صبر کنید.",
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif data == "back_to_main":
            welcome_text, reply_markup = self.renderer.render_welcome(user.id)
            
            await query.edit_message_text(
                "به صفحه اصلی بازگشتید.",
                parse_mode=ParseMode.MARKDOWN
            )
            
            await context.bot.send_message(
                chat_id=user.id,
                text=welcome_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """مدیریت خطاها"""
        error_msg = str(context.error) if context.error else "خطای ناشناخته"
        logger.error(f"خطای تلگرام: {error_msg}")
        
        # ثبت در دیتابیس
        self.db.log_system_event("ERROR", f"خطای تلگرام: {error_msg}", "telegram_handler")
        
        try:
            if update and update.effective_message:
                await update.effective_message.reply_text(
                    "❌ متأسفانه خطایی رخ داد.\n"
                    "لطفاً بعداً مجدداً تلاش کنید."
                )
        except:
            pass
    
    def setup_handlers(self):
        """تنظیم هندلرهای تلگرام"""
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.start))
        self.application.add_handler(CommandHandler("stats", self.start))
        
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, 
            self.handle_message
        ))
        
        self.application.add_handler(CallbackQueryHandler(
            self.handle_callback_query
        ))
        
        self.application.add_error_handler(self.error_handler)
    
    async def setup_webhook(self):
        """تنظیم وب‌هوک برای رندر"""
        if not self.renderer.MOTHER_CONFIG["enable_webhook"]:
            logger.info("وب‌هوک غیرفعال است. استفاده از پولینگ.")
            return
        
        webhook_url = self.renderer.MOTHER_CONFIG["webhook_url"]
        if not webhook_url:
            logger.warning("آدرس وب‌هوک تنظیم نشده است. استفاده از پولینگ.")
            return
        
        # تنظیم وب‌هوک
        webhook_path = f"/webhook/{self.token}"
        full_webhook_url = f"{webhook_url}{webhook_path}"
        
        try:
            await self.application.bot.set_webhook(
                url=full_webhook_url,
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES
            )
            logger.info(f"وب‌هوک تنظیم شد: {full_webhook_url}")
            
            # ثبت در سیستم
            self.db.log_system_event("INFO", 
                f"وب‌هوک تنظیم شد: {full_webhook_url}", 
                "webhook_setup")
                
        except Exception as e:
            logger.error(f"خطا در تنظیم وب‌هوک: {e}")
            self.db.log_system_event("ERROR", 
                f"خطا در تنظیم وب‌هوک: {str(e)}", 
                "webhook_setup")
    
    async def load_existing_bots(self):
        """بارگذاری ربات‌های موجود"""
        active_bots = self.db.get_active_bots()
        
        logger.info(f"بارگذاری {len(active_bots)} ربات فعال از دیتابیس...")
        
        for bot in active_bots:
            if bot['status'] == BotStatus.ACTIVE.value:
                self.bot_queue.put(("start_bot", bot))
        
        self.db.log_system_event("INFO", 
            f"{len(active_bots)} ربات فعال بارگذاری شدند", 
            "bot_loader")
    
    def shutdown(self, signum=None, frame=None):
        """خاتمه تمیز سیستم"""
        logger.info("در حال خاتمه سیستم...")
        self.is_running = False
        
        # ثبت در سیستم
        self.db.log_system_event("INFO", "سیستم در حال خاتمه است", "shutdown")
        
        # توقف تمام ربات‌های فرزند
        active_bots = self.db.get_active_bots()
        for bot in active_bots:
            self.bot_queue.put(("stop_bot", bot['bot_id']))
        
        logger.info("سیستم خاتمه یافت.")
        sys.exit(0)
    
    async def run_with_webhook(self):
        """اجرا با وب‌هوک"""
        # تنظیم وب‌هوک
        await self.setup_webhook()
        
        # بارگذاری ربات‌های موجود
        await self.load_existing_bots()
        
        # شروع اپلیکیشن
        await self.application.start()
        
        logger.info("ربات مادر با وب‌هوک راه‌اندازی شد.")
        
        # نگه داشتن برنامه در حال اجرا
        await asyncio.Event().wait()
    
    async def run_with_polling(self):
        """اجرا با پولینگ"""
        # بارگذاری ربات‌های موجود
        await self.load_existing_bots()
        
        # شروع اپلیکیشن
        await self.application.initialize()
        await self.application.start()
        
        logger.info("ربات مادر با پولینگ راه‌اندازی شد.")
        
        # شروع پولینگ
        await self.application.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        
        # نگه داشتن برنامه در حال اجرا
        await asyncio.Event().wait()
    
    def run(self):
        """اجرای اصلی سیستم"""
        logger.info("=" * 60)
        logger.info("🤖 **ربات مادر ساخت ربات چت ناشناس**")
        logger.info("🚀 **نسخه مخصوص رندر**")
        logger.info("=" * 60)
        
        # نمایش اطلاعات سیستم
        logger.info(f"محیط: {'رندر' if RENDER else 'محلی'}")
        logger.info(f"پورت: {PORT}")
        logger.info(f"وب‌هوک: {'فعال' if self.renderer.MOTHER_CONFIG['enable_webhook'] else 'غیرفعال'}")
        logger.info(f"تعداد ادمین‌ها: {len(self.renderer.MOTHER_CONFIG['admin_ids'])}")
        
        # شروع لوپ اصلی
        try:
            if self.renderer.MOTHER_CONFIG["enable_webhook"] and RENDER:
                asyncio.run(self.run_with_webhook())
            else:
                asyncio.run(self.run_with_polling())
        
        except KeyboardInterrupt:
            self.shutdown()
        except Exception as e:
            logger.critical(f"خطای بحرانی: {e}")
            self.shutdown()

# ==================== فایل‌های کمکی برای رندر ====================
def create_requirements_file():
    """ایجاد فایل requirements.txt برای رندر"""
    requirements = [
        "python-telegram-bot[job-queue]==20.7",
        "aiohttp==3.9.1",
        "sqlite3",
        "schedule==1.2.0",
        "python-dotenv==1.0.0"
    ]
    
    with open("requirements.txt", "w") as f:
        f.write("\n".join(requirements))
    
    print("✅ فایل requirements.txt ایجاد شد.")

def create_render_yaml():
    """ایجاد فایل render.yaml برای استقرار"""
    yaml_content = """services:
  - type: web
    name: mother-bot
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: python mother_bot_render.py
    envVars:
      - key: ENVIRONMENT
        value: production
      - key: RENDER
        value: "true"
      - key: PORT
        value: 8443
      - key: MOTHER_BOT_TOKEN
        sync: false
      - key: ADMIN_IDS
        sync: false
      - key: WEBHOOK_BASE_URL
        sync: false
      - key: RENDER_API_KEY
        sync: false
        optional: true
    healthCheckPath: /health
    autoDeploy: true
    plan: free
"""
    
    with open("render.yaml", "w") as f:
        f.write(yaml_content)
    
    print("✅ فایل render.yaml ایجاد شد.")

def create_health_endpoint():
    """ایجاد endpoint سلامت برای رندر"""
    health_code = """#!/usr/bin/env python3
from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route('/health')
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "mother-bot",
        "environment": os.environ.get('ENVIRONMENT', 'development')
    }), 200

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8443))
    app.run(host='0.0.0.0', port=port)
"""
    
    with open("health_check.py", "w") as f:
        f.write(health_code)
    
    print("✅ فایل health_check.py ایجاد شد.")

# ==================== اجرای برنامه ====================
if __name__ == "__main__":
    # بررسی و ایجاد فایل‌های لازم
    if not os.path.exists("requirements.txt"):
        create_requirements_file()
    
    if not os.path.exists("render.yaml") and RENDER:
        create_render_yaml()
    
    if not os.path.exists("health_check.py"):
        create_health_endpoint()
    
    # نمایش راهنمای نصب
    if not RENDER and os.environ.get('MOTHER_BOT_TOKEN') == 'YOUR_MOTHER_BOT_TOKEN_HERE':
        print("=" * 70)
        print("🚀 **راهنمای استقرار روی رندر**")
        print("=" * 70)
        print("\n1. تنظیم متغیرهای محیطی در رندر:")
        print("   - MOTHER_BOT_TOKEN: توکن ربات مادر از @BotFather")
        print("   - ADMIN_IDS: آیدی عددی ادمین‌ها (با کاما جدا کنید)")
        print("   - WEBHOOK_BASE_URL: آدرس وب‌سایت شما روی رندر")
        print("   - RENDER_API_KEY: کلید API رندر (اختیاری)")
        print("\n2. آپلود کد به گیتهاب:")
        print("   git add .")
        print("   git commit -m 'Add mother bot'")
        print("   git push origin main")
        print("\n3. اتصال مخزن به رندر:")
        print("   - به render.com بروید")
        print("   - New Web Service")
        print("   - مخزن خود را انتخاب کنید")
        print("   - تنظیمات به صورت خودکار بارگذاری می‌شود")
        print("\n4. ربات آماده استفاده است!")
        print("=" * 70)
    
    # اجرای ربات مادر
    bot = RenderMotherBot()
    bot.run()
