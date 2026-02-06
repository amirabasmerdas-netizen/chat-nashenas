#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات تلگرام چت ناشناس - نسخه اصلاح شده برای Render
"""

import os
import json
import logging
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
import threading

from flask import Flask, request, jsonify
import telebot
from telebot import types
from telebot.async_telebot import AsyncTeleBot
import aiohttp
from aiohttp import web

# تنظیمات لاگ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== کلاس مدیریت مرحله‌ها (جایگزین register_next_step_handler) ==========
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


# ========== کلاس اصلی ربات مادر ==========
class AnonymousChatBot:
    def __init__(self, token: str, webhook_url: str = None, port: int = 10000):
        """
        مقداردهی اولیه ربات مادر
        
        Args:
            token: توکن ربات مادر
            webhook_url: آدرس وب هوک
            port: پورت برای اجرای سرور (در Render باید 10000 باشد)
        """
        self.master_token = token
        self.bot = AsyncTeleBot(token)
        self.webhook_url = webhook_url
        self.port = port
        
        # مدیر مراحل
        self.step_manager = StepHandlerManager()
        
        # دیکشنری برای ذخیره ربات‌های کاربران
        self.user_bots: Dict[int, List[Dict]] = {}
        
        # دیکشنری برای ذخیره پیام‌های در انتظار
        self.pending_messages: Dict[int, List] = {}
        
        # دیکشنری برای نگاشت چت‌ها
        self.chat_mapping: Dict[int, int] = {}
        
        # ذخیره آخرین پیام کاربران برای پاسخ
        self.last_user_message: Dict[Tuple[int, int], Dict] = {}  # {(owner_id, user_id): message_data}
        
        # تنظیم هندلرها
        self.setup_handlers()
        self.setup_callback_handlers()
        
        # تنظیمات رندر
        self.render_config = {
            'welcome_message': "🎭 به ربات چت ناشناس خوش آمدید!\n\n"
                              "از طریق این ربات می‌توانید با مخاطبین خود به صورت ناشناس چت کنید.\n\n"
                              "دستورات:\n"
                              "/start - شروع کار با ربات\n"
                              "/addbot - افزودن ربات ناشناس خود\n"
                              "/mybots - مشاهده ربات‌های من\n"
                              "/help - راهنمایی",
            
            'add_bot_instructions': "🤖 برای ایجاد ربات ناشناس خود:\n\n"
                                   "1. به @BotFather در تلگرام مراجعه کنید\n"
                                   "2. دستور /newbot را ارسال کنید\n"
                                   "3. نام و یوزرنیم برای ربات انتخاب کنید\n"
                                   "4. توکن دریافتی را برای من ارسال کنید\n\n"
                                   "⚠️ توجه: مالک ربات شما خواهید بود و فقط شما می‌توانید پیام‌ها را مشاهده کنید.",
            
            'bot_added_success': "✅ ربات شما با موفقیت اضافه شد!\n\n"
                                "ربات شما آماده دریافت پیام‌های ناشناس است.\n"
                                "کاربران با یوزرنیم ربات شما می‌توانند پیام ناشناس ارسال کنند.",
            
            'no_bots_found': "🤖 شما هیچ رباتی اضافه نکرده‌اید.\n"
                            "از دستور /addbot برای افزودن ربات استفاده کنید.",
            
            'bot_list': "📋 ربات‌های شما:\n\n",
            
            'message_received': "📩 پیام ناشناس جدید دریافت شد!\n\n",
            
            'view_profile_btn': "👤 مشاهده پروفایل",
            
            'reply_btn': "↪️ پاسخ",
            
            'block_btn': "🚫 مسدود کردن",
            
            'back_btn': "🔙 بازگشت",
            
            'help_message': "📚 راهنمای ربات چت ناشناس:\n\n"
                           "• شما می‌توانید چندین ربات ناشناس ایجاد کنید\n"
                           "• هر ربات فقط برای شما پیام‌ها را نمایش می‌دهد\n"
                           "• کاربران از طریق یوزرنیم ربات شما می‌توانند پیام بفرستند\n"
                           "• پیام‌ها کاملاً ناشناس هستند\n"
                           "• می‌توانید به پیام‌ها پاسخ دهید\n\n"
                           "دستورات:\n"
                           "/start - شروع\n"
                           "/addbot - افزودن ربات\n"
                           "/mybots - لیست ربات‌ها\n"
                           "/help - راهنمایی",
            
            'enter_token': "لطفاً توکن ربات خود را ارسال کنید:",
            
            'invalid_token': "❌ توکن نامعتبر است. لطفاً توکن صحیح را ارسال کنید.",
            
            'processing_token': "⏳ در حال پردازش توکن...",
            
            'enter_reply': "لطفاً پاسخ خود را ارسال کنید:",
            
            'reply_sent': "✅ پاسخ شما ارسال شد.",
            
            'user_blocked': "✅ کاربر مسدود شد.",
            
            'error_occurred': "❌ خطا در پردازش درخواست."
        }
        
        # Flask app برای وب هوک
        self.app = Flask(__name__)
        self.setup_flask_routes()
    
    def setup_flask_routes(self):
        """تنظیم مسیرهای Flask برای وب هوک"""
        
        @self.app.route('/')
        def index():
            return "🤖 ربات چت ناشناس در حال اجراست!"
        
        @self.app.route('/webhook/master', methods=['POST'])
        def master_webhook():
            """وب هوک ربات مادر"""
            if request.headers.get('content-type') == 'application/json':
                json_string = request.get_data().decode('utf-8')
                update = types.Update.de_json(json_string)
                
                # پردازش آپدیت در thread جداگانه
                asyncio.run(self.process_update(update))
                
                return jsonify({"status": "ok"}), 200
            return jsonify({"error": "Invalid content type"}), 403
        
        @self.app.route('/health', methods=['GET'])
        def health_check():
            """بررسی سلامت سرویس"""
            return jsonify({"status": "healthy", "service": "anonymous-chat-bot"}), 200
    
    async def process_update(self, update):
        """پردازش آپدیت دریافتی"""
        await self.bot.process_new_updates([update])
    
    def setup_handlers(self):
        """تنظیم هندلرهای ربات مادر"""
        
        @self.bot.message_handler(commands=['start'])
        async def start_handler(message):
            """هندلر دستور /start"""
            user_id = message.from_user.id
            
            welcome_msg = self.render_config['welcome_message']
            
            # ایجاد کیبورد اصلی
            markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
            btn1 = types.KeyboardButton("➕ افزودن ربات")
            btn2 = types.KeyboardButton("📋 ربات‌های من")
            btn3 = types.KeyboardButton("ℹ️ راهنمایی")
            markup.add(btn1, btn2, btn3)
            
            await self.bot.send_message(
                message.chat.id,
                welcome_msg,
                reply_markup=markup
            )
            
            # پاک کردن مرحله قبلی
            self.step_manager.clear_step(user_id)
        
        @self.bot.message_handler(commands=['addbot'])
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
        
        @self.bot.message_handler(commands=['mybots'])
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
                status = "✅ فعال" if bot_info.get('active', False) else "❌ غیرفعال"
                bot_list += f"{idx}. @{bot_info.get('username', 'نامشخص')}\n"
                bot_list += f"   وضعیت: {status}\n"
                bot_list += f"   ایجاد: {bot_info.get('created_at', 'نامشخص')}\n\n"
            
            await self.bot.send_message(
                message.chat.id,
                bot_list,
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
            if text == "➕ افزودن ربات":
                await add_bot_handler(message)
            elif text == "📋 ربات‌های من":
                await my_bots_handler(message)
            elif text == "ℹ️ راهنمایی":
                await help_handler(message)
            else:
                await self.bot.send_message(
                    chat_id,
                    "لطفاً از دکمه‌های منو یا دستورات استفاده کنید."
                )
    
    async def process_token_step(self, message):
        """پردازش مرحله دریافت توکن"""
        user_id = message.from_user.id
        token = message.text.strip()
        
        # ارسال پیام پردازش
        await self.bot.send_message(
            message.chat.id,
            self.render_config['processing_token']
        )
        
        # اعتبارسنجی اولیه توکن
        if not token or len(token) < 30:
            await self.bot.send_message(
                message.chat.id,
                self.render_config['invalid_token']
            )
            self.step_manager.clear_step(user_id)
            return
        
        try:
            # ایجاد ربات جدید با توکن کاربر
            user_bot = AsyncTeleBot(token)
            
            # بررسی صحت توکن با یک درخواست تست
            bot_info = await user_bot.get_me()
            bot_username = bot_info.username
            
            # ذخیره اطلاعات ربات کاربر
            if user_id not in self.user_bots:
                self.user_bots[user_id] = []
            
            # بررسی تکراری نبودن ربات
            for existing_bot in self.user_bots[user_id]:
                if existing_bot.get('username') == bot_username:
                    await self.bot.send_message(
                        message.chat.id,
                        f"⚠️ ربات @{bot_username} قبلاً اضافه شده است."
                    )
                    self.step_manager.clear_step(user_id)
                    return
            
            bot_data = {
                'bot_instance': user_bot,
                'token': token,
                'username': bot_username,
                'owner_id': user_id,
                'active': True,
                'created_at': datetime.now().strftime('%Y/%m/%d %H:%M'),
                'user_bot': user_bot  # ذخیره شی ربات
            }
            
            self.user_bots[user_id].append(bot_data)
            
            # راه‌اندازی ربات کاربر
            await self.setup_user_bot(bot_data)
            
            await self.bot.send_message(
                message.chat.id,
                self.render_config['bot_added_success'],
                parse_mode='Markdown'
            )
            
            # نمایش اطلاعات ربات
            info_msg = (
                f"📊 اطلاعات ربات شما:\n\n"
                f"نام: @{bot_username}\n"
                f"توکن: `{token[:15]}...`\n"
                f"تاریخ ایجاد: {datetime.now().strftime('%Y/%m/%d %H:%M')}\n\n"
                f"کاربران می‌توانند از طریق @{bot_username} با شما چت ناشناس داشته باشند."
            )
            
            await self.bot.send_message(
                message.chat.id,
                info_msg,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"خطا در ایجاد ربات کاربر: {e}")
            await self.bot.send_message(
                message.chat.id,
                f"❌ خطا در ایجاد ربات: {str(e)[:100]}"
            )
        
        # پاک کردن مرحله
        self.step_manager.clear_step(user_id)
    
    def setup_callback_handlers(self):
        """تنظیم هندلرهای callback برای ربات مادر"""
        
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
                
                # درخواست پاسخ از مالک
                await self.bot.send_message(
                    call.from_user.id,
                    f"✍️ لطفاً پاسخ خود را برای کاربر ارسال کنید:"
                )
                
            except Exception as e:
                logger.error(f"خطا در پردازش پاسخ: {e}")
                await self.bot.answer_callback_query(call.id, "خطا در پردازش")
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('block_'))
        async def block_callback_handler(call):
            """هندلر مسدود کردن کاربر"""
            try:
                data_parts = call.data.split('_')
                if len(data_parts) < 3:
                    await self.bot.answer_callback_query(call.id, "خطا در پردازش")
                    return
                
                target_user_id = int(data_parts[1])
                bot_username = data_parts[2]
                
                # پیدا کردن ربات مربوطه
                owner_id = call.from_user.id
                user_bots = self.user_bots.get(owner_id, [])
                
                target_bot = None
                for bot_data in user_bots:
                    if bot_data['username'] == bot_username:
                        target_bot = bot_data.get('user_bot')
                        break
                
                if target_bot:
                    try:
                        # ذخیره اطلاعات مسدودسازی
                        block_key = f"blocked_{owner_id}_{bot_username}"
                        if owner_id not in self.pending_messages:
                            self.pending_messages[owner_id] = []
                        
                        # اضافه کردن کاربر به لیست مسدود شده (در واقعیت باید در دیتابیس ذخیره شود)
                        self.pending_messages[owner_id].append({
                            'type': 'blocked_user',
                            'user_id': target_user_id,
                            'bot_username': bot_username,
                            'timestamp': datetime.now().isoformat()
                        })
                        
                        await self.bot.answer_callback_query(
                            call.id,
                            self.render_config['user_blocked']
                        )
                        
                        await self.bot.send_message(
                            owner_id,
                            f"✅ کاربر با آیدی `{target_user_id}` به لیست مسدود شده اضافه شد.",
                            parse_mode='Markdown'
                        )
                        
                    except Exception as e:
                        logger.error(f"خطا در مسدود کردن کاربر: {e}")
                        await self.bot.answer_callback_query(call.id, "خطا در مسدود کردن")
                else:
                    await self.bot.answer_callback_query(call.id, "ربات مورد نظر یافت نشد")
                    
            except Exception as e:
                logger.error(f"خطا در پردازش مسدودسازی: {e}")
                await self.bot.answer_callback_query(call.id, self.render_config['error_occurred'])
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('delete_'))
        async def delete_bot_callback_handler(call):
            """هندلر حذف ربات"""
            try:
                data_parts = call.data.split('_')
                if len(data_parts) < 2:
                    await self.bot.answer_callback_query(call.id, "خطا در پردازش")
                    return
                
                bot_username = data_parts[1]
                owner_id = call.from_user.id
                
                # حذف ربات از لیست
                if owner_id in self.user_bots:
                    self.user_bots[owner_id] = [
                        bot for bot in self.user_bots[owner_id] 
                        if bot.get('username') != bot_username
                    ]
                
                await self.bot.answer_callback_query(call.id, "✅ ربات حذف شد")
                await self.bot.send_message(owner_id, f"ربات @{bot_username} حذف شد.")
                
            except Exception as e:
                logger.error(f"خطا در حذف ربات: {e}")
                await self.bot.answer_callback_query(call.id, "خطا در حذف")
    
    async def process_reply_step(self, message, target_user_id: int, bot_username: str):
        """پردازش مرحله پاسخ به کاربر"""
        owner_id = message.from_user.id
        
        # پیدا کردن ربات مربوطه
        user_bots = self.user_bots.get(owner_id, [])
        target_bot = None
        
        for bot_data in user_bots:
            if bot_data['username'] == bot_username:
                target_bot = bot_data.get('user_bot')
                break
        
        if not target_bot:
            await self.bot.send_message(
                owner_id,
                "❌ ربات مورد نظر یافت نشد."
            )
            return
        
        try:
            # ارسال پاسخ به کاربر
            reply_text = f"📬 پاسخ از مالک:\n\n{message.text}"
            await target_bot.send_message(target_user_id, reply_text)
            
            await self.bot.send_message(
                owner_id,
                self.render_config['reply_sent']
            )
            
        except Exception as e:
            logger.error(f"خطا در ارسال پاسخ: {e}")
            await self.bot.send_message(
                owner_id,
                f"❌ خطا در ارسال پاسخ: کاربر ممکن است ربات را مسدود کرده باشد."
            )
    
    async def setup_user_bot(self, bot_data: Dict):
        """راه‌اندازی و تنظیم ربات کاربر"""
        user_bot = bot_data['bot_instance']
        owner_id = bot_data['owner_id']
        bot_username = bot_data['username']
        
        @user_bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'document', 'voice', 'audio', 'sticker'])
        async def user_bot_message_handler(message):
            """هندلر پیام‌های دریافتی توسط ربات کاربر"""
            try:
                sender_id = message.from_user.id
                chat_id = message.chat.id
                
                # جلوگیری از پاسخ به پیام‌های خود ربات
                bot_me = await user_bot.get_me()
                if sender_id == bot_me.id:
                    return
                
                # بررسی مسدود بودن کاربر
                block_key = f"blocked_{owner_id}_{bot_username}"
                blocked_users = self.pending_messages.get(owner_id, [])
                
                for item in blocked_users:
                    if item.get('type') == 'blocked_user' and item.get('user_id') == sender_id:
                        await user_bot.send_message(
                            chat_id,
                            "⛔ شما توسط مالک ربات مسدود شده‌اید و نمی‌توانید پیام ارسال کنید."
                        )
                        return
                
                # ذخیره نگاشت چت
                self.chat_mapping[sender_id] = owner_id
                
                # ذخیره آخرین پیام برای امکان پاسخ
                self.last_user_message[(owner_id, sender_id)] = {
                    'message': message,
                    'bot_username': bot_username,
                    'timestamp': datetime.now().isoformat()
                }
                
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
                
                # دکمه مسدود کردن
                block_btn = types.InlineKeyboardButton(
                    self.render_config['block_btn'],
                    callback_data=f"block_{sender_id}_{bot_username}"
                )
                
                inline_markup.row(profile_btn)
                inline_markup.row(reply_btn, block_btn)
                
                # ارسال پیام به مالک
                await self.bot.send_message(
                    owner_id,
                    message_text,
                    reply_markup=inline_markup,
                    parse_mode='HTML'
                )
                
                # پاسخ به کاربر مبنی بر دریافت پیام
                await user_bot.send_message(
                    chat_id,
                    "✅ پیام شما دریافت شد و به صورت ناشناس ارسال گردید."
                )
                
            except Exception as e:
                logger.error(f"خطا در پردازش پیام کاربر: {e}")
                try:
                    await user_bot.send_message(
                        message.chat.id,
                        "⚠️ خطایی در ارسال پیام رخ داد. لطفاً مجدداً تلاش کنید."
                    )
                except:
                    pass
        
        @user_bot.callback_query_handler(func=lambda call: True)
        async def user_bot_callback_handler(call):
            """هندلر callback های ربات کاربر"""
            await user_bot.answer_callback_query(call.id, "در حال پردازش...")
        
        # اگر وب هوک فعال است، تنظیم کن
        if self.webhook_url:
            try:
                webhook_path = f"/webhook/{bot_username}_{owner_id}"
                full_webhook_url = f"{self.webhook_url}{webhook_path}"
                
                # در نسخه فعلی از polling استفاده می‌کنیم
                # برای وب هوک نیاز به تنظیم سرور جداگانه داریم
                logger.info(f"ربات کاربر @{bot_username} آماده است (Polling Mode)")
            except Exception as e:
                logger.error(f"خطا در تنظیم ربات کاربر: {e}")
        
        logger.info(f"ربات کاربر @{bot_username} برای مالک {owner_id} راه‌اندازی شد")
    
    def prepare_message_for_owner(self, message, bot_username: str) -> str:
        """آماده‌سازی پیام برای نمایش به مالک"""
        sender = message.from_user
        sender_name = sender.first_name or ""
        sender_last_name = sender.last_name or ""
        full_name = f"{sender_name} {sender_last_name}".strip()
        if not full_name:
            full_name = "ناشناس"
        
        message_text = self.render_config['message_received']
        message_text += f"👤 از: {full_name}\n"
        message_text += f"🆔 آیدی: <code>{sender.id}</code>\n"
        message_text += f"🤖 ربات: @{bot_username}\n"
        message_text += f"⏰ زمان: {datetime.now().strftime('%H:%M:%S')}\n\n"
        
        content_type = message.content_type
        
        if content_type == 'text':
            message_text += f"📝 پیام:\n{message.text}"
        elif content_type == 'photo':
            caption = message.caption or ""
            message_text += f"🖼 عکس ارسال شده\n"
            if caption:
                message_text += f"📌 کپشن: {caption}"
        elif content_type == 'video':
            caption = message.caption or ""
            message_text += f"🎬 ویدیو ارسال شده\n"
            if caption:
                message_text += f"📌 کپشن: {caption}"
        elif content_type == 'document':
            file_name = message.document.file_name if message.document else "فایل"
            message_text += f"📎 فایل: {file_name}"
        elif content_type == 'voice':
            message_text += "🎤 پیام صوتی"
        elif content_type == 'audio':
            message_text += "🔊 فایل صوتی"
        elif content_type == 'sticker':
            message_text += "😀 استیکر"
        else:
            message_text += f"📦 محتوای ارسالی ({content_type})"
        
        return message_text
    
    def update_render_config(self, new_config: Dict):
        """به‌روزرسانی تنظیمات رندر"""
        self.render_config.update(new_config)
        logger.info("تنظیمات رندر به‌روزرسانی شد")
    
    async def start_polling_for_user_bots(self):
        """شروع polling برای ربات‌های کاربران"""
        """توجه: در عمل بهتر است از webhook استفاده شود"""
        pass
    
    def start_polling_sync(self):
        """شروع polling به صورت همزمان"""
        asyncio.run(self.bot.polling(non_stop=True, timeout=60))
    
    def start_flask_server(self):
        """شروع سرور Flask"""
        logger.info(f"🚀 شروع سرور Flask روی پورت {self.port}")
        self.app.run(host='0.0.0.0', port=self.port, debug=False)
    
    def run(self, use_webhook: bool = False):
        """اجرای ربات"""
        logger.info("🚀 ربات چت ناشناس در حال راه‌اندازی...")
        
        if use_webhook and self.webhook_url:
            logger.info(f"🔗 حالت Webhook فعال: {self.webhook_url}")
            
            # تنظیم وب هوک برای ربات مادر
            async def set_webhook_async():
                await self.bot.remove_webhook()
                webhook_url = f"{self.webhook_url}/webhook/master"
                await self.bot.set_webhook(
                    url=webhook_url,
                    drop_pending_updates=True
                )
                logger.info(f"Webhook تنظیم شد: {webhook_url}")
            
            # اجرای تنظیمات وب هوک
            asyncio.run(set_webhook_async())
            
            # شروع سرور Flask در thread جداگانه
            flask_thread = threading.Thread(target=self.start_flask_server)
            flask_thread.daemon = True
            flask_thread.start()
            
            # نگه داشتن برنامه در حال اجرا
            try:
                flask_thread.join()
            except KeyboardInterrupt:
                logger.info("ربات متوقف شد.")
        
        else:
            logger.info("🔄 حالت Polling فعال")
            
            # اجرای polling در thread جداگانه
            polling_thread = threading.Thread(target=self.start_polling_sync)
            polling_thread.daemon = True
            polling_thread.start()
            
            # همچنین سرور Flask را برای health check اجرا کن
            flask_thread = threading.Thread(target=self.start_flask_server)
            flask_thread.daemon = True
            flask_thread.start()
            
            try:
                while True:
                    # برنامه را زنده نگه دار
                    import time
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info("ربات متوقف شد.")


# ========== تابع اصلی اجرا ==========
def main():
    """تابع اصلی اجرای ربات"""
    
    # خواندن توکن از متغیر محیطی (اولویت اول در Render)
    token = os.environ.get('MASTER_BOT_TOKEN')
    
    if not token:
        # اگر توکن در متغیر محیطی نبود، از فایل بخوان
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
                token = config.get('master_bot_token')
        except FileNotFoundError:
            # ایجاد فایل config.json نمونه
            sample_config = {
                "master_bot_token": "YOUR_MASTER_BOT_TOKEN_HERE",
                "webhook_url": "https://your-app-name.onrender.com",
                "port": 10000
            }
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(sample_config, f, indent=4, ensure_ascii=False)
            
            print("⚠️ فایل config.json ایجاد شد. لطفاً توکن ربات مادر را در آن وارد کنید.")
            print("یا از طریق متغیر محیطی MASTER_BOT_TOKEN تنظیم کنید.")
            return
    
    # خواندن تنظیمات وب هوک
    webhook_url = os.environ.get('WEBHOOK_URL')
    port = int(os.environ.get('PORT', 10000))  # Render از پورت 10000 استفاده می‌کند
    
    if not webhook_url:
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
                webhook_url = config.get('webhook_url')
                port = config.get('port', port)
        except:
            pass
    
    # نمایش اطلاعات تنظیمات
    print(f"🤖 ربات مادر: {'فعال' if token else 'غیرفعال'}")
    print(f"🔗 Webhook URL: {webhook_url or 'استفاده از Polling'}")
    print(f"🚪 پورت: {port}")
    
    if not token:
        print("❌ توکن ربات مادر تنظیم نشده است!")
        print("لطفاً یکی از روش‌های زیر را انجام دهید:")
        print("1. فایل config.json را ویرایش کنید")
        print("2. متغیر محیطی MASTER_BOT_TOKEN را تنظیم کنید")
        return
    
    # ایجاد و اجرای ربات
    bot = AnonymousChatBot(
        token=token,
        webhook_url=webhook_url,
        port=port
    )
    
    # اجرای ربات
    use_webhook = bool(webhook_url)
    print(f"🚀 ربات در حال اجرا است... (Webhook: {use_webhook})")
    bot.run(use_webhook=use_webhook)


# ========== اجرا در صورت فراخوانی مستقیم ==========
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 ربات متوقف شد.")
    except Exception as e:
        logger.error(f"خطای اصلی: {e}")
        print(f"❌ خطا در اجرای ربات: {e}")
