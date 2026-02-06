#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات تلگرام چت ناشناس - نسخه تک فایل
"""

import os
import json
import logging
import threading
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

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

# ========== کلاس اصلی ربات مادر ==========
class AnonymousChatBot:
    def __init__(self, token: str, webhook_url: str = None, port: int = 8443):
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
        
        # دیکشنری برای ذخیره ربات‌های کاربران: {user_id: {'bot': bot_instance, 'token': token, 'owner_id': owner_id}}
        self.user_bots: Dict[int, Dict] = {}
        
        # دیکشنری برای ذخیره پیام‌های در انتظار: {user_bot_owner_id: [messages]}
        self.pending_messages: Dict[int, List] = {}
        
        # دیکشنری برای نگاشت چت‌ها: {anonymous_user_id: owner_id}
        self.chat_mapping: Dict[int, int] = {}
        
        # تنظیم هندلرها
        self.setup_handlers()
        
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
                           "/help - راهنمایی"
        }
    
    def setup_handlers(self):
        """تنظیم هندلرهای ربات مادر"""
        
        @self.bot.message_handler(commands=['start'])
        async def start_handler(message):
            """هندلر دستور /start"""
            user_id = message.from_user.id
            first_name = message.from_user.first_name
            
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
        
        @self.bot.message_handler(commands=['addbot'])
        async def add_bot_handler(message):
            """هندلر افزودن ربات جدید"""
            instructions = self.render_config['add_bot_instructions']
            
            await self.bot.send_message(
                message.chat.id,
                instructions,
                parse_mode='Markdown'
            )
            
            # درخواست توکن
            msg = await self.bot.send_message(
                message.chat.id,
                "لطفاً توکن ربات خود را ارسال کنید:"
            )
            
            # ثبت برای دریافت توکن
            await self.bot.register_next_step_handler(msg, self.process_token)
        
        @self.bot.message_handler(commands=['mybots'])
        async def my_bots_handler(message):
            """هندلر مشاهده ربات‌های کاربر"""
            user_id = message.from_user.id
            
            if user_id not in self.user_bots:
                await self.bot.send_message(
                    message.chat.id,
                    self.render_config['no_bots_found']
                )
                return
            
            bot_list = self.render_config['bot_list']
            user_bots_info = self.user_bots[user_id]
            
            for idx, bot_info in enumerate(user_bots_info, 1):
                bot_list += f"{idx}. @{bot_info.get('username', 'نامشخص')}\n"
                bot_list += f"   توکن: `{bot_info['token'][:10]}...`\n"
                bot_list += f"   وضعیت: {'✅ فعال' if bot_info.get('active', False) else '❌ غیرفعال'}\n\n"
            
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
            text = message.text
            
            if text == "➕ افزودن ربات":
                await add_bot_handler(message)
            elif text == "📋 ربات‌های من":
                await my_bots_handler(message)
            elif text == "ℹ️ راهنمایی":
                await help_handler(message)
            else:
                await self.bot.send_message(
                    message.chat.id,
                    "دستور نامعتبر است. از منو استفاده کنید."
                )
    
    async def process_token(self, message):
        """پردازش توکن دریافتی از کاربر"""
        user_id = message.from_user.id
        token = message.text.strip()
        
        # اعتبارسنجی اولیه توکن
        if not token or len(token) < 30:
            await self.bot.send_message(
                message.chat.id,
                "❌ توکن نامعتبر است. لطفاً توکن صحیح را ارسال کنید."
            )
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
            
            bot_data = {
                'bot_instance': user_bot,
                'token': token,
                'username': bot_username,
                'owner_id': user_id,
                'active': True,
                'created_at': datetime.now().isoformat()
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
                f"❌ خطا در ایجاد ربات: {str(e)}"
            )
    
    async def setup_user_bot(self, bot_data: Dict):
        """راه‌اندازی و تنظیم ربات کاربر"""
        user_bot = bot_data['bot_instance']
        owner_id = bot_data['owner_id']
        bot_username = bot_data['username']
        
        @user_bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'document', 'voice'])
        async def user_bot_message_handler(message):
            """هندلر پیام‌های دریافتی توسط ربات کاربر"""
            sender_id = message.from_user.id
            chat_id = message.chat.id
            
            # جلوگیری از پاسخ به پیام‌های خود ربات
            if sender_id == (await user_bot.get_me()).id:
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
            
            # دکمه مسدود کردن
            block_btn = types.InlineKeyboardButton(
                self.render_config['block_btn'],
                callback_data=f"block_{sender_id}_{bot_username}"
            )
            
            inline_markup.row(profile_btn)
            inline_markup.row(reply_btn, block_btn)
            
            try:
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
                logger.error(f"خطا در ارسال پیام به مالک: {e}")
        
        @user_bot.callback_query_handler(func=lambda call: True)
        async def user_bot_callback_handler(call):
            """هندلر callback های ربات کاربر"""
            await user_bot.answer_callback_query(call.id, "در حال پردازش...")
        
        # راه‌اندازی وب هوک برای ربات کاربر اگر آدرس مشخص شده
        if self.webhook_url:
            webhook_path = f"/webhook/{bot_username}_{owner_id}"
            full_webhook_url = f"{self.webhook_url}{webhook_path}"
            
            try:
                await user_bot.remove_webhook()
                await user_bot.set_webhook(
                    url=full_webhook_url,
                    drop_pending_updates=True
                )
                logger.info(f"Webhook set for @{bot_username}: {full_webhook_url}")
            except Exception as e:
                logger.error(f"خطا در تنظیم وب هوک: {e}")
        
        # ذخیره هندلرها برای استفاده بعدی
        bot_data['handlers'] = {
            'message_handler': user_bot_message_handler,
            'callback_handler': user_bot_callback_handler
        }
        
        logger.info(f"ربات کاربر @{bot_username} برای مالک {owner_id} راه‌اندازی شد")
    
    def prepare_message_for_owner(self, message, bot_username: str) -> str:
        """آماده‌سازی پیام برای نمایش به مالک"""
        sender = message.from_user
        sender_name = sender.first_name or ""
        sender_last_name = sender.last_name or ""
        full_name = f"{sender_name} {sender_last_name}".strip()
        
        message_text = self.render_config['message_received']
        message_text += f"📨 از: {full_name}\n"
        message_text += f"🆔 آیدی: <code>{sender.id}</code>\n"
        message_text += f"🤖 از طریق: @{bot_username}\n"
        message_text += f"⏰ زمان: {datetime.now().strftime('%H:%M:%S')}\n\n"
        
        if message.content_type == 'text':
            message_text += f"📝 پیام:\n{message.text}"
        elif message.content_type == 'photo':
            message_text += "🖼 عکس ارسال شده"
        elif message.content_type == 'video':
            message_text += "🎬 ویدیو ارسال شده"
        elif message.content_type == 'document':
            message_text += f"📎 فایل: {message.document.file_name}"
        elif message.content_type == 'voice':
            message_text += "🎤 پیام صوتی"
        
        return message_text
    
    async def setup_callback_handlers(self):
        """تنظیم هندلرهای callback برای ربات مادر"""
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('reply_'))
        async def reply_callback_handler(call):
            """هندلر پاسخ به پیام"""
            data_parts = call.data.split('_')
            if len(data_parts) < 3:
                await self.bot.answer_callback_query(call.id, "خطا در پردازش")
                return
            
            target_user_id = int(data_parts[1])
            bot_username = data_parts[2]
            
            await self.bot.answer_callback_query(call.id, "لطفاً پاسخ خود را تایپ کنید...")
            
            # درخواست پاسخ از مالک
            msg = await self.bot.send_message(
                call.from_user.id,
                f"لطفاً پاسخ خود را برای کاربر با آیدی {target_user_id} ارسال کنید:"
            )
            
            # ثبت برای دریافت پاسخ
            await self.bot.register_next_step_handler(msg, self.process_reply, target_user_id, bot_username)
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('block_'))
        async def block_callback_handler(call):
            """هندلر مسدود کردن کاربر"""
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
                    target_bot = bot_data['bot_instance']
                    break
            
            if target_bot:
                try:
                    # مسدود کردن کاربر (در واقع فقط اطلاع‌رسانی)
                    await target_bot.send_message(
                        target_user_id,
                        "متأسفانه شما توسط مالک ربات مسدود شده‌اید و نمی‌توانید پیام ارسال کنید."
                    )
                    
                    await self.bot.answer_callback_query(
                        call.id,
                        "کاربر مسدود شد و به او اطلاع داده شد."
                    )
                    
                    await self.bot.send_message(
                        owner_id,
                        f"✅ کاربر با آیدی {target_user_id} مسدود شد."
                    )
                    
                except Exception as e:
                    logger.error(f"خطا در مسدود کردن کاربر: {e}")
                    await self.bot.answer_callback_query(call.id, "خطا در مسدود کردن")
            else:
                await self.bot.answer_callback_query(call.id, "ربات مورد نظر یافت نشد")
    
    async def process_reply(self, message, target_user_id: int, bot_username: str):
        """پردازش پاسخ مالک به کاربر"""
        owner_id = message.from_user.id
        
        # پیدا کردن ربات مربوطه
        user_bots = self.user_bots.get(owner_id, [])
        target_bot = None
        
        for bot_data in user_bots:
            if bot_data['username'] == bot_username:
                target_bot = bot_data['bot_instance']
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
                f"✅ پاسخ شما به کاربر با آیدی {target_user_id} ارسال شد."
            )
            
        except Exception as e:
            logger.error(f"خطا در ارسال پاسخ: {e}")
            await self.bot.send_message(
                owner_id,
                f"❌ خطا در ارسال پاسخ: {str(e)}"
            )
    
    def update_render_config(self, new_config: Dict):
        """به‌روزرسانی تنظیمات رندر"""
        self.render_config.update(new_config)
        logger.info("تنظیمات رندر به‌روزرسانی شد")
    
    async def start_polling(self):
        """شروع polling برای ربات مادر"""
        logger.info("شروع polling برای ربات مادر...")
        
        # تنظیم هندلرهای callback
        await self.setup_callback_handlers()
        
        # حذف وب هوک قبلی (اگر存在 دارد)
        await self.bot.remove_webhook()
        
        # شروع polling
        await self.bot.polling(non_stop=True, timeout=60)
    
    async def start_webhook(self):
        """شروع وب هوک برای ربات مادر"""
        logger.info("شروع وب هوک برای ربات مادر...")
        
        # تنظیم هندلرهای callback
        await self.setup_callback_handlers()
        
        # تنظیم وب هوک
        await self.bot.remove_webhook()
        await self.bot.set_webhook(
            url=f"{self.webhook_url}/webhook/master",
            drop_pending_updates=True
        )
        
        logger.info(f"وب هوک ربات مادر تنظیم شد: {self.webhook_url}/webhook/master")
        
        # اجرای سرور Flask
        app = Flask(__name__)
        
        @app.route('/webhook/master', methods=['POST'])
        def master_webhook():
            """وب هوک ربات مادر"""
            if request.headers.get('content-type') == 'application/json':
                json_string = request.get_data().decode('utf-8')
                update = types.Update.de_json(json_string)
                
                # پردازش آپدیت در تابع جداگانه
                asyncio.create_task(self.bot.process_new_updates([update]))
                
                return jsonify({"status": "ok"}), 200
            else:
                return jsonify({"error": "Invalid content type"}), 403
        
        # شروع سرور Flask
        app.run(host='0.0.0.0', port=self.port)
    
    def run(self, use_webhook: bool = False):
        """اجرای ربات"""
        if use_webhook and self.webhook_url:
            asyncio.run(self.start_webhook())
        else:
            asyncio.run(self.start_polling())


# ========== تابع اصلی اجرا ==========
def main():
    """تابع اصلی اجرای ربات"""
    
    # خواندن توکن از متغیر محیطی یا فایل
    token = os.environ.get('MASTER_BOT_TOKEN')
    
    if not token:
        # اگر توکن در متغیر محیطی نبود، از فایل بخوان
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
                token = config.get('master_bot_token')
        except FileNotFoundError:
            # ایجاد فایل config.json نمونه
            sample_config = {
                "master_bot_token": "YOUR_MASTER_BOT_TOKEN_HERE",
                "webhook_url": "https://yourdomain.com",
                "port": 8443
            }
            with open('config.json', 'w') as f:
                json.dump(sample_config, f, indent=4)
            
            print("⚠️ فایل config.json ایجاد شد. لطفاً توکن ربات مادر را در آن وارد کنید.")
            return
    
    # خواندن تنظیمات وب هوک
    webhook_url = os.environ.get('WEBHOOK_URL')
    port = int(os.environ.get('PORT', 8443))
    
    if not webhook_url:
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
                webhook_url = config.get('webhook_url')
                port = config.get('port', port)
        except:
            pass
    
    # ایجاد و اجرای ربات
    bot = AnonymousChatBot(
        token=token,
        webhook_url=webhook_url,
        port=port
    )
    
    # اضافه کردن تنظیمات سفارشی رندر (اختیاری)
    custom_render_config = {
        'welcome_message': "🌟 به پیشرفته‌ترین ربات چت ناشناس خوش آمدید!",
        # می‌توانید سایر تنظیمات را اینجا تغییر دهید
    }
    
    bot.update_render_config(custom_render_config)
    
    # اجرای ربات
    use_webhook = bool(webhook_url)
    print(f"🚀 ربات در حال اجرا است... (Webhook: {use_webhook})")
    bot.run(use_webhook=use_webhook)


# ========== اجرا در صورت فراخوانی مستقیم ==========
if __name__ == "__main__":
    # برای اجرا در محیط‌های مختلف
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 ربات متوقف شد.")
    except Exception as e:
        logger.error(f"خطای اصلی: {e}")
        print(f"❌ خطا در اجرای ربات: {e}")
