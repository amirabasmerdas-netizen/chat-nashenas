#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات تلگرام چت ناشناس - تک فایل
این ربات پیام‌های ناشناس را دریافت و فقط به مالک نمایش می‌دهد
مالک می‌تواند پروفایل کاربران را مشاهده کند
"""

import logging
import json
from datetime import datetime
from typing import Dict, Any, Optional

# ==================== تنظیمات اولیه ====================
import os
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== تنظیمات ربات ====================
class BotConfig:
    """کلاس تنظیمات ربات"""
    
    # توکن ربات (از @BotFather دریافت شود)
    BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
    
    # آیدی عددی مالک ربات (از @userinfobot دریافت شود)
    OWNER_ID = 123456789  # جایگزین کن با آیدی واقعی مالک
    
    # آدرس وب هوک (برای سرور)
    WEBHOOK_URL = "https://yourdomain.com/webhook"  # در صورت استفاده از وب‌هوک
    
    # پورت برای اجرای محلی
    PORT = 8443
    
    # حالت رندر (webhook یا polling)
    USE_WEBHOOK = False  # اگر True باشد از وب‌هوک استفاده می‌کند
    
    # تنظیمات پیام‌ها
    WELCOME_MESSAGE = "👋 سلام! به ربات چت ناشناس خوش آمدید.\n\n" \
                      "شما می‌توانید پیام‌های ناشناس خود را برای مالک ربات ارسال کنید."
    
    ANONYMOUS_SENT_MESSAGE = "✅ پیام شما به صورت ناشناس ارسال شد."
    
    OWNER_NEW_MESSAGE = "📨 **پیام جدید از کاربر ناشناس**\n\n"
    
    # فایل ذخیره سازی داده‌ها
    DATA_FILE = "bot_data.json"

# ==================== مدیریت داده‌ها ====================
class DataManager:
    """مدیریت ذخیره و بازیابی داده‌های ربات"""
    
    def __init__(self, filename: str = BotConfig.DATA_FILE):
        self.filename = filename
        self.data = self._load_data()
    
    def _load_data(self) -> Dict[str, Any]:
        """بارگذاری داده‌ها از فایل"""
        try:
            with open(self.filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            # ساختار اولیه داده‌ها
            return {
                "users": {},
                "messages": [],
                "stats": {
                    "total_messages": 0,
                    "total_users": 0,
                    "last_message_time": None
                }
            }
        except Exception as e:
            logger.error(f"خطا در بارگذاری داده‌ها: {e}")
            return {
                "users": {},
                "messages": [],
                "stats": {
                    "total_messages": 0,
                    "total_users": 0,
                    "last_message_time": None
                }
            }
    
    def _save_data(self):
        """ذخیره داده‌ها در فایل"""
        try:
            with open(self.filename, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"خطا در ذخیره داده‌ها: {e}")
    
    def register_user(self, user_id: int, username: str, first_name: str, last_name: str = ""):
        """ثبت کاربر جدید"""
        if str(user_id) not in self.data["users"]:
            self.data["users"][str(user_id)] = {
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "join_date": datetime.now().isoformat(),
                "message_count": 0,
                "is_banned": False
            }
            self.data["stats"]["total_users"] = len(self.data["users"])
            self._save_data()
            return True
        return False
    
    def save_message(self, user_id: int, message_type: str, content: str, message_id: int = None):
        """ذخیره پیام در تاریخچه"""
        message_data = {
            "user_id": user_id,
            "type": message_type,  # text, photo, etc.
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "message_id": message_id
        }
        
        self.data["messages"].append(message_data)
        self.data["stats"]["total_messages"] += 1
        self.data["stats"]["last_message_time"] = datetime.now().isoformat()
        
        # افزایش تعداد پیام‌های کاربر
        if str(user_id) in self.data["users"]:
            self.data["users"][str(user_id)]["message_count"] += 1
        
        self._save_data()
        return message_data
    
    def get_user_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """دریافت اطلاعات کاربر"""
        return self.data["users"].get(str(user_id))
    
    def get_stats(self) -> Dict[str, Any]:
        """دریافت آمار ربات"""
        return self.data["stats"]
    
    def get_recent_messages(self, limit: int = 10) -> list:
        """دریافت آخرین پیام‌ها"""
        return self.data["messages"][-limit:] if self.data["messages"] else []

# ==================== رندر پیام‌ها ====================
class MessageRenderer:
    """کلاس رندر پیام‌ها و رابط کاربری"""
    
    def __init__(self, data_manager: DataManager):
        self.data_manager = data_manager
    
    def render_welcome_message(self, user: Any) -> tuple:
        """رندر پیام خوشآمدگویی"""
        welcome_text = BotConfig.WELCOME_MESSAGE
        
        # ایجاد کیبورد اصلی
        keyboard = [
            [KeyboardButton("📝 ارسال پیام ناشناس")],
            [KeyboardButton("ℹ️ راهنمای استفاده"), KeyboardButton("📊 آمار ربات")]
        ]
        
        if user.id == BotConfig.OWNER_ID:
            keyboard.append([KeyboardButton("👑 پنل مدیریت")])
        
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        return welcome_text, reply_markup
    
    def render_anonymous_message_to_owner(self, user_id: int, message_text: str) -> tuple:
        """رندر پیام ناشناس برای مالک"""
        user_info = self.data_manager.get_user_info(user_id)
        
        if user_info:
            username = user_info.get("username", "بدون نام کاربری")
            first_name = user_info.get("first_name", "ناشناس")
            last_name = user_info.get("last_name", "")
            
            user_display = f"@{username}" if username else f"{first_name} {last_name}".strip()
        else:
            user_display = "کارگر ناشناس"
        
        # متن پیام برای مالک
        message_for_owner = f"{BotConfig.OWNER_NEW_MESSAGE}"
        message_for_owner += f"👤 **فرستنده:** {user_display}\n"
        message_for_owner += f"🆔 **آیدی:** `{user_id}`\n"
        message_for_owner += f"📅 **زمان:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        message_for_owner += f"📝 **پیام:**\n{message_text}\n\n"
        message_for_owner += "👇 برای پاسخ یا مشاهده پروفایل از دکمه‌های زیر استفاده کنید:"
        
        # ایجاد اینلاین کیبورد
        keyboard = [
            [
                InlineKeyboardButton("👁️ مشاهده پروفایل", callback_data=f"profile_{user_id}"),
                InlineKeyboardButton("💬 پاسخ به کاربر", callback_data=f"reply_{user_id}")
            ],
            [
                InlineKeyboardButton("🚫 مسدود کردن کاربر", callback_data=f"ban_{user_id}"),
                InlineKeyboardButton("✅ تایید کاربر", callback_data=f"approve_{user_id}")
            ],
            [
                InlineKeyboardButton("📊 آمار کاربر", callback_data=f"stats_{user_id}"),
                InlineKeyboardButton("🗑️ حذف پیام", callback_data=f"delete_{message_text[:20]}")
            ]
        ]
        
        inline_markup = InlineKeyboardMarkup(keyboard)
        
        return message_for_owner, inline_markup
    
    def render_user_profile(self, user_id: int) -> tuple:
        """رندر پروفایل کاربر برای مالک"""
        user_info = self.data_manager.get_user_info(user_id)
        
        if not user_info:
            return "❌ کاربر یافت نشد.", None
        
        profile_text = "👤 **پروفایل کاربر**\n\n"
        profile_text += f"🆔 **آیدی:** `{user_id}`\n"
        profile_text += f"👤 **نام:** {user_info.get('first_name', '')} {user_info.get('last_name', '')}\n"
        
        username = user_info.get('username', '')
        profile_text += f"📱 **نام کاربری:** @{username}\n" if username else "📱 **نام کاربری:** ندارد\n"
        
        join_date = datetime.fromisoformat(user_info.get('join_date', datetime.now().isoformat()))
        profile_text += f"📅 **تاریخ عضویت:** {join_date.strftime('%Y-%m-%d %H:%M:%S')}\n"
        profile_text += f"📨 **تعداد پیام‌ها:** {user_info.get('message_count', 0)}\n"
        
        status = "✅ فعال" if not user_info.get('is_banned', False) else "🚫 مسدود شده"
        profile_text += f"🔰 **وضعیت:** {status}\n\n"
        
        profile_text += "👇 برای اقدام‌های بیشتر از دکمه‌های زیر استفاده کنید:"
        
        # ایجاد اینلاین کیبورد
        keyboard = [
            [
                InlineKeyboardButton("📩 ارسال پیام به کاربر", callback_data=f"msg_{user_id}"),
                InlineKeyboardButton("📨 تاریخچه پیام‌ها", callback_data=f"history_{user_id}")
            ],
            [
                InlineKeyboardButton("🚫 مسدود کردن", callback_data=f"ban_{user_id}") if not user_info.get('is_banned', False) 
                else InlineKeyboardButton("✅ آزاد کردن", callback_data=f"unban_{user_id}"),
                InlineKeyboardButton("📊 آمار کامل", callback_data=f"fullstats_{user_id}")
            ],
            [
                InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main"),
                InlineKeyboardButton("🏠 صفحه اصلی", callback_data="home")
            ]
        ]
        
        inline_markup = InlineKeyboardMarkup(keyboard)
        
        return profile_text, inline_markup
    
    def render_stats(self, for_owner: bool = False) -> str:
        """رندر آمار ربات"""
        stats = self.data_manager.get_stats()
        recent_msgs = self.data_manager.get_recent_messages(5)
        
        stats_text = "📊 **آمار ربات چت ناشناس**\n\n"
        stats_text += f"📨 **کل پیام‌ها:** {stats.get('total_messages', 0)}\n"
        stats_text += f"👥 **کل کاربران:** {stats.get('total_users', 0)}\n"
        
        if stats.get('last_message_time'):
            last_time = datetime.fromisoformat(stats['last_message_time'])
            stats_text += f"🕒 **آخرین پیام:** {last_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        
        if for_owner:
            stats_text += "\n📈 **آخرین فعالیت‌ها:**\n"
            for msg in recent_msgs[-5:]:
                user_info = self.data_manager.get_user_info(msg['user_id'])
                user_name = user_info.get('first_name', 'ناشناس') if user_info else 'ناشناس'
                time = datetime.fromisoformat(msg['timestamp']).strftime('%H:%M')
                stats_text += f"• {user_name}: {msg['content'][:30]}... ({time})\n"
        
        return stats_text
    
    def render_admin_panel(self) -> tuple:
        """رندر پنل مدیریت برای مالک"""
        admin_text = "👑 **پنل مدیریت ربات**\n\n"
        admin_text += "با استفاده از دکمه‌های زیر می‌توانید ربات را مدیریت کنید:\n"
        
        # ایجاد اینلاین کیبورد برای پنل مدیریت
        keyboard = [
            [
                InlineKeyboardButton("📊 آمار کامل", callback_data="admin_stats"),
                InlineKeyboardButton("📋 لیست کاربران", callback_data="user_list")
            ],
            [
                InlineKeyboardButton("📨 پیام همگانی", callback_data="broadcast"),
                InlineKeyboardButton("⚙️ تنظیمات", callback_data="settings")
            ],
            [
                InlineKeyboardButton("🔄 بروزرسانی ربات", callback_data="update_bot"),
                InlineKeyboardButton("📤 خروجی داده", callback_data="export_data")
            ],
            [
                InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main"),
                InlineKeyboardButton("🏠 صفحه اصلی", callback_data="home")
            ]
        ]
        
        inline_markup = InlineKeyboardMarkup(keyboard)
        
        return admin_text, inline_markup

# ==================== مدیریت ربات ====================
class AnonymousChatBot:
    """کلاس اصلی ربات چت ناشناس"""
    
    def __init__(self):
        self.data_manager = DataManager()
        self.renderer = MessageRenderer(self.data_manager)
        self.application = None
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """دستور /start"""
        user = update.effective_user
        
        # ثبت کاربر در سیستم
        self.data_manager.register_user(
            user.id, 
            user.username or "", 
            user.first_name, 
            user.last_name or ""
        )
        
        # رندر پیام خوشآمدگویی
        welcome_text, reply_markup = self.renderer.render_welcome_message(user)
        
        await update.message.reply_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """مدیریت پیام‌های متنی"""
        user = update.effective_user
        message_text = update.message.text
        
        # اگر کاربر مالک باشد
        if user.id == BotConfig.OWNER_ID:
            await self._handle_owner_message(update, context, message_text)
            return
        
        # اگر کاربر عادی باشد و پیام ارسال کرده
        if message_text == "📝 ارسال پیام ناشناس":
            await update.message.reply_text(
                "لطفا پیام ناشناس خود را تایپ کنید:",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 لغو")]], resize_keyboard=True)
            )
            context.user_data['waiting_for_anonymous_message'] = True
            return
        
        elif message_text == "🔙 لغو":
            welcome_text, reply_markup = self.renderer.render_welcome_message(user)
            await update.message.reply_text(
                "عملیات لغو شد.",
                reply_markup=reply_markup
            )
            context.user_data.pop('waiting_for_anonymous_message', None)
            return
        
        elif message_text == "ℹ️ راهنمای استفاده":
            help_text = "📖 **راهنمای استفاده از ربات**\n\n"
            help_text += "1. برای ارسال پیام ناشناس، روی دکمه 'ارسال پیام ناشناس' کلیک کنید.\n"
            help_text += "2. پیام خود را تایپ و ارسال کنید.\n"
            help_text += "3. پیام شما به صورت ناشناس برای مالک ربات ارسال می‌شود.\n"
            help_text += "4. مالک می‌تواند به پیام شما پاسخ دهد.\n\n"
            help_text += "⚠️ **توجه:** از ارسال محتوای نامناسب خودداری کنید."
            
            await update.message.reply_text(
                help_text,
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        elif message_text == "📊 آمار ربات":
            stats_text = self.renderer.render_stats()
            await update.message.reply_text(
                stats_text,
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        elif message_text == "👑 پنل مدیریت" and user.id == BotConfig.OWNER_ID:
            admin_text, inline_markup = self.renderer.render_admin_panel()
            await update.message.reply_text(
                admin_text,
                reply_markup=inline_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # اگر کاربر در حال ارسال پیام ناشناس است
        if context.user_data.get('waiting_for_anonymous_message', False):
            # ذخیره پیام
            self.data_manager.save_message(user.id, "text", message_text)
            
            # ارسال به مالک
            message_for_owner, inline_markup = self.renderer.render_anonymous_message_to_owner(
                user.id, message_text
            )
            
            try:
                await context.bot.send_message(
                    chat_id=BotConfig.OWNER_ID,
                    text=message_for_owner,
                    reply_markup=inline_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                
                # تایید به کاربر
                await update.message.reply_text(
                    BotConfig.ANONYMOUS_SENT_MESSAGE,
                    reply_markup=ReplyKeyboardMarkup(
                        [[KeyboardButton("📝 ارسال پیام جدید")], 
                         [KeyboardButton("🏠 صفحه اصلی")]],
                        resize_keyboard=True
                    )
                )
                
            except Exception as e:
                logger.error(f"خطا در ارسال پیام به مالک: {e}")
                await update.message.reply_text("❌ خطا در ارسال پیام. لطفا مجددا تلاش کنید.")
            
            context.user_data.pop('waiting_for_anonymous_message', None)
            return
        
        # پیام عادی
        welcome_text, reply_markup = self.renderer.render_welcome_message(user)
        await update.message.reply_text(
            "لطفا از دکمه‌های زیر استفاده کنید:",
            reply_markup=reply_markup
        )
    
    async def _handle_owner_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str):
        """مدیریت پیام‌های مالک"""
        if message_text == "👑 پنل مدیریت":
            admin_text, inline_markup = self.renderer.render_admin_panel()
            await update.message.reply_text(
                admin_text,
                reply_markup=inline_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif message_text == "📊 آمار ربات":
            stats_text = self.renderer.render_stats(for_owner=True)
            await update.message.reply_text(
                stats_text,
                parse_mode=ParseMode.MARKDOWN
            )
        
        else:
            # اگر مالک در حال پاسخ به کاربر است
            if 'replying_to_user' in context.user_data:
                target_user_id = context.user_data['replying_to_user']
                
                try:
                    # ارسال پیام به کاربر
                    await context.bot.send_message(
                        chat_id=target_user_id,
                        text=f"📩 **پاسخ از مدیریت:**\n\n{message_text}"
                    )
                    
                    await update.message.reply_text(
                        f"✅ پاسخ شما به کاربر {target_user_id} ارسال شد."
                    )
                    
                    # ذخیره پیام
                    self.data_manager.save_message(
                        BotConfig.OWNER_ID, 
                        "text", 
                        f"پاسخ به کاربر {target_user_id}: {message_text}"
                    )
                    
                except Exception as e:
                    logger.error(f"خطا در ارسال پاسخ: {e}")
                    await update.message.reply_text(
                        f"❌ خطا در ارسال پاسخ. ممکن است کاربر ربات را بلاک کرده باشد."
                    )
                
                context.user_data.pop('replying_to_user', None)
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """مدیریت کلیک روی دکمه‌های اینلاین"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user = update.effective_user
        
        # بررسی دسترسی (فقط مالک)
        if user.id != BotConfig.OWNER_ID:
            await query.edit_message_text(
                "⛔ شما دسترسی به این بخش را ندارید."
            )
            return
        
        if data.startswith("profile_"):
            # مشاهده پروفایل کاربر
            user_id = int(data.split("_")[1])
            profile_text, inline_markup = self.renderer.render_user_profile(user_id)
            
            await query.edit_message_text(
                profile_text,
                reply_markup=inline_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif data.startswith("reply_"):
            # پاسخ به کاربر
            user_id = int(data.split("_")[1])
            context.user_data['replying_to_user'] = user_id
            
            await query.edit_message_text(
                f"📝 در حال پاسخ به کاربر {user_id}\nلطفا پیام خود را تایپ کنید:"
            )
        
        elif data.startswith("ban_"):
            # مسدود کردن کاربر
            user_id = int(data.split("_")[1])
            user_info = self.data_manager.get_user_info(user_id)
            
            if user_info:
                user_info['is_banned'] = True
                self.data_manager._save_data()
                
                await query.edit_message_text(
                    f"✅ کاربر {user_id} با موفقیت مسدود شد."
                )
        
        elif data.startswith("unban_"):
            # آزاد کردن کاربر
            user_id = int(data.split("_")[1])
            user_info = self.data_manager.get_user_info(user_id)
            
            if user_info:
                user_info['is_banned'] = False
                self.data_manager._save_data()
                
                await query.edit_message_text(
                    f"✅ کاربر {user_id} با موفقیت آزاد شد."
                )
        
        elif data == "admin_stats":
            # آمار کامل برای مالک
            stats_text = self.renderer.render_stats(for_owner=True)
            
            keyboard = [
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_admin")],
                [InlineKeyboardButton("🏠 صفحه اصلی", callback_data="home")]
            ]
            inline_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                stats_text,
                reply_markup=inline_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif data == "back_to_admin" or data == "back_to_main":
            # بازگشت به پنل مدیریت
            admin_text, inline_markup = self.renderer.render_admin_panel()
            await query.edit_message_text(
                admin_text,
                reply_markup=inline_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif data == "home":
            # بازگشت به صفحه اصلی
            welcome_text, reply_markup = self.renderer.render_welcome_message(user)
            
            await query.edit_message_text(
                welcome_text,
                parse_mode=ParseMode.MARKDOWN
            )
            # توجه: برای کیبورد ریپلای باید پیام جدید ارسال کرد
            await context.bot.send_message(
                chat_id=user.id,
                text="به صفحه اصلی بازگشتید:",
                reply_markup=reply_markup
            )
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """مدیریت خطاها"""
        logger.error(f"خطا در بروزرسانی {update}: {context.error}")
        
        if update and update.effective_user:
            try:
                await update.effective_message.reply_text(
                    "❌ خطایی در پردازش درخواست شما رخ داده است. لطفا مجددا تلاش کنید."
                )
            except:
                pass
    
    def setup_handlers(self):
        """تنظیم هندلرهای ربات"""
        # دستورات
        self.application.add_handler(CommandHandler("start", self.start))
        
        # پیام‌های متنی
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # کلیک روی دکمه‌های اینلاین
        self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))
        
        # هندلر خطا
        self.application.add_error_handler(self.error_handler)
    
    async def setup_webhook(self):
        """تنظیم وب‌هوک"""
        await self.application.bot.set_webhook(
            url=f"{BotConfig.WEBHOOK_URL}/{BotConfig.BOT_TOKEN}",
            drop_pending_updates=True
        )
        logger.info("وب‌هوک تنظیم شد.")
    
    def run(self):
        """اجرای ربات"""
        # ساخت اپلیکیشن
        self.application = Application.builder().token(BotConfig.BOT_TOKEN).build()
        
        # تنظیم هندلرها
        self.setup_handlers()
        
        if BotConfig.USE_WEBHOOK:
            # اجرا با وب‌هوک
            self.application.run_webhook(
                listen="0.0.0.0",
                port=BotConfig.PORT,
                url_path=BotConfig.BOT_TOKEN,
                webhook_url=f"{BotConfig.WEBHOOK_URL}/{BotConfig.BOT_TOKEN}"
            )
        else:
            # اجرا با پولینگ
            self.application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

