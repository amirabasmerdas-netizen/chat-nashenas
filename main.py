#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات تلگرام چت ناشناس - نسخه کامل با polling خودکار برای ربات‌های فرزند
"""

import os
import json
import logging
import asyncio
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any, Set

from flask import Flask, request, jsonify
import telebot
from telebot import types
from telebot.async_telebot import AsyncTeleBot
import aiohttp

# تنظیمات لاگ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== کلاس مدیریت مرحله‌ها ==========
class StepHandlerManager:
    """مدیریت مراحل ثبت‌نام و تعاملات چند مرحله‌ای"""
    
    def __init__(self):
        self.user_steps: Dict[int, Dict] = {}
        self.user_data: Dict[int, Dict] = {}
    
    def set_step(self, user_id: int, step: str, data: Dict = None):
        """تنظیم مرحله کاربر"""
        if user_id not in self.user_steps:
            self.user_steps[user_id] = {}
        
        self.user_steps[user_id]['current_step'] = step
        
        if data:
            if user_id not in self.user_data:
                self.user_data[user_id] = {}
            self.user_data[user_id].update(data)
    
    def get_step(self, user_id: int) -> Optional[str]:
        """دریافت مرحله فعلی کاربر"""
        if user_id in self.user_steps:
            return self.user_steps[user_id].get('current_step')
        return None
    
    def get_data(self, user_id: int, key: str = None):
        """دریافت داده کاربر"""
        if user_id in self.user_data:
            if key:
                return self.user_data[user_id].get(key)
            return self.user_data[user_id]
        return None
    
    def clear_step(self, user_id: int):
        """پاک کردن مرحله کاربر"""
        if user_id in self.user_steps:
            del self.user_steps[user_id]
        if user_id in self.user_data:
            del self.user_data[user_id]


# ========== کلاس مدیریت ربات‌های فرزند ==========
class ChildBotManager:
    """مدیریت polling ربات‌های فرزند"""
    
    def __init__(self):
        self.child_bots: Dict[str, Dict] = {}  # username -> bot_data
        self.polling_tasks: Dict[str, threading.Thread] = {}
        self.polling_active: Dict[str, bool] = {}
    
    def add_bot(self, bot_data: Dict):
        """افزودن ربات فرزند"""
        username = bot_data['username']
        self.child_bots[username] = bot_data
        self.polling_active[username] = True
        
        # شروع polling در thread جداگانه
        thread = threading.Thread(
            target=self._start_bot_polling,
            args=(bot_data,),
            daemon=True,
            name=f"bot_{username}"
        )
        self.polling_tasks[username] = thread
        thread.start()
        
        logger.info(f"ربات فرزند @{username} اضافه شد و polling شروع شد")
    
    def _start_bot_polling(self, bot_data: Dict):
        """شروع polling برای یک ربات فرزند"""
        bot = bot_data['bot_instance']
        username = bot_data['username']
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # حذف webhook قبلی (اگر وجود دارد)
            loop.run_until_complete(bot.remove_webhook())
            
            logger.info(f"شروع polling برای ربات @{username}")
            
            # شروع polling
            loop.run_until_complete(bot.polling(
                non_stop=True,
                timeout=60,
                skip_pending=True
            ))
        except Exception as e:
            logger.error(f"خطا در polling ربات @{username}: {e}")
        finally:
            loop.close()
    
    def remove_bot(self, username: str):
        """حذف ربات فرزند"""
        if username in self.polling_active:
            self.polling_active[username] = False
        
        if username in self.child_bots:
            del self.child_bots[username]
        
        if username in self.polling_tasks:
            # صبر کردن برای پایان thread (اختیاری)
            time.sleep(1)
            # thread به صورت daemon است، پس خودش بسته می‌شود
        
        logger.info(f"ربات فرزند @{username} حذف شد")
    
    def get_bot(self, username: str) -> Optional[Dict]:
        """دریافت اطلاعات ربات فرزند"""
        return self.child_bots.get(username)
    
    def stop_all(self):
        """توقف تمام ربات‌های فرزند"""
        for username in list(self.polling_active.keys()):
            self.polling_active[username] = False
        
        logger.info("تمام ربات‌های فرزند متوقف شدند")


# ========== کلاس اصلی ربات مادر ==========
class AnonymousChatBot:
    def __init__(self, token: str, webhook_url: str = None, port: int = 10000):
        """
        مقداردهی اولیه ربات مادر
        
        Args:
            token: توکن ربات مادر
            webhook_url: آدرس وب هوک
            port: پورت برای اجرای سرور
        """
        self.master_token = token
        self.bot = AsyncTeleBot(token)
        self.webhook_url = webhook_url
        self.port = port
        
        # مدیر مراحل
        self.step_manager = StepHandlerManager()
        
        # مدیر ربات‌های فرزند
        self.child_manager = ChildBotManager()
        
        # دیکشنری برای ذخیره ربات‌های کاربران
        self.user_bots: Dict[int, List[Dict]] = {}
        
        # دیکشنری برای نگاشت چت‌ها
        self.chat_mapping: Dict[int, int] = {}
        
        # کاربران مسدود شده
        self.blocked_users: Set[Tuple[int, str]] = set()  # (user_id, bot_username)
        
        # تنظیم هندلرها
        self.setup_handlers()
        self.setup_callback_handlers()
        
        # تنظیمات رندر
        self.setup_render_config()
        
        # Flask app برای وب هوک
        self.app = Flask(__name__)
        self.setup_flask_routes()
    
    def setup_render_config(self):
        """تنظیمات رندر"""
        self.render_config = {
            'welcome_message': "🎭 به ربات چت ناشناس خوش آمدید!\n\n"
                              "با این ربات می‌توانید ربات ناشناس خود را ایجاد کنید.\n\n"
                              "دستورات:\n"
                              "/start - شروع کار\n"
                              "/addbot - ساخت ربات جدید\n"
                              "/mybots - ربات‌های من\n"
                              "/help - راهنمایی",
            
            'add_bot_instructions': "🤖 **مراحل ساخت ربات ناشناس:**\n\n"
                                   "1. به @BotFather در تلگرام بروید\n"
                                   "2. دستور `/newbot` را ارسال کنید\n"
                                   "3. برای ربات خود نام انتخاب کنید\n"
                                   "4. یک username منحصر به فرد انتخاب کنید\n"
                                   "5. توکن دریافتی را برای من ارسال کنید\n\n"
                                   "⚠️ **توجه:**\n"
                                   "• مالک ربات شما خواهید بود\n"
                                   "• فقط شما پیام‌ها را می‌بینید\n"
                                   "• کاربران از طریق username ربات شما پیام می‌فرستند",
            
            'bot_added_success': "✅ **ربات شما ساخته شد!**\n\n"
                                "ربات شما آماده دریافت پیام‌های ناشناس است.\n"
                                "کاربران می‌توانند با جستجوی @{} در تلگرام، با شما چت ناشناس داشته باشند.",
            
            'no_bots_found': "🤖 شما هنوز هیچ رباتی نساخته‌اید.\n"
                            "از دستور /addbot استفاده کنید.",
            
            'bot_list': "📋 **ربات‌های شما:**\n\n",
            
            'message_received': "📩 **پیام ناشناس جدید**\n\n",
            
            'view_profile_btn': "👤 مشاهده پروفایل",
            'reply_btn': "↪️ پاسخ",
            'block_btn': "🚫 مسدود",
            'unblock_btn': "✅ آزاد کردن",
            'delete_bot_btn': "🗑 حذف ربات",
            'back_btn': "🔙 بازگشت",
            
            'help_message': "📚 **راهنمای استفاده:**\n\n"
                           "**امکانات:**\n"
                           "• ساخت چندین ربات ناشناس\n"
                           "• مشاهده پیام‌ها فقط توسط مالک\n"
                           "• پاسخ به پیام‌های دریافتی\n"
                           "• مسدود کردن کاربران مزاحم\n"
                           "• مشاهده پروفایل فرستنده\n\n"
                           "**دستورات:**\n"
                           "/start - شروع\n"
                           "/addbot - ساخت ربات جدید\n"
                           "/mybots - لیست ربات‌ها\n"
                           "/help - این راهنما",
            
            'enter_token': "🔑 لطفاً توکن ربات خود را ارسال کنید:",
            'invalid_token': "❌ توکن نامعتبر است!\nلطفاً توکن صحیح را ارسال کنید.",
            'processing_token': "⏳ در حال ساخت ربات...",
            'enter_reply': "✍️ لطفاً پاسخ خود را ارسال کنید:",
            'reply_sent': "✅ پاسخ شما ارسال شد.",
            'user_blocked': "✅ کاربر مسدود شد.",
            'user_unblocked': "✅ کاربر آزاد شد.",
            'bot_deleted': "🗑 ربات حذف شد.",
            'error_occurred': "❌ خطایی رخ داد.",
            'no_permission': "⛔ شما دسترسی ندارید.",
            'user_not_found': "❌ کاربر یافت نشد.",
            'bot_not_found': "❌ ربات یافت نشد.",
            'already_blocked': "⚠️ کاربر قبلاً مسدود شده.",
            'not_blocked': "⚠️ کاربر مسدود نیست."
        }
    
    def setup_flask_routes(self):
        """تنظیم مسیرهای Flask"""
        
        @self.app.route('/')
        def index():
            return """
            <!DOCTYPE html>
            <html>
            <head>
                <title>ربات چت ناشناس</title>
                <meta charset="utf-8">
                <style>
                    body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
                    .container { max-width: 800px; margin: 0 auto; }
                    h1 { color: #333; }
                    .status { background: #4CAF50; color: white; padding: 10px; border-radius: 5px; }
                    .info { background: #f8f9fa; padding: 20px; border-radius: 10px; margin: 20px 0; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>🤖 ربات چت ناشناس</h1>
                    <div class="status">✅ در حال اجرا</div>
                    <div class="info">
                        <p>این سرویس برای ربات تلگرام چت ناشناس ایجاد شده است.</p>
                        <p>ربات اصلی: @{} (با دستور /start شروع کنید)</p>
                        <p>تعداد ربات‌های فرزند فعال: {}</p>
                    </div>
                    <p><a href="https://t.me/{}" target="_blank">شروع گفتگو با ربات</a></p>
                </div>
            </body>
            </html>
            """.format(
                (self.bot.get_me() if hasattr(self.bot, 'get_me') else 'ربات'),
                len(self.child_manager.child_bots),
                (self.bot.get_me().username if hasattr(self.bot, 'get_me') else '')
            )
        
        @self.app.route('/webhook/master', methods=['POST'])
        def master_webhook():
            """وب هوک ربات مادر"""
            if request.headers.get('content-type') == 'application/json':
                json_string = request.get_data().decode('utf-8')
                update = types.Update.de_json(json_string)
                
                # پردازش آپدیت
                asyncio.run(self.process_update(update))
                
                return jsonify({"status": "ok"}), 200
            return jsonify({"error": "Invalid content type"}), 403
        
        @self.app.route('/health', methods=['GET'])
        def health_check():
            """بررسی سلامت"""
            return jsonify({
                "status": "healthy",
                "service": "anonymous-chat-bot",
                "master_bot": "active",
                "child_bots": len(self.child_manager.child_bots),
                "timestamp": datetime.now().isoformat()
            }), 200
        
        @self.app.route('/api/stats', methods=['GET'])
        def get_stats():
            """آمار سرویس"""
            return jsonify({
                "total_users": len(self.user_bots),
                "total_child_bots": len(self.child_manager.child_bots),
                "blocked_users": len(self.blocked_users),
                "active_polling_threads": len([t for t in threading.enumerate() if 'bot_' in t.name])
            }), 200
    
    async def process_update(self, update):
        """پردازش آپدیت دریافتی"""
        await self.bot.process_new_updates([update])
    
    def setup_handlers(self):
        """تنظیم هندلرهای ربات مادر"""
        
        @self.bot.message_handler(commands=['start'])
        async def start_handler(message):
            """هندلر دستور /start"""
            user_id = message.from_user.id
            first_name = message.from_user.first_name or "کاربر"
            
            welcome_msg = f"سلام {first_name}!\n\n"
            welcome_msg += self.render_config['welcome_message']
            
            # ایجاد کیبورد اصلی
            markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
            btn1 = types.KeyboardButton("➕ ساخت ربات جدید")
            btn2 = types.KeyboardButton("📋 ربات‌های من")
            btn3 = types.KeyboardButton("ℹ️ راهنمایی")
            markup.add(btn1, btn2, btn3)
            
            await self.bot.send_message(
                message.chat.id,
                welcome_msg,
                reply_markup=markup,
                parse_mode='Markdown'
            )
            
            # پاک کردن مرحله قبلی
            self.step_manager.clear_step(user_id)
        
        @self.bot.message_handler(commands=['addbot', 'newbot'])
        async def add_bot_handler(message):
            """هندلر افزودن ربات جدید"""
            user_id = message.from_user.id
            
            instructions = self.render_config['add_bot_instructions']
            
            await self.bot.send_message(
                message.chat.id,
                instructions,
                parse_mode='Markdown'
            )
            
            # درخواست توکن
            await self.bot.send_message(
                message.chat.id,
                self.render_config['enter_token']
            )
            
            # تنظیم مرحله کاربر
            self.step_manager.set_step(user_id, 'awaiting_token')
        
        @self.bot.message_handler(commands=['mybots', 'list'])
        async def my_bots_handler(message):
            """هندلر مشاهده ربات‌های کاربر"""
            user_id = message.from_user.id
            
            if user_id not in self.user_bots or not self.user_bots[user_id]:
                await self.bot.send_message(
                    message.chat.id,
                    self.render_config['no_bots_found']
                )
                return
            
            bot_list = self.render_config['bot_list']
            user_bots_info = self.user_bots[user_id]
            
            for idx, bot_info in enumerate(user_bots_info, 1):
                username = bot_info.get('username', 'نامشخص')
                status = "✅ فعال" if bot_info.get('active', True) else "❌ غیرفعال"
                created = bot_info.get('created_at', 'نامشخص')
                
                bot_list += f"**{idx}. @{username}**\n"
                bot_list += f"   وضعیت: {status}\n"
                bot_list += f"   ایجاد: {created}\n\n"
            
            # ایجاد اینلاین کیبورد برای مدیریت
            markup = types.InlineKeyboardMarkup(row_width=2)
            
            for idx, bot_info in enumerate(user_bots_info, 1):
                username = bot_info['username']
                btn = types.InlineKeyboardButton(
                    f"@{username}",
                    callback_data=f"manage_{username}"
                )
                markup.add(btn)
            
            await self.bot.send_message(
                message.chat.id,
                bot_list,
                reply_markup=markup,
                parse_mode='Markdown'
            )
        
        @self.bot.message_handler(commands=['help'])
        async def help_handler(message):
            """هندلر راهنمایی"""
            await self.bot.send_message(
                message.chat.id,
                self.render_config['help_message'],
                parse_mode='Markdown'
            )
        
        @self.bot.message_handler(commands=['stats'])
        async def stats_handler(message):
            """هندلر آمار"""
            user_id = message.from_user.id
            
            # فقط برای توسعه‌دهنده
            # if user_id != YOUR_USER_ID:  # می‌توانید ID خود را اینجا قرار دهید
            #     return
            
            stats_text = "📊 **آمار سیستم:**\n\n"
            stats_text += f"تعداد کاربران: {len(self.user_bots)}\n"
            stats_text += f"تعداد ربات‌های فرزند: {len(self.child_manager.child_bots)}\n"
            stats_text += f"کاربران مسدود شده: {len(self.blocked_users)}\n"
            stats_text += f"Thread های فعال: {threading.active_count()}\n"
            
            await self.bot.send_message(
                message.chat.id,
                stats_text,
                parse_mode='Markdown'
            )
        
        @self.bot.message_handler(func=lambda message: True)
        async def text_handler(message):
            """هندلر پیام‌های متنی"""
            user_id = message.from_user.id
            text = message.text
            chat_id = message.chat.id
            
            # بررسی مرحله کاربر
            current_step = self.step_manager.get_step(user_id)
            
            if current_step == 'awaiting_token':
                # پردازش توکن دریافتی
                await self.process_token_step(message)
                return
            
            elif current_step == 'awaiting_reply':
                # پردازش پاسخ کاربر
                data = self.step_manager.get_data(user_id)
                if data:
                    target_user_id = data.get('target_user_id')
                    bot_username = data.get('bot_username')
                    await self.process_reply_step(message, target_user_id, bot_username)
                self.step_manager.clear_step(user_id)
                return
            
            # پردازش دکمه‌های کیبورد
            if text == "➕ ساخت ربات جدید" or text == "ربات جدید":
                await add_bot_handler(message)
            elif text == "📋 ربات‌های من" or text == "ربات‌های من":
                await my_bots_handler(message)
            elif text == "ℹ️ راهنمایی" or text == "راهنمایی":
                await help_handler(message)
            else:
                # اگر کاربر توکن ارسال کرده اما مرحله تنظیم نشده
                if text.startswith('') and len(text) > 30:
                    # ممکن است توکن باشد
                    await self.bot.send_message(
                        chat_id,
                        "اگر می‌خواهید ربات جدیدی اضافه کنید، از دکمه '➕ ساخت ربات جدید' استفاده کنید."
                    )
                else:
                    await self.bot.send_message(
                        chat_id,
                        "لطفاً از دکمه‌های منو یا دستورات استفاده کنید.\n"
                        "برای شروع /start را ارسال کنید."
                    )
    
    async def process_token_step(self, message):
        """پردازش مرحله دریافت توکن"""
        user_id = message.from_user.id
        token = message.text.strip()
        chat_id = message.chat.id
        
        # ارسال پیام پردازش
        processing_msg = await self.bot.send_message(
            chat_id,
            self.render_config['processing_token']
        )
        
        # اعتبارسنجی اولیه توکن
        if not token or len(token) < 30:
            await self.bot.edit_message_text(
                self.render_config['invalid_token'],
                chat_id,
                processing_msg.message_id
            )
            self.step_manager.clear_step(user_id)
            return
        
        try:
            # ایجاد ربات جدید با توکن کاربر
            user_bot = AsyncTeleBot(token)
            
            # بررسی صحت توکن
            bot_info = await user_bot.get_me()
            bot_username = bot_info.username
            
            # بررسی اینکه ربات قبلاً ساخته نشده باشد
            if user_id not in self.user_bots:
                self.user_bots[user_id] = []
            
            for existing_bot in self.user_bots[user_id]:
                if existing_bot.get('username') == bot_username:
                    await self.bot.edit_message_text(
                        f"⚠️ ربات @{bot_username} قبلاً اضافه شده است.",
                        chat_id,
                        processing_msg.message_id
                    )
                    self.step_manager.clear_step(user_id)
                    return
            
            # ذخیره اطلاعات ربات
            bot_data = {
                'bot_instance': user_bot,
                'token': token[:10] + '...',  # فقط بخشی از توکن ذخیره شود
                'username': bot_username,
                'owner_id': user_id,
                'active': True,
                'created_at': datetime.now().strftime('%Y/%m/%d %H:%M'),
                'full_token': token  # ذخیره کامل توکن برای استفاده
            }
            
            self.user_bots[user_id].append(bot_data)
            
            # راه‌اندازی ربات فرزند
            await self.setup_user_bot(bot_data)
            
            # اضافه کردن به مدیر ربات‌های فرزند برای polling
            self.child_manager.add_bot(bot_data)
            
            # پیام موفقیت
            success_msg = self.render_config['bot_added_success'].format(bot_username)
            success_msg += f"\n\n📊 **اطلاعات ربات:**\n"
            success_msg += f"• نام: @{bot_username}\n"
            success_msg += f"• مالک: شما\n"
            success_msg += f"• وضعیت: فعال ✅\n"
            success_msg += f"• زمان ایجاد: {datetime.now().strftime('%H:%M:%S')}\n\n"
            success_msg += "📨 **نحوه استفاده:**\n"
            success_msg += f"کاربران می‌توانند @{bot_username} را در تلگرام جستجو کنند\n"
            success_msg += "و به صورت ناشناس برای شما پیام ارسال کنند."
            
            await self.bot.edit_message_text(
                success_msg,
                chat_id,
                processing_msg.message_id,
                parse_mode='Markdown'
            )
            
            # ارسال یک پیام تست به مالک از ربات جدید
            try:
                test_msg = "🤖 **ربات شما فعال شد!**\n\n"
                test_msg += "این یک پیام تست از ربات شماست.\n"
                test_msg += "کاربران می‌توانند از این پس با شما چت ناشناس داشته باشند."
                
                await user_bot.send_message(user_id, test_msg, parse_mode='Markdown')
            except Exception as e:
                logger.warning(f"نتوانستم پیام تست به مالک ارسال کنم: {e}")
            
        except Exception as e:
            logger.error(f"خطا در ایجاد ربات کاربر: {e}")
            error_msg = f"❌ **خطا در ایجاد ربات:**\n\n{str(e)[:200]}"
            
            if "409" in str(e):
                error_msg += "\n\n⚠️ ممکن است ربات با این توکن قبلاً ساخته شده باشد."
            elif "401" in str(e):
                error_msg += "\n\n⚠️ توکن نامعتبر است. لطفاً توکن صحیح را وارد کنید."
            
            await self.bot.edit_message_text(
                error_msg,
                chat_id,
                processing_msg.message_id,
                parse_mode='Markdown'
            )
        
        # پاک کردن مرحله
        self.step_manager.clear_step(user_id)
    
    def setup_callback_handlers(self):
        """تنظیم هندلرهای callback"""
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('reply_'))
        async def reply_callback_handler(call):
            """هندلر پاسخ به پیام"""
            try:
                data_parts = call.data.split('_')
                if len(data_parts) < 3:
                    await self.bot.answer_callback_query(call.id, "خطا در پردازش")
                    return
                
                target_user_id = int(data_parts[1])
                bot_username = data_parts[2]
                
                await self.bot.answer_callback_query(call.id, "آماده دریافت پاسخ...")
                
                # تنظیم مرحله برای دریافت پاسخ
                self.step_manager.set_step(
                    call.from_user.id,
                    'awaiting_reply',
                    {
                        'target_user_id': target_user_id,
                        'bot_username': bot_username
                    }
                )
                
                # درخواست پاسخ
                await self.bot.send_message(
                    call.from_user.id,
                    f"✍️ **پاسخ به کاربر با آیدی {target_user_id}**\n\n"
                    "لطفاً پاسخ خود را ارسال کنید:",
                    parse_mode='Markdown'
                )
                
            except Exception as e:
                logger.error(f"خطا در reply callback: {e}")
                await self.bot.answer_callback_query(call.id, "خطا!")
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('block_'))
        async def block_callback_handler(call):
            """هندلر مسدود کردن کاربر"""
            try:
                data_parts = call.data.split('_')
                if len(data_parts) < 3:
                    await self.bot.answer_callback_query(call.id, "خطا")
                    return
                
                target_user_id = int(data_parts[1])
                bot_username = data_parts[2]
                owner_id = call.from_user.id
                
                # بررسی مالکیت
                user_bots = self.user_bots.get(owner_id, [])
                user_has_bot = any(bot['username'] == bot_username for bot in user_bots)
                
                if not user_has_bot:
                    await self.bot.answer_callback_query(call.id, self.render_config['no_permission'])
                    return
                
                # مسدود کردن کاربر
                self.blocked_users.add((target_user_id, bot_username))
                
                await self.bot.answer_callback_query(call.id, self.render_config['user_blocked'])
                
                # اطلاع به مالک
                await self.bot.send_message(
                    owner_id,
                    f"✅ کاربر با آیدی `{target_user_id}` در ربات @{bot_username} مسدود شد.",
                    parse_mode='Markdown'
                )
                
            except Exception as e:
                logger.error(f"خطا در block callback: {e}")
                await self.bot.answer_callback_query(call.id, self.render_config['error_occurred'])
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('unblock_'))
        async def unblock_callback_handler(call):
            """هندلر آزاد کردن کاربر"""
            try:
                data_parts = call.data.split('_')
                if len(data_parts) < 3:
                    await self.bot.answer_callback_query(call.id, "خطا")
                    return
                
                target_user_id = int(data_parts[1])
                bot_username = data_parts[2]
                owner_id = call.from_user.id
                
                # بررسی مالکیت
                user_bots = self.user_bots.get(owner_id, [])
                user_has_bot = any(bot['username'] == bot_username for bot in user_bots)
                
                if not user_has_bot:
                    await self.bot.answer_callback_query(call.id, self.render_config['no_permission'])
                    return
                
                # آزاد کردن کاربر
                self.blocked_users.discard((target_user_id, bot_username))
                
                await self.bot.answer_callback_query(call.id, self.render_config['user_unblocked'])
                
                await self.bot.send_message(
                    owner_id,
                    f"✅ کاربر با آیدی `{target_user_id}` در ربات @{bot_username} آزاد شد.",
                    parse_mode='Markdown'
                )
                
            except Exception as e:
                logger.error(f"خطا در unblock callback: {e}")
                await self.bot.answer_callback_query(call.id, self.render_config['error_occurred'])
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('delete_'))
        async def delete_bot_callback_handler(call):
            """هندلر حذف ربات"""
            try:
                data_parts = call.data.split('_')
                if len(data_parts) < 2:
                    await self.bot.answer_callback_query(call.id, "خطا")
                    return
                
                bot_username = data_parts[1]
                owner_id = call.from_user.id
                
                # حذف ربات از لیست کاربر
                if owner_id in self.user_bots:
                    self.user_bots[owner_id] = [
                        bot for bot in self.user_bots[owner_id] 
                        if bot.get('username') != bot_username
                    ]
                
                # حذف از مدیر ربات‌های فرزند
                self.child_manager.remove_bot(bot_username)
                
                # حذف کاربران مسدود شده مرتبط
                self.blocked_users = {
                    (uid, uname) for (uid, uname) in self.blocked_users 
                    if uname != bot_username
                }
                
                await self.bot.answer_callback_query(call.id, self.render_config['bot_deleted'])
                
                await self.bot.send_message(
                    owner_id,
                    f"🗑 ربات @{bot_username} با موفقیت حذف شد.",
                    parse_mode='Markdown'
                )
                
            except Exception as e:
                logger.error(f"خطا در delete callback: {e}")
                await self.bot.answer_callback_query(call.id, self.render_config['error_occurred'])
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('manage_'))
        async def manage_bot_callback_handler(call):
            """هندلر مدیریت ربات"""
            try:
                bot_username = call.data.split('_')[1]
                owner_id = call.from_user.id
                
                # بررسی مالکیت
                user_bots = self.user_bots.get(owner_id, [])
                target_bot = None
                
                for bot in user_bots:
                    if bot['username'] == bot_username:
                        target_bot = bot
                        break
                
                if not target_bot:
                    await self.bot.answer_callback_query(call.id, self.render_config['bot_not_found'])
                    return
                
                # ایجاد منوی مدیریت
                markup = types.InlineKeyboardMarkup(row_width=2)
                
                # دکمه‌های مدیریت
                delete_btn = types.InlineKeyboardButton(
                    self.render_config['delete_bot_btn'],
                    callback_data=f"delete_{bot_username}"
                )
                
                # دکمه تست
                test_msg_btn = types.InlineKeyboardButton(
                    "📨 پیام تست",
                    callback_data=f"test_{bot_username}"
                )
                
                back_btn = types.InlineKeyboardButton(
                    self.render_config['back_btn'],
                    callback_data="back_to_list"
                )
                
                markup.add(delete_btn, test_msg_btn)
                markup.add(back_btn)
                
                info_text = f"⚙️ **مدیریت ربات @{bot_username}**\n\n"
                info_text += f"• وضعیت: {'فعال ✅' if target_bot.get('active', True) else 'غیرفعال ❌'}\n"
                info_text += f"• تاریخ ایجاد: {target_bot.get('created_at', 'نامشخص')}\n"
                info_text += f"• کاربران مسدود شده: {len([u for u in self.blocked_users if u[1] == bot_username])}\n\n"
                info_text += "**گزینه‌های مدیریت:**"
                
                await self.bot.edit_message_text(
                    info_text,
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=markup,
                    parse_mode='Markdown'
                )
                
                await self.bot.answer_callback_query(call.id, "منوی مدیریت")
                
            except Exception as e:
                logger.error(f"خطا در manage callback: {e}")
                await self.bot.answer_callback_query(call.id, "خطا!")
        
        @self.bot.callback_query_handler(func=lambda call: call.data == 'back_to_list')
        async def back_to_list_handler(call):
            """بازگشت به لیست ربات‌ها"""
            await my_bots_handler(call.message)
            await self.bot.answer_callback_query(call.id, "بازگشت")
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('test_'))
        async def test_message_handler(call):
            """ارسال پیام تست"""
            try:
                bot_username = call.data.split('_')[1]
                owner_id = call.from_user.id
                
                # پیدا کردن ربات
                user_bots = self.user_bots.get(owner_id, [])
                target_bot_data = None
                
                for bot in user_bots:
                    if bot['username'] == bot_username:
                        target_bot_data = bot
                        break
                
                if not target_bot_data or 'full_token' not in target_bot_data:
                    await self.bot.answer_callback_query(call.id, "ربات یافت نشد")
                    return
                
                # ایجاد ربات موقت برای ارسال پیام
                test_bot = AsyncTeleBot(target_bot_data['full_token'])
                
                test_msg = "✅ **پیام تست از ربات شما**\n\n"
                test_msg += "این پیام نشان می‌دهد که ربات شما به درستی کار می‌کند.\n"
                test_msg += "کاربران می‌توانند از طریق این ربات با شما چت ناشناس داشته باشند."
                
                await test_bot.send_message(owner_id, test_msg, parse_mode='Markdown')
                
                await self.bot.answer_callback_query(call.id, "پیام تست ارسال شد")
                
            except Exception as e:
                logger.error(f"خطا در ارسال پیام تست: {e}")
                await self.bot.answer_callback_query(call.id, f"خطا: {str(e)[:50]}")
    
    async def process_reply_step(self, message, target_user_id: int, bot_username: str):
        """پردازش پاسخ به کاربر"""
        owner_id = message.from_user.id
        
        # پیدا کردن ربات مربوطه
        user_bots = self.user_bots.get(owner_id, [])
        target_bot_data = None
        
        for bot_data in user_bots:
            if bot_data['username'] == bot_username:
                target_bot_data = bot_data
                break
        
        if not target_bot_data or 'full_token' not in target_bot_data:
            await self.bot.send_message(
                owner_id,
                self.render_config['bot_not_found']
            )
            return
        
        try:
            # ایجاد ربات موقت برای ارسال پاسخ
            reply_bot = AsyncTeleBot(target_bot_data['full_token'])
            
            # بررسی مسدود بودن
            if (target_user_id, bot_username) in self.blocked_users:
                await self.bot.send_message(
                    owner_id,
                    "⚠️ این کاربر مسدود شده است. ابتدا کاربر را آزاد کنید."
                )
                return
            
            # ارسال پاسخ
            reply_text = f"📬 **پاسخ از مالک:**\n\n{message.text}"
            
            await reply_bot.send_message(
                target_user_id,
                reply_text,
                parse_mode='Markdown'
            )
            
            await self.bot.send_message(
                owner_id,
                self.render_config['reply_sent']
            )
            
        except Exception as e:
            logger.error(f"خطا در ارسال پاسخ: {e}")
            error_msg = f"❌ **خطا در ارسال پاسخ:**\n\n"
            
            if "bot was blocked" in str(e).lower():
                error_msg += "کاربر ربات را مسدود کرده است."
            elif "user not found" in str(e).lower():
                error_msg += "کاربر یافت نشد."
            else:
                error_msg += str(e)[:100]
            
            await self.bot.send_message(
                owner_id,
                error_msg,
                parse_mode='Markdown'
            )
    
    async def setup_user_bot(self, bot_data: Dict):
        """راه‌اندازی و تنظیم ربات کاربر"""
        user_bot = bot_data['bot_instance']
        owner_id = bot_data['owner_id']
        bot_username = bot_data['username']
        full_token = bot_data['full_token']
        
        @user_bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'document', 'voice', 'audio', 'sticker'])
        async def user_bot_message_handler(message):
            """هندلر پیام‌های دریافتی توسط ربات کاربر"""
            try:
                sender_id = message.from_user.id
                chat_id = message.chat.id
                
                # جلوگیری از پاسخ به پیام‌های خود ربات
                try:
                    bot_me = await user_bot.get_me()
                    if sender_id == bot_me.id:
                        return
                except:
                    pass
                
                # بررسی مسدود بودن کاربر
                if (sender_id, bot_username) in self.blocked_users:
                    await user_bot.send_message(
                        chat_id,
                        "⛔ شما توسط مالک ربات مسدود شده‌اید."
                    )
                    return
                
                # ذخیره نگاشت چت
                self.chat_mapping[sender_id] = owner_id
                
                # ایجاد پیام برای مالک
                message_text = self.prepare_message_for_owner(message, bot_username)
                
                # ایجاد اینلاین کیبورد
                inline_markup = types.InlineKeyboardMarkup()
                
                # دکمه مشاهده پروفایل
                profile_btn = types.InlineKeyboardButton(
                    self.render_config['view_profile_btn'],
                    url=f"tg://user?id={sender_id}"
                )
                
                # دکمه پاسخ
                reply_btn = types.InlineKeyboardButton(
                    self.render_config['reply_btn'],
                    callback_data=f"reply_{sender_id}_{bot_username}"
                )
                
                # بررسی اینکه آیا کاربر مسدود شده یا نه
                if (sender_id, bot_username) in self.blocked_users:
                    block_btn = types.InlineKeyboardButton(
                        self.render_config['unblock_btn'],
                        callback_data=f"unblock_{sender_id}_{bot_username}"
                    )
                else:
                    block_btn = types.InlineKeyboardButton(
                        self.render_config['block_btn'],
                        callback_data=f"block_{sender_id}_{bot_username}"
                    )
                
                inline_markup.row(profile_btn)
                inline_markup.row(reply_btn, block_btn)
                
                # ارسال پیام به مالک
                try:
                    await self.bot.send_message(
                        owner_id,
                        message_text,
                        reply_markup=inline_markup,
                        parse_mode='HTML'
                    )
                    
                    # تایید دریافت به کاربر
                    await user_bot.send_message(
                        chat_id,
                        "✅ پیام شما دریافت شد و به صورت ناشناس ارسال گردید."
                    )
                    
                except Exception as send_error:
                    logger.error(f"خطا در ارسال پیام به مالک: {send_error}")
                    # اگر نتوانستیم به مالک پیام بدهیم، حداقل به کاربر اطلاع دهیم
                    try:
                        await user_bot.send_message(
                            chat_id,
                            "⚠️ خطایی در ارسال پیام رخ داد. لطفاً بعداً تلاش کنید."
                        )
                    except:
                        pass
                
            except Exception as e:
                logger.error(f"خطا در پردازش پیام کاربر: {e}")
    
    def prepare_message_for_owner(self, message, bot_username: str) -> str:
        """آماده‌سازی پیام برای نمایش به مالک"""
        sender = message.from_user
        sender_name = sender.first_name or ""
        sender_last_name = sender.last_name or ""
        full_name = f"{sender_name} {sender_last_name}".strip()
        if not full_name:
            full_name = "ناشناس"
        
        # ایجاد نام نمایشی
        display_name = f"<b>{full_name}</b>" if full_name else "<i>ناشناس</i>"
        
        message_text = self.render_config['message_received']
        message_text += f"👤 از: {display_name}\n"
        message_text += f"🆔 آیدی: <code>{sender.id}</code>\n"
        message_text += f"🤖 ربات: @{bot_username}\n"
        message_text += f"⏰ زمان: {datetime.now().strftime('%H:%M:%S')}\n"
        message_text += f"📅 تاریخ: {datetime.now().strftime('%Y/%m/%d')}\n\n"
        
        content_type = message.content_type
        
        if content_type == 'text':
            message_text += f"📝 <b>پیام:</b>\n{message.text}"
        elif content_type == 'photo':
            caption = message.caption or ""
            message_text += f"🖼 <b>عکس ارسال شده</b>\n"
            if caption:
                message_text += f"📌 <b>کپشن:</b> {caption}"
        elif content_type == 'video':
            caption = message.caption or ""
            message_text += f"🎬 <b>ویدیو ارسال شده</b>\n"
            if caption:
                message_text += f"📌 <b>کپشن:</b> {caption}"
        elif content_type == 'document':
            file_name = message.document.file_name if message.document else "فایل"
            message_text += f"📎 <b>فایل:</b> {file_name}"
        elif content_type == 'voice':
            message_text += "🎤 <b>پیام صوتی</b>"
        elif content_type == 'audio':
            message_text += "🔊 <b>فایل صوتی</b>"
        elif content_type == 'sticker':
            message_text += "😀 <b>استیکر</b>"
        else:
            message_text += f"📦 <b>نوع محتوا:</b> {content_type}"
        
        return message_text
    
    def start_flask_server(self):
        """شروع سرور Flask"""
        logger.info(f"🚀 شروع سرور Flask روی پورت {self.port}")
        self.app.run(
            host='0.0.0.0',
            port=self.port,
            debug=False,
            threaded=True
        )
    
    def start_polling_sync(self):
        """شروع polling ربات مادر"""
        logger.info("🔄 شروع polling ربات مادر...")
        asyncio.run(self.bot.polling(
            non_stop=True,
            timeout=60,
            skip_pending=True
        ))
    
    def run(self, use_webhook: bool = False):
        """اجرای ربات"""
        logger.info("🚀 راه‌اندازی ربات چت ناشناس...")
        
        # نمایش اطلاعات
        logger.info(f"ربات مادر: فعال")
        logger.info(f"حالت: {'Webhook' if use_webhook else 'Polling'}")
        logger.info(f"پورت Flask: {self.port}")
        
        # شروع سرور Flask در thread جداگانه
        flask_thread = threading.Thread(
            target=self.start_flask_server,
            daemon=True,
            name="flask_server"
        )
        flask_thread.start()
        
        # اگر از webhook استفاده می‌شود
        if use_webhook and self.webhook_url:
            logger.info(f"تنظیم webhook: {self.webhook_url}/webhook/master")
            
            async def set_webhook():
                await self.bot.remove_webhook()
                await self.bot.set_webhook(
                    url=f"{self.webhook_url}/webhook/master",
                    drop_pending_updates=True
                )
                logger.info("Webhook تنظیم شد")
            
            asyncio.run(set_webhook())
        else:
            # شروع polling ربات مادر در thread جداگانه
            polling_thread = threading.Thread(
                target=self.start_polling_sync,
                daemon=True,
                name="master_bot_polling"
            )
            polling_thread.start()
            logger.info("Polling ربات مادر شروع شد")
        
        # نگه داشتن برنامه اصلی
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("🛑 توقف ربات...")
            self.child_manager.stop_all()


# ========== تابع اصلی اجرا ==========
def main():
    """تابع اصلی اجرای ربات"""
    
    # خواندن توکن
    token = os.environ.get('MASTER_BOT_TOKEN')
    
    if not token:
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
                token = config.get('master_bot_token')
        except FileNotFoundError:
            sample_config = {
                "master_bot_token": "YOUR_MASTER_BOT_TOKEN_HERE",
                "webhook_url": "https://your-app.onrender.com",
                "port": 10000
            }
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(sample_config, f, indent=4, ensure_ascii=False)
            
            print("⚠️ فایل config.json ایجاد شد. لطفاً توکن ربات مادر را در آن وارد کنید.")
            print("یا از طریق متغیر محیطی MASTER_BOT_TOKEN تنظیم کنید.")
            return
    
    # تنظیمات وب هوک
    webhook_url = os.environ.get('WEBHOOK_URL')
    port = int(os.environ.get('PORT', 10000))
    
    if not webhook_url:
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
                webhook_url = config.get('webhook_url')
        except:
            pass
    
    print(f"""
    🤖 ربات چت ناشناس
    =================
    
    تنظیمات:
    • ربات مادر: {'✅' if token else '❌'}
    • حالت: {'Webhook' if webhook_url else 'Polling'}
    • پورت: {port}
    """)
    
    if not token:
        print("❌ توکن ربات مادر تنظیم نشده!")
        return
    
    # ایجاد و اجرای ربات
    bot = AnonymousChatBot(
        token=token,
        webhook_url=webhook_url,
        port=port
    )
    
    # اجرا
    use_webhook = bool(webhook_url)
    bot.run(use_webhook=use_webhook)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 ربات متوقف شد.")
    except Exception as e:
        logger.error(f"خطای اصلی: {e}")
        print(f"❌ خطا: {e}")
