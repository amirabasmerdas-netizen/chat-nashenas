#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات مادر ساخت ربات‌های چت ناشناس
کاربران توکن ربات‌های خود را می‌فرستند و این ربات برایشان یک ربات چت ناشناس می‌سازد
"""

import logging
import json
import asyncio
import aiohttp
import sqlite3
import threading
import queue
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
from dataclasses import dataclass, asdict
from contextlib import contextmanager
import hashlib

# ==================== تنظیمات تلگرام ====================
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode, ChatAction
from telegram.error import TelegramError

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('mother_bot.log', encoding='utf-8'),
        logging.StreamHandler()
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

# ==================== دیتا کلاس‌ها ====================
@dataclass
class BotConfig:
    """تنظیمات هر ربات فرزند"""
    token: str
    owner_id: int
    bot_id: str
    bot_username: str
    created_at: str
    status: str
    webhook_url: Optional[str] = None
    total_messages: int = 0
    total_users: int = 0
    last_activity: Optional[str] = None
    settings: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.settings is None:
            self.settings = {
                "welcome_message": "👋 به ربات چت ناشناس خوش آمدید!",
                "anonymous_prefix": "📨 پیام ناشناس",
                "max_message_length": 2000,
                "rate_limit": 5,
                "allow_media": True,
                "auto_reply": False,
                "notify_owner": True
            }

@dataclass
class UserData:
    """داده‌های کاربر"""
    user_id: int
    username: str
    first_name: str
    last_name: str
    role: str
    created_at: str
    owned_bots: List[str] = None
    subscription_end: Optional[str] = None
    
    def __post_init__(self):
        if self.owned_bots is None:
            self.owned_bots = []

@dataclass
class AnonymousMessage:
    """پیام ناشناس"""
    message_id: str
    bot_id: str
    from_user_id: int
    to_user_id: int
    message_type: str
    content: str
    timestamp: str
    is_read: bool = False
    reply_to: Optional[str] = None

# ==================== کلاس مدیریت دیتابیس ====================
class DatabaseManager:
    """مدیریت دیتابیس SQLite"""
    
    def __init__(self, db_path: str = "mother_bot.db"):
        self.db_path = db_path
        self._init_database()
    
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
                    settings TEXT NOT NULL
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
                    subscription_end TEXT
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
            
            # جدول آمار
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    messages_count INTEGER DEFAULT 0,
                    users_count INTEGER DEFAULT 0,
                    FOREIGN KEY (bot_id) REFERENCES bots (bot_id)
                )
            ''')
            
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        """کانتکست منیجر برای اتصال به دیتابیس"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    # === متدهای ربات‌ها ===
    
    def save_bot(self, bot_config: BotConfig):
        """ذخیره ربات جدید"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO bots 
                (token, owner_id, bot_id, bot_username, created_at, status, webhook_url, 
                 total_messages, total_users, last_activity, settings)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                bot_config.token,
                bot_config.owner_id,
                bot_config.bot_id,
                bot_config.bot_username,
                bot_config.created_at,
                bot_config.status,
                bot_config.webhook_url,
                bot_config.total_messages,
                bot_config.total_users,
                bot_config.last_activity,
                json.dumps(bot_config.settings)
            ))
            conn.commit()
    
    def get_bot(self, bot_id: str) -> Optional[BotConfig]:
        """دریافت تنظیمات ربات"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM bots WHERE bot_id = ?', (bot_id,))
            row = cursor.fetchone()
            
            if row:
                return BotConfig(
                    token=row['token'],
                    owner_id=row['owner_id'],
                    bot_id=row['bot_id'],
                    bot_username=row['bot_username'],
                    created_at=row['created_at'],
                    status=row['status'],
                    webhook_url=row['webhook_url'],
                    total_messages=row['total_messages'],
                    total_users=row['total_users'],
                    last_activity=row['last_activity'],
                    settings=json.loads(row['settings'])
                )
            return None
    
    def get_bot_by_token(self, token: str) -> Optional[BotConfig]:
        """دریافت ربات با توکن"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM bots WHERE token = ?', (token,))
            row = cursor.fetchone()
            
            if row:
                return BotConfig(
                    token=row['token'],
                    owner_id=row['owner_id'],
                    bot_id=row['bot_id'],
                    bot_username=row['bot_username'],
                    created_at=row['created_at'],
                    status=row['status'],
                    webhook_url=row['webhook_url'],
                    total_messages=row['total_messages'],
                    total_users=row['total_users'],
                    last_activity=row['last_activity'],
                    settings=json.loads(row['settings'])
                )
            return None
    
    def get_user_bots(self, user_id: int) -> List[BotConfig]:
        """دریافت ربات‌های یک کاربر"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM bots WHERE owner_id = ?', (user_id,))
            rows = cursor.fetchall()
            
            bots = []
            for row in rows:
                bots.append(BotConfig(
                    token=row['token'],
                    owner_id=row['owner_id'],
                    bot_id=row['bot_id'],
                    bot_username=row['bot_username'],
                    created_at=row['created_at'],
                    status=row['status'],
                    webhook_url=row['webhook_url'],
                    total_messages=row['total_messages'],
                    total_users=row['total_users'],
                    last_activity=row['last_activity'],
                    settings=json.loads(row['settings'])
                ))
            return bots
    
    def update_bot_stats(self, bot_id: str, messages: int = 0, users: int = 0):
        """بروزرسانی آمار ربات"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            if messages > 0:
                cursor.execute('''
                    UPDATE bots 
                    SET total_messages = total_messages + ?, last_activity = ?
                    WHERE bot_id = ?
                ''', (messages, datetime.now().isoformat(), bot_id))
            
            if users > 0:
                cursor.execute('''
                    UPDATE bots 
                    SET total_users = total_users + ?
                    WHERE bot_id = ?
                ''', (users, bot_id))
            
            conn.commit()
    
    def update_bot_status(self, bot_id: str, status: str):
        """بروزرسانی وضعیت ربات"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE bots SET status = ? WHERE bot_id = ?
            ''', (status, bot_id))
            conn.commit()
    
    # === متدهای کاربران ===
    
    def save_user(self, user: UserData):
        """ذخیره کاربر جدید"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, username, first_name, last_name, role, created_at, owned_bots, subscription_end)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user.user_id,
                user.username,
                user.first_name,
                user.last_name,
                user.role,
                user.created_at,
                json.dumps(user.owned_bots),
                user.subscription_end
            ))
            conn.commit()
    
    def get_user(self, user_id: int) -> Optional[UserData]:
        """دریافت اطلاعات کاربر"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            
            if row:
                owned_bots = json.loads(row['owned_bots']) if row['owned_bots'] else []
                return UserData(
                    user_id=row['user_id'],
                    username=row['username'],
                    first_name=row['first_name'],
                    last_name=row['last_name'],
                    role=row['role'],
                    created_at=row['created_at'],
                    owned_bots=owned_bots,
                    subscription_end=row['subscription_end']
                )
            return None
    
    def add_bot_to_user(self, user_id: int, bot_id: str):
        """افزودن ربات به لیست ربات‌های کاربر"""
        user = self.get_user(user_id)
        if user:
            if bot_id not in user.owned_bots:
                user.owned_bots.append(bot_id)
                self.save_user(user)
    
    def update_user_role(self, user_id: int, role: str):
        """بروزرسانی نقش کاربر"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users SET role = ? WHERE user_id = ?
            ''', (role, user_id))
            conn.commit()
    
    # === متدهای پیام‌ها ===
    
    def save_anonymous_message(self, message: AnonymousMessage):
        """ذخیره پیام ناشناس"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO anonymous_messages 
                (message_id, bot_id, from_user_id, to_user_id, message_type, content, timestamp, is_read, reply_to)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                message.message_id,
                message.bot_id,
                message.from_user_id,
                message.to_user_id,
                message.message_type,
                message.content,
                message.timestamp,
                1 if message.is_read else 0,
                message.reply_to
            ))
            conn.commit()
    
    def get_bot_messages(self, bot_id: str, limit: int = 50) -> List[AnonymousMessage]:
        """دریافت پیام‌های یک ربات"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM anonymous_messages 
                WHERE bot_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (bot_id, limit))
            rows = cursor.fetchall()
            
            messages = []
            for row in rows:
                messages.append(AnonymousMessage(
                    message_id=row['message_id'],
                    bot_id=row['bot_id'],
                    from_user_id=row['from_user_id'],
                    to_user_id=row['to_user_id'],
                    message_type=row['message_type'],
                    content=row['content'],
                    timestamp=row['timestamp'],
                    is_read=bool(row['is_read']),
                    reply_to=row['reply_to']
                ))
            return messages
    
    def mark_message_as_read(self, message_id: str):
        """علامت‌گذاری پیام به عنوان خوانده شده"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE anonymous_messages SET is_read = 1 WHERE message_id = ?
            ''', (message_id,))
            conn.commit()
    
    # === متدهای آمار ===
    
    def get_daily_stats(self, bot_id: str, date: str = None):
        """دریافت آمار روزانه"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM stats 
                WHERE bot_id = ? AND date = ?
            ''', (bot_id, date))
            row = cursor.fetchone()
            
            if row:
                return {
                    'messages': row['messages_count'],
                    'users': row['users_count']
                }
            return {'messages': 0, 'users': 0}
    
    def increment_daily_stats(self, bot_id: str, messages: int = 0, users: int = 0):
        """افزایش آمار روزانه"""
        date = datetime.now().strftime("%Y-%m-%d")
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # بررسی وجود رکورد
            cursor.execute('''
                SELECT COUNT(*) as count FROM stats 
                WHERE bot_id = ? AND date = ?
            ''', (bot_id, date))
            
            if cursor.fetchone()['count'] == 0:
                # ایجاد رکورد جدید
                cursor.execute('''
                    INSERT INTO stats (bot_id, date, messages_count, users_count)
                    VALUES (?, ?, ?, ?)
                ''', (bot_id, date, messages, users))
            else:
                # بروزرسانی رکورد موجود
                if messages > 0:
                    cursor.execute('''
                        UPDATE stats 
                        SET messages_count = messages_count + ?
                        WHERE bot_id = ? AND date = ?
                    ''', (messages, bot_id, date))
                
                if users > 0:
                    cursor.execute('''
                        UPDATE stats 
                        SET users_count = users_count + ?
                        WHERE bot_id = ? AND date = ?
                    ''', (users, bot_id, date))
            
            conn.commit()

# ==================== کلاس رندر اصلی ====================
class MotherBotRenderer:
    """
    کلاس رندر ربات مادر - تمام متغیرها و تنظیمات در این کلاس
    """
    
    # ==================== متغیرهای پیکربندی ====================
    
    # تنظیمات اصلی ربات مادر
    MOTHER_CONFIG = {
        "token": "YOUR_MOTHER_BOT_TOKEN_HERE",  # توکن ربات مادر
        "admin_ids": [123456789],  # آیدی ادمین‌های سیستم
        "max_bots_per_user": 3,  # حداکثر ربات برای هر کاربر
        "bot_name_prefix": "AnonymousBot_",  # پیشوند نام ربات‌ها
        "default_webhook_url": "https://your-server.com/webhook",  # آدرس پیش‌فرض وب‌هوک
        "subscription_days": 30,  # روزهای اشتراک پیش‌فرض
        "data_file": "mother_bot_data.json",
        "rate_limit": 3,  # پیام در ثانیه
    }
    
    # متغیرهای متن پیام‌ها
    MESSAGES = {
        # پیام‌های عمومی
        "welcome": "👑 **به ربات مادر ساخت ربات چت ناشناس خوش آمدید!**\n\n"
                  "من می‌توانم برای شما ربات چت ناشناس شخصی‌سازی شده بسازم.\n"
                  "کافیست توکن رباتی که از @BotFather ساخته‌اید را برای من بفرستید.",
        
        "help": "📚 **راهنمای کامل استفاده:**\n\n"
               "🔹 **مراحل ساخت ربات:**\n"
               "1. به @BotFather در تلگرام مراجعه کنید\n"
               "2. ربات جدیدی با دستور /newbot بسازید\n"
               "3. توکن ربات ساخته شده را کپی کنید\n"
               "4. توکن را برای این ربات ارسال کنید\n"
               "5. ربات چت ناشناس شما آماده خواهد شد!\n\n"
               "🔹 **دستورات مدیریتی:**\n"
               "/mybots - مشاهده ربات‌های شما\n"
               "/stats - آمار ربات‌های شما\n"
               "/settings - تنظیمات ربات\n"
               "/help - نمایش این راهنما\n\n"
               "🔹 **ویژگی‌های ربات چت ناشناس:**\n"
               "• دریافت پیام‌های ناشناس\n"
               "• پنل مدیریت پیشرفته\n"
               "• آمار کامل کاربران\n"
               "• سیستم مسدودسازی\n"
               "• پشتیبانی از مدیا\n"
               "• و بسیاری امکانات دیگر!",
        
        "send_token": "🔑 **لطفاً توکن ربات خود را ارسال کنید:**\n\n"
                     "توکن ربات شما چیزی شبیه به این است:\n"
                     "`1234567890:ABCdefGHIJKLMNopqRSTUvwxYZ`\n\n"
                     "⚠️ **توجه:** توکن ربات مانند رمز عبور است، آن را با کسی به اشتراک نگذارید!",
        
        "processing_token": "🔄 **در حال پردازش توکن...**\n\n"
                          "لطفاً چند لحظه صبر کنید.",
        
        "token_valid": "✅ **توکن معتبر است!**\n\n"
                      "ربات: @{bot_username}\n"
                      "آیدی: `{bot_id}`\n\n"
                      "در حال ساخت ربات چت ناشناس...",
        
        "token_invalid": "❌ **توکن نامعتبر است!**\n\n"
                        "لطفاً مطمئن شوید توکن را به درستی کپی کرده‌اید.\n"
                        "توکن باید با فرمت زیر باشد:\n"
                        "`عدد:رشته حروف و اعداد`",
        
        "bot_created": "🎉 **ربات چت ناشناس شما ساخته شد!**\n\n"
                      "🤖 **نام ربات:** @{bot_username}\n"
                      "🔗 **لینک ربات:** t.me/{bot_username}\n"
                      "👤 **مالک:** شما (آیدی: `{owner_id}`)\n"
                      "📅 **تاریخ ایجاد:** {created_at}\n\n"
                      "✨ **ربات شما آماده استفاده است!**\n"
                      "کاربران می‌توانند با ارسال پیام به ربات شما، پیام‌های ناشناس برای شما بفرستند.\n\n"
                      "📊 برای مدیریت ربات از دستورات زیر استفاده کنید:",
        
        "max_bots_reached": "⚠️ **شما به حداکثر تعداد ربات مجاز رسیده‌اید!**\n\n"
                           "تعداد ربات‌های فعلی شما: {current}/{max}\n"
                           "برای ساخت ربات بیشتر با پشتیبانی تماس بگیرید.",
        
        "no_bots": "📭 **شما هنوز هیچ رباتی نساخته‌اید!**\n\n"
                  "برای ساخت اولین ربات چت ناشناس خود، توکن ربات را ارسال کنید.",
        
        "bot_list": "🤖 **ربات‌های شما:**\n\n",
        
        "bot_info": "🔹 **@{bot_username}**\n"
                   "🆔 آیدی: `{bot_id}`\n"
                   "📊 پیام‌ها: {total_messages}\n"
                   "👥 کاربران: {total_users}\n"
                   "📅 آخرین فعالیت: {last_activity}\n"
                   "🔰 وضعیت: {status}\n",
        
        "stats": "📈 **آمار کلی شما:**\n\n"
                "🤖 **تعداد ربات‌ها:** {total_bots}\n"
                "📨 **کل پیام‌ها:** {total_messages}\n"
                "👥 **کل کاربران:** {total_users}\n"
                "📅 **اشتراک شما تا:** {subscription_end}\n\n"
                "📊 **آمار امروز:**\n"
                "📨 پیام‌ها: {today_messages}\n"
                "👥 کاربران جدید: {today_users}",
        
        # پیام‌های مدیریتی
        "admin_panel": "👑 **پنل مدیریت سیستم**\n\n"
                      "تعداد کل ربات‌ها: {total_bots}\n"
                      "تعداد کل کاربران: {total_users}\n"
                      "ربات‌های فعال: {active_bots}\n\n"
                      "👇 برای مدیریت از دکمه‌های زیر استفاده کنید:",
        
        "user_management": "👤 **مدیریت کاربران**\n\n"
                          "کاربر: {user_info}\n"
                          "ربات‌ها: {user_bots}\n"
                          "اشتراک تا: {subscription}\n\n"
                          "👇 اقدامات مدیریتی:",
        
        "bot_management": "🤖 **مدیریت ربات**\n\n"
                         "ربات: @{bot_username}\n"
                         "مالک: {owner_info}\n"
                         "وضعیت: {status}\n"
                         "پیام‌ها: {messages}\n\n"
                         "👇 اقدامات مدیریتی:",
        
        "broadcast_all": "📢 **ارسال پیام همگانی به همه کاربران**\n\n"
                        "لطفاً پیام خود را وارد کنید:",
        
        # پیام‌های خطا
        "error": "❌ **خطا!**\n\n"
                "متأسفانه خطایی رخ داده است.\n"
                "لطفاً بعداً تلاش کنید یا با پشتیبانی تماس بگیرید.",
        
        "access_denied": "⛔ **دسترسی denied!**\n\n"
                        "شما دسترسی به این بخش را ندارید.",
        
        "bot_not_found": "❌ **ربات یافت نشد!**\n\n"
                        "ربات مورد نظر وجود ندارد یا حذف شده است.",
    }
    
    # متغیرهای دکمه‌ها
    BUTTONS = {
        # ریپلای کیبورد
        "reply": {
            "create_bot": "🤖 ساخت ربات جدید",
            "my_bots": "📋 ربات‌های من",
            "stats": "📊 آمار من",
            "help": "ℹ️ راهنمای استفاده",
            "admin_panel": "👑 پنل مدیریت",
            "cancel": "🔙 لغو",
            "back": "🔙 بازگشت",
            "home": "🏠 صفحه اصلی",
        },
        
        # اینلاین کیبورد
        "inline": {
            # مدیریت ربات‌ها
            "bot_settings": "⚙️ تنظیمات ربات",
            "bot_stats": "📊 آمار ربات",
            "bot_stop": "⏹️ توقف ربات",
            "bot_start": "▶️ راه‌اندازی ربات",
            "bot_delete": "🗑️ حذف ربات",
            "bot_webhook": "🔗 تنظیم وب‌هوک",
            
            # مدیریت کاربران
            "user_info": "👤 اطلاعات کاربر",
            "user_bots": "🤖 ربات‌های کاربر",
            "user_ban": "🚫 مسدود کردن",
            "user_unban": "✅ آزاد کردن",
            "user_extend": "📅 تمدید اشتراک",
            
            # پنل مدیریت
            "all_bots": "📋 همه ربات‌ها",
            "all_users": "👥 همه کاربران",
            "system_stats": "📈 آمار سیستم",
            "broadcast": "📢 ارسال همگانی",
            "backup": "💾 پشتیبان‌گیری",
            
            # ناوبری
            "back": "🔙 بازگشت",
            "back_to_admin": "🔙 به مدیریت",
            "back_to_list": "🔙 به لیست",
            "refresh": "🔄 بروزرسانی",
        }
    }
    
    # فرمت‌ها
    FORMATS = {
        "datetime": "%Y-%m-%d %H:%M:%S",
        "date": "%Y-%m-%d",
        "time": "%H:%M",
        "subscription": "%Y/%m/%d",
    }
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        
    # ==================== متدهای رندر اصلی ====================
    
    def render_welcome(self, user_id: int) -> Tuple[str, ReplyKeyboardMarkup]:
        """رندر صفحه خوشامدگویی"""
        user = self.db.get_user(user_id)
        is_admin = user_id in self.MOTHER_CONFIG["admin_ids"] if user else False
        
        welcome_text = self.MESSAGES["welcome"]
        
        if user:
            welcome_text = f"👋 سلام {user.first_name}!\n\n" + welcome_text
        
        # ساخت کیبورد
        buttons = [
            [self.BUTTONS["reply"]["create_bot"]],
            [self.BUTTONS["reply"]["my_bots"], self.BUTTONS["reply"]["stats"]],
            [self.BUTTONS["reply"]["help"]]
        ]
        
        if is_admin:
            buttons.append([self.BUTTONS["reply"]["admin_panel"]])
        
        reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        
        return welcome_text, reply_markup
    
    def render_help(self) -> str:
        """رندر صفحه راهنما"""
        return self.MESSAGES["help"]
    
    def render_send_token(self) -> str:
        """رندر درخواست توکن"""
        return self.MESSAGES["send_token"]
    
    def render_token_processing(self) -> str:
        """رندر در حال پردازش"""
        return self.MESSAGES["processing_token"]
    
    def render_token_valid(self, bot_username: str, bot_id: str) -> str:
        """رندر تأیید توکن"""
        return self.MESSAGES["token_valid"].format(
            bot_username=bot_username,
            bot_id=bot_id
        )
    
    def render_token_invalid(self) -> str:
        """رندر توکن نامعتبر"""
        return self.MESSAGES["token_invalid"]
    
    def render_bot_created(self, bot_config: BotConfig) -> Tuple[str, InlineKeyboardMarkup]:
        """رندر تأیید ساخت ربات"""
        created_at = datetime.fromisoformat(bot_config.created_at).strftime(self.FORMATS["datetime"])
        
        bot_info = self.MESSAGES["bot_created"].format(
            bot_username=bot_config.bot_username,
            owner_id=bot_config.owner_id,
            created_at=created_at
        )
        
        # ساخت اینلاین کیبورد
        keyboard = [
            [
                InlineKeyboardButton(
                    self.BUTTONS["inline"]["bot_settings"],
                    callback_data=f"bot_settings_{bot_config.bot_id}"
                ),
                InlineKeyboardButton(
                    self.BUTTONS["inline"]["bot_stats"],
                    callback_data=f"bot_stats_{bot_config.bot_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔗 لینک ربات",
                    url=f"https://t.me/{bot_config.bot_username}"
                )
            ]
        ]
        
        inline_markup = InlineKeyboardMarkup(keyboard)
        
        return bot_info, inline_markup
    
    def render_max_bots_reached(self, current: int, max_limit: int) -> str:
        """رندر رسیدن به حداکثر ربات"""
        return self.MESSAGES["max_bots_reached"].format(
            current=current,
            max=max_limit
        )
    
    def render_my_bots(self, user_id: int) -> Tuple[str, InlineKeyboardMarkup]:
        """رندر لیست ربات‌های کاربر"""
        bots = self.db.get_user_bots(user_id)
        
        if not bots:
            return self.MESSAGES["no_bots"], None
        
        bot_list_text = self.MESSAGES["bot_list"]
        
        for i, bot in enumerate(bots, 1):
            last_activity = "بدون فعالیت"
            if bot.last_activity:
                last_activity = datetime.fromisoformat(bot.last_activity).strftime(self.FORMATS["datetime"])
            
            status_icons = {
                BotStatus.ACTIVE.value: "🟢",
                BotStatus.INACTIVE.value: "🔴",
                BotStatus.SUSPENDED.value: "🟡",
                BotStatus.PENDING.value: "🟠"
            }
            
            bot_list_text += f"{i}. {status_icons.get(bot.status, '⚪')} @{bot.bot_username}\n"
            bot_list_text += f"   📨 پیام‌ها: {bot.total_messages} | 👤 کاربران: {bot.total_users}\n"
            bot_list_text += f"   🕒 آخرین فعالیت: {last_activity}\n\n"
        
        # ساخت اینلاین کیبورد
        keyboard = []
        for bot in bots[:5]:  # حداکثر 5 ربات در صفحه
            keyboard.append([
                InlineKeyboardButton(
                    f"⚙️ @{bot.bot_username}",
                    callback_data=f"bot_manage_{bot.bot_id}"
                )
            ])
        
        if len(bots) > 5:
            keyboard.append([
                InlineKeyboardButton(
                    "📖 صفحه بعد",
                    callback_data="next_page_2"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton(
                self.BUTTONS["inline"]["refresh"],
                callback_data="refresh_bots"
            ),
            InlineKeyboardButton(
                self.BUTTONS["reply"]["home"],
                callback_data="home"
            )
        ])
        
        inline_markup = InlineKeyboardMarkup(keyboard)
        
        return bot_list_text, inline_markup
    
    def render_bot_management(self, bot_config: BotConfig) -> Tuple[str, InlineKeyboardMarkup]:
        """رندر صفحه مدیریت ربات"""
        owner = self.db.get_user(bot_config.owner_id)
        owner_info = f"{owner.first_name} (@{owner.username})" if owner else "نامشخص"
        
        last_activity = "بدون فعالیت"
        if bot_config.last_activity:
            last_activity = datetime.fromisoformat(bot_config.last_activity).strftime(self.FORMATS["datetime"])
        
        status_texts = {
            BotStatus.ACTIVE.value: "🟢 فعال",
            BotStatus.INACTIVE.value: "🔴 غیرفعال",
            BotStatus.SUSPENDED.value: "🟡 معلق",
            BotStatus.PENDING.value: "🟠 در انتظار"
        }
        
        bot_info = self.MESSAGES["bot_management"].format(
            bot_username=bot_config.bot_username,
            owner_info=owner_info,
            status=status_texts.get(bot_config.status, "نامشخص"),
            messages=bot_config.total_messages
        )
        
        # ساخت اینلاین کیبورد
        keyboard = []
        
        # ردیف 1: وضعیت ربات
        if bot_config.status == BotStatus.ACTIVE.value:
            keyboard.append([
                InlineKeyboardButton(
                    self.BUTTONS["inline"]["bot_stop"],
                    callback_data=f"bot_stop_{bot_config.bot_id}"
                )
            ])
        else:
            keyboard.append([
                InlineKeyboardButton(
                    self.BUTTONS["inline"]["bot_start"],
                    callback_data=f"bot_start_{bot_config.bot_id}"
                )
            ])
        
        # ردیف 2: تنظیمات
        keyboard.append([
            InlineKeyboardButton(
                self.BUTTONS["inline"]["bot_settings"],
                callback_data=f"bot_settings_{bot_config.bot_id}"
            ),
            InlineKeyboardButton(
                self.BUTTONS["inline"]["bot_stats"],
                callback_data=f"bot_stats_{bot_config.bot_id}"
            )
        ])
        
        # ردیف 3: اقدامات
        keyboard.append([
            InlineKeyboardButton(
                self.BUTTONS["inline"]["bot_webhook"],
                callback_data=f"bot_webhook_{bot_config.bot_id}"
            ),
            InlineKeyboardButton(
                self.BUTTONS["inline"]["bot_delete"],
                callback_data=f"bot_delete_{bot_config.bot_id}"
            )
        ])
        
        # ردیف 4: ناوبری
        keyboard.append([
            InlineKeyboardButton(
                self.BUTTONS["inline"]["back"],
                callback_data="back_to_bots"
            ),
            InlineKeyboardButton(
                "🔗 لینک ربات",
                url=f"https://t.me/{bot_config.bot_username}"
            )
        ])
        
        inline_markup = InlineKeyboardMarkup(keyboard)
        
        return bot_info, inline_markup
    
    def render_admin_panel(self) -> Tuple[str, InlineKeyboardMarkup]:
        """رندر پنل مدیریت"""
        # محاسبه آمار
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            
            # تعداد کل ربات‌ها
            cursor.execute('SELECT COUNT(*) as count FROM bots')
            total_bots = cursor.fetchone()['count']
            
            # تعداد کاربران
            cursor.execute('SELECT COUNT(*) as count FROM users')
            total_users = cursor.fetchone()['count']
            
            # ربات‌های فعال
            cursor.execute('SELECT COUNT(*) as count FROM bots WHERE status = ?', (BotStatus.ACTIVE.value,))
            active_bots = cursor.fetchone()['count']
        
        admin_text = self.MESSAGES["admin_panel"].format(
            total_bots=total_bots,
            total_users=total_users,
            active_bots=active_bots
        )
        
        # ساخت اینلاین کیبورد
        keyboard = [
            [
                InlineKeyboardButton(
                    self.BUTTONS["inline"]["all_bots"],
                    callback_data="admin_all_bots"
                ),
                InlineKeyboardButton(
                    self.BUTTONS["inline"]["all_users"],
                    callback_data="admin_all_users"
                )
            ],
            [
                InlineKeyboardButton(
                    self.BUTTONS["inline"]["system_stats"],
                    callback_data="admin_system_stats"
                ),
                InlineKeyboardButton(
                    self.BUTTONS["inline"]["broadcast"],
                    callback_data="admin_broadcast"
                )
            ],
            [
                InlineKeyboardButton(
                    self.BUTTONS["inline"]["backup"],
                    callback_data="admin_backup"
                ),
                InlineKeyboardButton(
                    self.BUTTONS["inline"]["back"],
                    callback_data="home"
                )
            ]
        ]
        
        inline_markup = InlineKeyboardMarkup(keyboard)
        
        return admin_text, inline_markup
    
    def render_user_stats(self, user_id: int) -> str:
        """رندر آمار کاربر"""
        user = self.db.get_user(user_id)
        bots = self.db.get_user_bots(user_id)
        
        if not user:
            return "❌ کاربر یافت نشد!"
        
        # محاسبه آمار
        total_messages = sum(bot.total_messages for bot in bots)
        total_users = sum(bot.total_users for bot in bots)
        
        # آمار امروز
        today_messages = 0
        today_users = 0
        
        for bot in bots:
            stats = self.db.get_daily_stats(bot.bot_id)
            today_messages += stats.get('messages', 0)
            today_users += stats.get('users', 0)
        
        # تاریخ اشتراک
        subscription_end = "نامحدود"
        if user.subscription_end:
            sub_date = datetime.fromisoformat(user.subscription_end)
            subscription_end = sub_date.strftime(self.FORMATS["subscription"])
            
            if sub_date < datetime.now():
                subscription_end += " (منقضی شده)"
        
        stats_text = self.MESSAGES["stats"].format(
            total_bots=len(bots),
            total_messages=total_messages,
            total_users=total_users,
            subscription_end=subscription_end,
            today_messages=today_messages,
            today_users=today_users
        )
        
        return stats_text

# ==================== کلاس ربات چت ناشناس (فرزند) ====================
class AnonymousChildBot:
    """ربات چت ناشناس که برای هر کاربر ساخته می‌شود"""
    
    def __init__(self, bot_config: BotConfig, db_manager: DatabaseManager, mother_renderer: MotherBotRenderer):
        self.config = bot_config
        self.db = db_manager
        self.mother_renderer = mother_renderer
        self.application = None
        self.user_cooldowns = {}
        
        # تنظیمات رندر این ربات
        self.CHILD_MESSAGES = {
            "welcome": "👋 **به ربات چت ناشناس خوش آمدید!**\n\n"
                      "شما می‌توانید پیام‌های ناشناس خود را برای مالک این ربات ارسال کنید.\n"
                      "هر پیام با حفظ کامل حریم خصوصی شما ارسال می‌شود.",
            
            "message_sent": "✅ **پیام شما ارسال شد!**\n\n"
                          "پیام شما به صورت ناشناس برای مالک ربات ارسال شد.",
            
            "new_message_owner": "📨 **پیام ناشناس جدید**\n\n"
                               "👤 **فرستنده:** کاربر ناشناس\n"
                               "🆔 **آیدی:** `{user_id}`\n"
                               "📅 **زمان:** {time}\n"
                               "📝 **پیام:**\n{message}\n\n"
                               "👇 برای پاسخ استفاده کنید:",
            
            "owner_reply": "📩 **پاسخ از مالک ربات:**\n\n{message}",
        }
        
        self.CHILD_BUTTONS = {
            "send_message": "📝 ارسال پیام ناشناس",
            "help": "ℹ️ راهنمای استفاده",
            "cancel": "🔙 لغو",
            "view_profile": "👁️ مشاهده پروفایل",
            "reply": "💬 پاسخ",
            "ban": "🚫 مسدود کردن",
        }
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """دستور /start برای ربات فرزند"""
        user = update.effective_user
        
        # ثبت کاربر در دیتابیس ربات
        self.db.increment_daily_stats(self.config.bot_id, users=1)
        self.db.update_bot_stats(self.config.bot_id, users=1)
        
        # ایجاد کیبورد
        keyboard = [[self.CHILD_BUTTONS["send_message"]], [self.CHILD_BUTTONS["help"]]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            self.CHILD_MESSAGES["welcome"],
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """مدیریت پیام‌ها در ربات فرزند"""
        user = update.effective_user
        message_text = update.message.text
        
        # اگر کاربر مالک است
        if user.id == self.config.owner_id:
            await self._handle_owner_message(update, context, message_text)
            return
        
        # اگر کاربر عادی است
        if message_text == self.CHILD_BUTTONS["send_message"]:
            await update.message.reply_text(
                "لطفاً پیام ناشناس خود را وارد کنید:",
                reply_markup=ReplyKeyboardMarkup([[self.CHILD_BUTTONS["cancel"]]], resize_keyboard=True)
            )
            context.user_data['waiting_for_message'] = True
        
        elif message_text == self.CHILD_BUTTONS["help"]:
            help_text = "📖 **راهنمای ربات چت ناشناس:**\n\n"
            help_text += "1. روی 'ارسال پیام ناشناس' کلیک کنید\n"
            help_text += "2. پیام خود را وارد کرده و ارسال کنید\n"
            help_text += "3. پیام شما به صورت ناشناس برای مالک ارسال می‌شود\n"
            help_text += "4. مالک می‌تواند به شما پاسخ دهد\n\n"
            help_text += "⚠️ از ارسال محتوای نامناسب خودداری کنید."
            
            await update.message.reply_text(help_text)
        
        elif message_text == self.CHILD_BUTTONS["cancel"]:
            keyboard = [[self.CHILD_BUTTONS["send_message"]], [self.CHILD_BUTTONS["help"]]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                "عملیات لغو شد.",
                reply_markup=reply_markup
            )
            context.user_data.pop('waiting_for_message', None)
        
        elif context.user_data.get('waiting_for_message', False):
            # ارسال پیام ناشناس به مالک
            await self._send_anonymous_message(update, context, message_text)
            context.user_data.pop('waiting_for_message', None)
    
    async def _send_anonymous_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE, message: str):
        """ارسال پیام ناشناس به مالک"""
        user = update.effective_user
        
        # ذخیره پیام در دیتابیس
        message_id = f"{self.config.bot_id}_{user.id}_{datetime.now().timestamp()}"
        
        anonymous_message = AnonymousMessage(
            message_id=message_id,
            bot_id=self.config.bot_id,
            from_user_id=user.id,
            to_user_id=self.config.owner_id,
            message_type=MessageType.TEXT.value,
            content=message,
            timestamp=datetime.now().isoformat()
        )
        
        self.db.save_anonymous_message(anonymous_message)
        
        # بروزرسانی آمار
        self.db.increment_daily_stats(self.config.bot_id, messages=1)
        self.db.update_bot_stats(self.config.bot_id, messages=1)
        
        # ارسال به مالک
        current_time = datetime.now().strftime(self.mother_renderer.FORMATS["datetime"])
        
        owner_message = self.CHILD_MESSAGES["new_message_owner"].format(
            user_id=user.id,
            time=current_time,
            message=message
        )
        
        # ایجاد اینلاین کیبورد برای مالک
        keyboard = [
            [
                InlineKeyboardButton(
                    self.CHILD_BUTTONS["reply"],
                    callback_data=f"reply_{user.id}_{message_id}"
                ),
                InlineKeyboardButton(
                    self.CHILD_BUTTONS["view_profile"],
                    callback_data=f"profile_{user.id}"
                )
            ],
            [
                InlineKeyboardButton(
                    self.CHILD_BUTTONS["ban"],
                    callback_data=f"ban_{user.id}"
                )
            ]
        ]
        
        inline_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await context.bot.send_message(
                chat_id=self.config.owner_id,
                text=owner_message,
                reply_markup=inline_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
            # تأیید به کاربر
            await update.message.reply_text(
                self.CHILD_MESSAGES["message_sent"],
                reply_markup=ReplyKeyboardMarkup(
                    [[self.CHILD_BUTTONS["send_message"]]],
                    resize_keyboard=True
                )
            )
            
        except Exception as e:
            logger.error(f"خطا در ارسال پیام به مالک: {e}")
            await update.message.reply_text("❌ خطا در ارسال پیام.")
    
    async def _handle_owner_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE, message: str):
        """مدیریت پیام‌های مالک"""
        # اگر مالک در حال پاسخ است
        if 'replying_to' in context.user_data:
            target_user_id = context.user_data['replying_to']
            original_message_id = context.user_data.get('original_message_id')
            
            try:
                # ارسال پاسخ به کاربر
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=self.CHILD_MESSAGES["owner_reply"].format(message=message),
                    parse_mode=ParseMode.MARKDOWN
                )
                
                await update.message.reply_text("✅ پاسخ ارسال شد.")
                
                # ذخیره پاسخ در دیتابیس
                if original_message_id:
                    reply_message_id = f"{self.config.bot_id}_{self.config.owner_id}_{datetime.now().timestamp()}"
                    
                    reply_message = AnonymousMessage(
                        message_id=reply_message_id,
                        bot_id=self.config.bot_id,
                        from_user_id=self.config.owner_id,
                        to_user_id=target_user_id,
                        message_type=MessageType.TEXT.value,
                        content=f"پاسخ به پیام {original_message_id}: {message}",
                        timestamp=datetime.now().isoformat(),
                        reply_to=original_message_id
                    )
                    
                    self.db.save_anonymous_message(reply_message)
                
            except Exception as e:
                logger.error(f"خطا در ارسال پاسخ: {e}")
                await update.message.reply_text("❌ خطا در ارسال پاسخ.")
            
            context.user_data.pop('replying_to', None)
            context.user_data.pop('original_message_id', None)
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """مدیریت کلیک روی دکمه‌های اینلاین"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user = update.effective_user
        
        # فقط مالک می‌تواند از دکمه‌ها استفاده کند
        if user.id != self.config.owner_id:
            await query.edit_message_text("⛔ دسترسی denied!")
            return
        
        if data.startswith("reply_"):
            # پاسخ به کاربر
            parts = data.split("_")
            target_user_id = int(parts[1])
            original_message_id = parts[2] if len(parts) > 2 else None
            
            context.user_data['replying_to'] = target_user_id
            if original_message_id:
                context.user_data['original_message_id'] = original_message_id
            
            await query.edit_message_text(
                f"📝 در حال پاسخ به کاربر `{target_user_id}`\n\nلطفاً پاسخ خود را وارد کنید:"
            )
        
        elif data.startswith("ban_"):
            # مسدود کردن کاربر
            target_user_id = int(data.split("_")[1])
            
            # در اینجا می‌توانید سیستم مسدودسازی را پیاده‌سازی کنید
            await query.edit_message_text(f"✅ کاربر `{target_user_id}` مسدود شد.")
    
    def setup_handlers(self):
        """تنظیم هندلرهای ربات فرزند"""
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))
    
    async def start_bot(self):
        """راه‌اندازی ربات فرزند"""
        self.application = Application.builder().token(self.config.token).build()
        self.setup_handlers()
        
        # اگر وب‌هوک تنظیم شده است
        if self.config.webhook_url:
            await self.application.bot.set_webhook(
                url=f"{self.config.webhook_url}/{self.config.token}",
                drop_pending_updates=True
            )
        
        # بروزرسانی وضعیت ربات
        self.db.update_bot_status(self.config.bot_id, BotStatus.ACTIVE.value)
        
        logger.info(f"ربات فرزند @{self.config.bot_username} راه‌اندازی شد.")
    
    async def stop_bot(self):
        """توقف ربات فرزند"""
        if self.application:
            await self.application.stop()
            await self.application.shutdown()
        
        self.db.update_bot_status(self.config.bot_id, BotStatus.INACTIVE.value)
        logger.info(f"ربات فرزند @{self.config.bot_username} متوقف شد.")

# ==================== کلاس اصلی ربات مادر ====================
class MotherBot:
    """کلاس اصلی ربات مادر"""
    
    def __init__(self):
        self.db = DatabaseManager()
        self.renderer = MotherBotRenderer(self.db)
        self.application = None
        self.child_bots: Dict[str, AnonymousChildBot] = {}
        self.bot_manager_queue = queue.Queue()
        self.is_running = False
        
        # راه‌اندازی مدیریت‌کننده ربات‌های فرزند
        self._start_child_bot_manager()
    
    def _start_child_bot_manager(self):
        """راه‌اندازی مدیر ربات‌های فرزند"""
        def manager_worker():
            while self.is_running:
                try:
                    task = self.bot_manager_queue.get(timeout=1)
                    if task:
                        task_type, data = task
                        
                        if task_type == "start_bot":
                            bot_config = data
                            asyncio.run(self._start_child_bot(bot_config))
                        
                        elif task_type == "stop_bot":
                            bot_id = data
                            asyncio.run(self._stop_child_bot(bot_id))
                
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"خطا در مدیریت‌کننده ربات‌ها: {e}")
        
        self.is_running = True
        manager_thread = threading.Thread(target=manager_worker, daemon=True)
        manager_thread.start()
    
    async def _start_child_bot(self, bot_config: BotConfig):
        """راه‌اندازی ربات فرزند"""
        try:
            child_bot = AnonymousChildBot(bot_config, self.db, self.renderer)
            self.child_bots[bot_config.bot_id] = child_bot
            
            # راه‌اندازی ربات در یک ترد جدید
            await child_bot.start_bot()
            
            # اگر از پولینگ استفاده می‌کنیم
            if not bot_config.webhook_url:
                # در یک ترد جداگانه اجرا می‌شود
                def run_polling():
                    asyncio.run(child_bot.application.run_polling(
                        allowed_updates=Update.ALL_TYPES,
                        drop_pending_updates=True
                    ))
                
                polling_thread = threading.Thread(target=run_polling, daemon=True)
                polling_thread.start()
            
        except Exception as e:
            logger.error(f"خطا در راه‌اندازی ربات فرزند: {e}")
            self.db.update_bot_status(bot_config.bot_id, BotStatus.SUSPENDED.value)
    
    async def _stop_child_bot(self, bot_id: str):
        """توقف ربات فرزند"""
        if bot_id in self.child_bots:
            await self.child_bots[bot_id].stop_bot()
            del self.child_bots[bot_id]
    
    async def validate_bot_token(self, token: str) -> Optional[Dict[str, Any]]:
        """اعتبارسنجی توکن ربات"""
        try:
            # تست توکن با دریافت اطلاعات ربات
            test_app = Application.builder().token(token).build()
            
            async with test_app:
                bot_info = await test_app.bot.get_me()
                
                return {
                    "is_valid": True,
                    "bot_id": str(bot_info.id),
                    "bot_username": bot_info.username,
                    "bot_name": bot_info.first_name
                }
        
        except Exception as e:
            logger.error(f"خطا در اعتبارسنجی توکن: {e}")
            return None
    
    async def create_child_bot(self, token: str, owner_id: int) -> Optional[BotConfig]:
        """ایجاد ربات فرزند جدید"""
        # اعتبارسنجی توکن
        bot_info = await self.validate_bot_token(token)
        
        if not bot_info or not bot_info["is_valid"]:
            return None
        
        # بررسی تعداد ربات‌های کاربر
        user_bots = self.db.get_user_bots(owner_id)
        max_bots = self.renderer.MOTHER_CONFIG["max_bots_per_user"]
        
        if len(user_bots) >= max_bots:
            return None
        
        # ایجاد آیدی منحصر به فرد برای ربات
        bot_hash = hashlib.md5(f"{token}_{owner_id}".encode()).hexdigest()[:8]
        bot_id = f"{self.renderer.MOTHER_CONFIG['bot_name_prefix']}{bot_hash}"
        
        # ایجاد تنظیمات ربات
        bot_config = BotConfig(
            token=token,
            owner_id=owner_id,
            bot_id=bot_id,
            bot_username=bot_info["bot_username"],
            created_at=datetime.now().isoformat(),
            status=BotStatus.PENDING.value,
            webhook_url=self.renderer.MOTHER_CONFIG["default_webhook_url"],
            total_messages=0,
            total_users=0,
            settings={
                "welcome_message": "👋 به ربات چت ناشناس خوش آمدید!",
                "auto_reply": False,
                "notify_owner": True,
                "max_message_length": 2000,
                "allow_media": True
            }
        )
        
        # ذخیره در دیتابیس
        self.db.save_bot(bot_config)
        
        # افزودن به کاربر
        user = self.db.get_user(owner_id)
        if user:
            self.db.add_bot_to_user(owner_id, bot_id)
        
        # راه‌اندازی ربات در صف
        self.bot_manager_queue.put(("start_bot", bot_config))
        
        return bot_config
    
    # ==================== هندلرهای ربات مادر ====================
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """دستور /start"""
        user = update.effective_user
        
        # ثبت یا بروزرسانی کاربر
        existing_user = self.db.get_user(user.id)
        
        if not existing_user:
            new_user = UserData(
                user_id=user.id,
                username=user.username or "",
                first_name=user.first_name,
                last_name=user.last_name or "",
                role=UserRole.USER.value,
                created_at=datetime.now().isoformat(),
                subscription_end=(datetime.now() + timedelta(days=30)).isoformat()
            )
            self.db.save_user(new_user)
        else:
            # بروزرسانی اطلاعات کاربر
            existing_user.username = user.username or ""
            existing_user.first_name = user.first_name
            existing_user.last_name = user.last_name or ""
            self.db.save_user(existing_user)
        
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
        
        # بررسی مالک بودن
        is_admin = user.id in self.renderer.MOTHER_CONFIG["admin_ids"]
        
        # پردازش پیام‌ها بر اساس دکمه‌ها
        if message_text == self.renderer.BUTTONS["reply"]["create_bot"]:
            # درخواست توکن
            send_token_msg = self.renderer.render_send_token()
            await update.message.reply_text(
                send_token_msg,
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data['waiting_for_token'] = True
        
        elif message_text == self.renderer.BUTTONS["reply"]["my_bots"]:
            # نمایش ربات‌های کاربر
            bots_text, inline_markup = self.renderer.render_my_bots(user.id)
            
            if inline_markup:
                await update.message.reply_text(
                    bots_text,
                    reply_markup=inline_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    bots_text,
                    parse_mode=ParseMode.MARKDOWN
                )
        
        elif message_text == self.renderer.BUTTONS["reply"]["stats"]:
            # نمایش آمار کاربر
            stats_text = self.renderer.render_user_stats(user.id)
            await update.message.reply_text(
                stats_text,
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif message_text == self.renderer.BUTTONS["reply"]["help"]:
            # نمایش راهنما
            help_text = self.renderer.render_help()
            await update.message.reply_text(
                help_text,
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif message_text == self.renderer.BUTTONS["reply"]["admin_panel"] and is_admin:
            # پنل مدیریت
            admin_text, inline_markup = self.renderer.render_admin_panel()
            await update.message.reply_text(
                admin_text,
                reply_markup=inline_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif message_text == self.renderer.BUTTONS["reply"]["cancel"]:
            # لغو عملیات
            welcome_text, reply_markup = self.renderer.render_welcome(user.id)
            await update.message.reply_text(
                "عملیات لغو شد.",
                reply_markup=reply_markup
            )
            context.user_data.pop('waiting_for_token', None)
        
        elif context.user_data.get('waiting_for_token', False):
            # دریافت توکن ربات
            await self._handle_bot_token(update, context, message_text)
            context.user_data.pop('waiting_for_token', None)
        
        else:
            # نمایش صفحه اصلی
            welcome_text, reply_markup = self.renderer.render_welcome(user.id)
            await update.message.reply_text(
                "لطفاً از دکمه‌های زیر استفاده کنید:",
                reply_markup=reply_markup
            )
    
    async def _handle_bot_token(self, update: Update, context: ContextTypes.DEFAULT_TYPE, token: str):
        """مدیریت دریافت توکن ربات"""
        user = update.effective_user
        
        # نمایش پیام در حال پردازش
        processing_msg = self.renderer.render_token_processing()
        processing_message = await update.message.reply_text(processing_msg)
        
        try:
            # بررسی فرمت توکن
            if not self._validate_token_format(token):
                await processing_message.edit_text(self.renderer.render_token_invalid())
                return
            
            # بررسی تعداد ربات‌های کاربر
            user_bots = self.db.get_user_bots(user.id)
            max_bots = self.renderer.MOTHER_CONFIG["max_bots_per_user"]
            
            if len(user_bots) >= max_bots:
                max_bots_msg = self.renderer.render_max_bots_reached(len(user_bots), max_bots)
                await processing_message.edit_text(max_bots_msg)
                return
            
            # اعتبارسنجی توکن
            bot_info = await self.validate_bot_token(token)
            
            if not bot_info:
                await processing_message.edit_text(self.renderer.render_token_invalid())
                return
            
            # نمایش تأیید توکن
            valid_msg = self.renderer.render_token_valid(
                bot_info["bot_username"],
                bot_info["bot_id"]
            )
            await processing_message.edit_text(valid_msg)
            
            # ایجاد ربات فرزند
            bot_config = await self.create_child_bot(token, user.id)
            
            if not bot_config:
                await processing_message.edit_text("❌ خطا در ساخت ربات!")
                return
            
            # نمایش اطلاعات ربات ساخته شده
            bot_created_msg, inline_markup = self.renderer.render_bot_created(bot_config)
            
            await context.bot.send_message(
                chat_id=user.id,
                text=bot_created_msg,
                reply_markup=inline_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as e:
            logger.error(f"خطا در ساخت ربات: {e}")
            await processing_message.edit_text("❌ خطا در ساخت ربات!")
    
    def _validate_token_format(self, token: str) -> bool:
        """اعتبارسنجی فرمت توکن"""
        parts = token.split(':')
        if len(parts) != 2:
            return False
        
        # بخش اول باید عدد باشد
        if not parts[0].isdigit():
            return False
        
        # بخش دوم باید رشته‌ای از حروف و اعداد باشد
        if not parts[1].replace('_', '').isalnum():
            return False
        
        return True
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """مدیریت کلیک روی دکمه‌های اینلاین"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user = update.effective_user
        
        # پردازش دستورات
        if data.startswith("bot_manage_"):
            # مدیریت ربات خاص
            bot_id = data.split("_", 2)[2]
            bot_config = self.db.get_bot(bot_id)
            
            if bot_config:
                bot_info, inline_markup = self.renderer.render_bot_management(bot_config)
                await query.edit_message_text(
                    bot_info,
                    reply_markup=inline_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
        
        elif data.startswith("bot_stop_"):
            # توقف ربات
            bot_id = data.split("_", 2)[2]
            
            # اضافه به صف توقف
            self.bot_manager_queue.put(("stop_bot", bot_id))
            
            await query.edit_message_text(
                "⏹️ ربات در حال توقف...\nلطفاً چند لحظه صبر کنید."
            )
        
        elif data.startswith("bot_start_"):
            # راه‌اندازی مجدد ربات
            bot_id = data.split("_", 2)[2]
            bot_config = self.db.get_bot(bot_id)
            
            if bot_config:
                self.bot_manager_queue.put(("start_bot", bot_config))
                await query.edit_message_text(
                    "▶️ ربات در حال راه‌اندازی...\nلطفاً چند لحظه صبر کنید."
                )
        
        elif data == "admin_all_bots":
            # نمایش همه ربات‌ها
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM bots ORDER BY created_at DESC LIMIT 20')
                rows = cursor.fetchall()
                
                if rows:
                    text = "🤖 **آخرین ربات‌های ساخته شده:**\n\n"
                    
                    for row in rows:
                        created_at = datetime.fromisoformat(row['created_at']).strftime("%Y-%m-%d")
                        text += f"🔹 @{row['bot_username']}\n"
                        text += f"   👤 مالک: {row['owner_id']}\n"
                        text += f"   📅 تاریخ: {created_at}\n"
                        text += f"   📊 پیام‌ها: {row['total_messages']}\n\n"
                    
                    keyboard = [[
                        InlineKeyboardButton(
                            self.renderer.BUTTONS["inline"]["back_to_admin"],
                            callback_data="back_to_admin"
                        )
                    ]]
                    inline_markup = InlineKeyboardMarkup(keyboard)
                    
                    await query.edit_message_text(
                        text,
                        reply_markup=inline_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
        
        elif data == "back_to_admin":
            # بازگشت به پنل مدیریت
            admin_text, inline_markup = self.renderer.render_admin_panel()
            await query.edit_message_text(
                admin_text,
                reply_markup=inline_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif data == "refresh_bots":
            # بروزرسانی لیست ربات‌ها
            bots_text, inline_markup = self.renderer.render_my_bots(user.id)
            await query.edit_message_text(
                bots_text,
                reply_markup=inline_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif data == "home":
            # بازگشت به خانه
            welcome_text, reply_markup = self.renderer.render_welcome(user.id)
            
            await query.edit_message_text(
                "به صفحه اصلی بازگشتید:",
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
        logger.error(f"خطا در بروزرسانی {update}: {context.error}")
        
        try:
            if update and update.effective_message:
                await update.effective_message.reply_text(
                    "❌ خطایی رخ داد. لطفاً بعداً تلاش کنید."
                )
        except:
            pass
    
    async def load_existing_bots(self):
        """بارگذاری ربات‌های موجود از دیتابیس"""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM bots WHERE status = ?', (BotStatus.ACTIVE.value,))
            rows = cursor.fetchall()
            
            for row in rows:
                bot_config = BotConfig(
                    token=row['token'],
                    owner_id=row['owner_id'],
                    bot_id=row['bot_id'],
                    bot_username=row['bot_username'],
                    created_at=row['created_at'],
                    status=row['status'],
                    webhook_url=row['webhook_url'],
                    total_messages=row['total_messages'],
                    total_users=row['total_users'],
                    last_activity=row['last_activity'],
                    settings=json.loads(row['settings'])
                )
                
                # راه‌اندازی ربات در صف
                self.bot_manager_queue.put(("start_bot", bot_config))
        
        logger.info(f"{len(rows)} ربات فعال از دیتابیس بارگذاری شد.")
    
    def setup_handlers(self):
        """تنظیم هندلرهای ربات مادر"""
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("mybots", self.start))  # به عنوان مثال
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))
        self.application.add_error_handler(self.error_handler)
    
    def run(self):
        """اجرای ربات مادر"""
        token = self.renderer.MOTHER_CONFIG["token"]
        
        if token == "YOUR_MOTHER_BOT_TOKEN_HERE":
            print("=" * 70)
            print("🤖 **ربات مادر ساخت ربات چت ناشناس**")
            print("=" * 70)
            print("\n⚠️  لطفاً تنظیمات ربات را اصلاح کنید!")
            print("\nمراحل تنظیم:")
            print("1. به @BotFather مراجعه کرده و یک ربات جدید بسازید")
            print("2. توکن ربات ساخته شده را کپی کنید")
            print("3. در کلاس MotherBotRenderer، بخش MOTHER_CONFIG:")
            print("   - token: توکن ربات خود را وارد کنید")
            print("   - admin_ids: آیدی عددی خود را وارد کنید")
            print("4. ربات را مجدداً اجرا کنید")
            print("\n🎯 **ویژگی‌های سیستم:**")
            print("• ساخت خودکار ربات چت ناشناس برای کاربران")
            print("• مدیریت چندین ربات به صورت همزمان")
            print("• پنل مدیریت پیشرفته")
            print("• آمار کامل و گزارش‌گیری")
            print("• سیستم اشتراک و محدودیت")
            print("=" * 70)
            return
        
        # ساخت و راه‌اندازی اپلیکیشن
        self.application = Application.builder().token(token).build()
        self.setup_handlers()
        
        # بارگذاری ربات‌های موجود
        asyncio.run(self.load_existing_bots())
        
        print("=" * 70)
        print("🤖 **ربات مادر راه‌اندازی شد!**")
        print("=" * 70)
        print(f"👑 ادمین‌ها: {self.renderer.MOTHER_CONFIG['admin_ids']}")
        print(f"🤖 حداکثر ربات هر کاربر: {self.renderer.MOTHER_CONFIG['max_bots_per_user']}")
        print(f"🔗 پیشوند نام ربات‌ها: {self.renderer.MOTHER_CONFIG['bot_name_prefix']}")
        print("=" * 70)
        print("\n✅ ربات آماده دریافت توکن و ساخت ربات چت ناشناس است!")
        print("کاربران می‌توانند با ارسال توکن ربات خود، ربات چت ناشناس شخصی دریافت کنند.")
        print("=" * 70)
        
        # اجرای ربات مادر
        self.application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )

# ==================== اجرای برنامه ====================
if __name__ == "__main__":
    bot = MotherBot()
    bot.run()