# ==================== اجرای ربات ====================
if __name__ == "__main__":
    print("=" * 50)
    print("ربات چت ناشناس تلگرام")
    print("نویسنده: تیم توسعه")
    print("=" * 50)
    
    # هشدار در مورد تنظیمات
    if BotConfig.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n⚠️  هشدار: لطفا تنظیمات ربات را اصلاح کنید!")
        print("1. توکن ربات خود را از @BotFather دریافت کنید.")
        print("2. آیدی عددی خود را از @userinfobot دریافت کنید.")
        print("3. مقادیر را در بخش BotConfig اصلاح کنید.")
        print("\nمقادیر فعلی:")
        print(f"   توکن ربات: {BotConfig.BOT_TOKEN}")
        print(f"   آیدی مالک: {BotConfig.OWNER_ID}")
        print("\nپس از اصلاح تنظیمات، ربات را مجددا اجرا کنید.")
    else:
        print(f"\n✅ ربات با توکن: {BotConfig.BOT_TOKEN[:10]}... راه‌اندازی می‌شود")
        print(f"✅ مالک ربات: {BotConfig.OWNER_ID}")
        print(f"✅ حالت اجرا: {'Webhook' if BotConfig.USE_WEBHOOK else 'Polling'}")
        print("\nدر حال راه‌اندازی ربات...")
        
        # ایجاد و اجرای ربات
        bot = AnonymousChatBot()
        bot.run()
