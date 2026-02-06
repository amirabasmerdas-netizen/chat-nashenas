#!/usr/bin/env python3
"""
ربات چت ناشناس تک فایله با پشتیبانی از Render
مالک: تنها فردی که می‌تواند همه پیام‌ها را ببیند و مدیریت کند
کاربران: افراد ناشناس که فقط می‌توانند پیام بفرستند
"""

from flask import Flask, render_template_string, request, jsonify
import json
import os
from datetime import datetime
import threading
import time
import requests
from urllib.parse import urlparse

app = Flask(__name__)

# تنظیمات وب‌هوک برای Render
RENDER_WEBHOOK_URL = os.environ.get('RENDER_WEBHOOK_URL', '')
WEBHOOK_INTERVAL = 25 * 60  # هر 25 دقیقه (رندر پس از 30 دقیقه غیرفعال می‌شود)

# فایل ذخیره داده‌ها
DATA_FILE = "chat_data.json"

# تنظیمات اولیه
CONFIG = {
    "owner_password": os.environ.get('OWNER_PASSWORD', 'owner123'),  # رمز مالک از متغیر محیطی
    "chat_title": "چت ناشناس",
    "max_messages": 100,
    "allow_anonymous": True
}

# ساختار داده‌ها
if not os.path.exists(DATA_FILE):
    initial_data = {
        "messages": [],
        "users": {},  # فقط برای شناسایی مالک
        "banned_ips": [],
        "stats": {
            "total_messages": 0,
            "unique_users": 0,
            "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(initial_data, f, ensure_ascii=False)

def load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# تابع وب‌هوک برای فعال نگه داشتن
def ping_webhook():
    """ارسال درخواست به وب‌هوک برای فعال نگه داشتن برنامه"""
    if RENDER_WEBHOOK_URL:
        try:
            response = requests.get(RENDER_WEBHOOK_URL, timeout=10)
            print(f"✅ وب‌هوک ارسال شد - وضعیت: {response.status_code}")
            
            # ذخیره زمان آخرین وب‌هوک
            chat_data = load_data()
            chat_data["last_webhook"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_data(chat_data)
            
        except Exception as e:
            print(f"❌ خطا در ارسال وب‌هوک: {e}")

def webhook_scheduler():
    """زمان‌بندی ارسال وب‌هوک"""
    while True:
        time.sleep(WEBHOOK_INTERVAL)
        ping_webhook()

# شروع زمان‌بند وب‌هوک در صورت وجود URL
if RENDER_WEBHOOK_URL:
    print(f"🚀 وب‌هوک فعال شد: ارسال هر {WEBHOOK_INTERVAL//60} دقیقه")
    webhook_thread = threading.Thread(target=webhook_scheduler, daemon=True)
    webhook_thread.start()

# صفحه اصلی برای کاربران ناشناس
HTML_TEMPLATE = """
<!DOCTYPE html>
<html dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            --primary: #6a11cb;
            --secondary: #2575fc;
            --success: #00b09b;
            --danger: #ff416c;
            --warning: #ff9966;
            --dark: #2c3e50;
            --light: #f8f9fa;
        }
        
        * {
            box-sizing: border-box;
            font-family: 'Vazirmatn', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        
        body {
            background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%);
            margin: 0;
            padding: 20px;
            min-height: 100vh;
            color: #333;
        }
        
        .container {
            max-width: 900px;
            margin: 0 auto;
            background-color: rgba(255, 255, 255, 0.98);
            border-radius: 20px;
            box-shadow: 0 15px 35px rgba(0, 0, 0, 0.2);
            overflow: hidden;
            animation: fadeIn 0.5s ease;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .header {
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            color: white;
            padding: 25px;
            text-align: center;
            position: relative;
            overflow: hidden;
        }
        
        .header::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: url("data:image/svg+xml,%3Csvg width='100' height='100' viewBox='0 0 100 100' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M11 18c3.866 0 7-3.134 7-7s-3.134-7-7-7-7 3.134-7 7 3.134 7 7 7zm48 25c3.866 0 7-3.134 7-7s-3.134-7-7-7-7 3.134-7 7 3.134 7 7 7zm-43-7c1.657 0 3-1.343 3-3s-1.343-3-3-3-3 1.343-3 3 1.343 3 3 3zm63 31c1.657 0 3-1.343 3-3s-1.343-3-3-3-3 1.343-3 3 1.343 3 3 3zM34 90c1.657 0 3-1.343 3-3s-1.343-3-3-3-3 1.343-3 3 1.343 3 3 3zm56-76c1.657 0 3-1.343 3-3s-1.343-3-3-3-3 1.343-3 3 1.343 3 3 3zM12 86c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm28-65c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm23-11c2.76 0 5-2.24 5-5s-2.24-5-5-5-5 2.24-5 5 2.24 5 5 5zm-6 60c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm29 22c2.76 0 5-2.24 5-5s-2.24-5-5-5-5 2.24-5 5 2.24 5 5 5zM32 63c2.76 0 5-2.24 5-5s-2.24-5-5-5-5 2.24-5 5 2.24 5 5 5zm57-13c2.76 0 5-2.24 5-5s-2.24-5-5-5-5 2.24-5 5 2.24 5 5 5zm-9-21c1.105 0 2-.895 2-2s-.895-2-2-2-2 .895-2 2 .895 2 2 2zM60 91c1.105 0 2-.895 2-2s-.895-2-2-2-2 .895-2 2 .895 2 2 2zM35 41c1.105 0 2-.895 2-2s-.895-2-2-2-2 .895-2 2 .895 2 2 2zM12 60c1.105 0 2-.895 2-2s-.895-2-2-2-2 .895-2 2 .895 2 2 2z' fill='%23ffffff' fill-opacity='0.1' fill-rule='evenodd'/%3E%3C/svg%3E");
            opacity: 0.1;
        }
        
        .header h1 {
            margin: 0;
            font-size: 28px;
            font-weight: 700;
            position: relative;
            z-index: 1;
        }
        
        .header p {
            margin: 10px 0 0;
            opacity: 0.9;
            font-size: 15px;
            position: relative;
            z-index: 1;
        }
        
        .status-indicator {
            position: absolute;
            top: 20px;
            left: 20px;
            display: flex;
            align-items: center;
            gap: 8px;
            background: rgba(255, 255, 255, 0.2);
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 12px;
            z-index: 2;
        }
        
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: #4CAF50;
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.5; }
            100% { opacity: 1; }
        }
        
        .chat-container {
            padding: 20px;
            height: 500px;
            overflow-y: auto;
            border-bottom: 1px solid #eee;
            background: #fafafa;
        }
        
        .message {
            margin-bottom: 15px;
            padding: 12px 18px;
            border-radius: 18px;
            max-width: 80%;
            word-wrap: break-word;
            position: relative;
            animation: messageAppear 0.3s ease;
            box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        }
        
        @keyframes messageAppear {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .anonymous-user {
            background-color: #e8f5e9;
            margin-right: auto;
            border-top-right-radius: 5px;
            border-left: 4px solid #4CAF50;
        }
        
        .owner {
            background: linear-gradient(90deg, #fff9c4, #ffecb3);
            margin-left: auto;
            border-top-left-radius: 5px;
            border-right: 4px solid #FF9800;
        }
        
        .message-time {
            font-size: 11px;
            color: #666;
            margin-top: 5px;
            text-align: left;
            direction: ltr;
        }
        
        .message-sender {
            font-weight: bold;
            margin-bottom: 5px;
            font-size: 13px;
            display: flex;
            align-items: center;
            gap: 5px;
        }
        
        .message-sender i {
            font-size: 12px;
        }
        
        .input-area {
            padding: 20px;
            display: flex;
            gap: 15px;
            align-items: flex-end;
            background: white;
        }
        
        #messageInput {
            flex: 1;
            padding: 15px;
            border: 2px solid #e0e0e0;
            border-radius: 15px;
            font-size: 16px;
            resize: none;
            min-height: 60px;
            font-family: inherit;
            transition: border 0.3s;
        }
        
        #messageInput:focus {
            outline: none;
            border-color: var(--primary);
        }
        
        #sendButton {
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            color: white;
            border: none;
            border-radius: 15px;
            padding: 0 30px;
            height: 60px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            display: flex;
            align-items: center;
            gap: 8px;
            box-shadow: 0 4px 15px rgba(106, 17, 203, 0.3);
        }
        
        #sendButton:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(106, 17, 203, 0.4);
        }
        
        #sendButton:active {
            transform: translateY(0);
        }
        
        .info-box {
            background: linear-gradient(90deg, #e3f2fd, #f3e5f5);
            border-right: 4px solid var(--primary);
            padding: 18px;
            margin: 15px;
            border-radius: 12px;
            font-size: 14px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .info-box i {
            color: var(--primary);
            font-size: 18px;
        }
        
        .owner-panel {
            background: linear-gradient(90deg, #fff3cd, #ffeaa7);
            border: 1px solid #ffd54f;
            padding: 18px;
            margin: 15px;
            border-radius: 12px;
            display: none;
        }
        
        .owner-actions {
            display: flex;
            gap: 10px;
            margin-top: 12px;
            flex-wrap: wrap;
        }
        
        .owner-btn {
            padding: 10px 18px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: all 0.3s;
        }
        
        .clear-btn {
            background: linear-gradient(90deg, var(--danger), #ff6b6b);
            color: white;
        }
        
        .logout-btn {
            background: linear-gradient(90deg, #6c757d, #868e96);
            color: white;
        }
        
        .admin-btn {
            background: linear-gradient(90deg, var(--success), #00b09b);
            color: white;
        }
        
        .login-panel {
            padding: 25px;
            text-align: center;
            background: #f8f9fa;
            margin: 15px;
            border-radius: 12px;
        }
        
        .login-input {
            padding: 15px;
            border: 2px solid #ddd;
            border-radius: 10px;
            width: 100%;
            max-width: 300px;
            margin: 12px 0;
            font-size: 16px;
            text-align: center;
        }
        
        .login-btn {
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            color: white;
            border: none;
            border-radius: 10px;
            padding: 14px 35px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            margin-top: 12px;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            transition: all 0.3s;
        }
        
        .login-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 15px rgba(106, 17, 203, 0.3);
        }
        
        .notification {
            position: fixed;
            top: 25px;
            right: 25px;
            padding: 18px 25px;
            border-radius: 12px;
            color: white;
            font-weight: 600;
            z-index: 10000;
            display: none;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
            animation: slideIn 0.3s ease;
            max-width: 350px;
        }
        
        @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        
        .success {
            background: linear-gradient(90deg, var(--success), #56ab2f);
        }
        
        .error {
            background: linear-gradient(90deg, var(--danger), #ff6b6b);
        }
        
        .warning {
            background: linear-gradient(90deg, var(--warning), #ff9966);
        }
        
        .stats-bar {
            display: flex;
            justify-content: space-around;
            padding: 12px;
            background: #f1f8e9;
            border-top: 1px solid #e0e0e0;
            font-size: 13px;
            color: #555;
        }
        
        .stat-item {
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        
        .stat-value {
            font-weight: bold;
            font-size: 16px;
            color: var(--primary);
        }
        
        .emoji-picker {
            position: absolute;
            bottom: 70px;
            right: 20px;
            background: white;
            border-radius: 10px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.15);
            padding: 10px;
            display: none;
            grid-template-columns: repeat(6, 1fr);
            gap: 5px;
            max-height: 200px;
            overflow-y: auto;
            z-index: 1000;
        }
        
        .emoji {
            padding: 8px;
            cursor: pointer;
            text-align: center;
            border-radius: 5px;
            font-size: 18px;
        }
        
        .emoji:hover {
            background: #f0f0f0;
        }
        
        .emoji-trigger {
            background: none;
            border: none;
            font-size: 22px;
            cursor: pointer;
            padding: 5px 10px;
            color: #666;
        }
        
        @media (max-width: 768px) {
            .container {
                border-radius: 15px;
                margin: 10px;
            }
            
            .chat-container {
                height: 400px;
                padding: 15px;
            }
            
            .message {
                max-width: 90%;
                padding: 10px 15px;
            }
            
            .input-area {
                padding: 15px;
                flex-direction: column;
            }
            
            #sendButton {
                width: 100%;
                justify-content: center;
                height: 55px;
            }
            
            .owner-actions {
                flex-direction: column;
            }
            
            .header h1 {
                font-size: 22px;
            }
            
            .status-indicator {
                position: relative;
                top: 0;
                left: 0;
                margin-bottom: 10px;
                justify-content: center;
            }
        }
        
        /* اسکرول بار زیبا */
        .chat-container::-webkit-scrollbar {
            width: 8px;
        }
        
        .chat-container::-webkit-scrollbar-track {
            background: #f1f1f1;
            border-radius: 4px;
        }
        
        .chat-container::-webkit-scrollbar-thumb {
            background: linear-gradient(var(--primary), var(--secondary));
            border-radius: 4px;
        }
        
        .chat-container::-webkit-scrollbar-thumb:hover {
            background: linear-gradient(var(--secondary), var(--primary));
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="status-indicator">
                <div class="status-dot"></div>
                <span>آنلاین</span>
                <span id="userCount">کاربران: 1</span>
            </div>
            <h1>{{ title }}</h1>
            <p>ارسال پیام به صورت کاملاً ناشناس • فقط مالک می‌تواند همه پیام‌ها را ببیند</p>
        </div>
        
        <div class="info-box">
            <i class="fas fa-info-circle"></i>
            <div>
                <strong>راهنما:</strong> شما به صورت ناشناس در این چت حضور دارید. پیام‌های شما برای سایر کاربران قابل مشاهده نیست و فقط مالک سیستم می‌تواند آن‌ها را ببیند.
            </div>
        </div>
        
        <div id="ownerPanel" class="owner-panel">
            <strong><i class="fas fa-crown"></i> پنل مالک</strong>
            <p>شما به عنوان مالک وارد شده‌اید. می‌توانید تمام پیام‌ها را مشاهده کنید و چت را مدیریت نمایید.</p>
            <div class="owner-actions">
                <button onclick="clearChat()" class="owner-btn clear-btn">
                    <i class="fas fa-trash"></i> پاک کردن چت
                </button>
                <button onclick="window.open('/admin', '_blank')" class="owner-btn admin-btn">
                    <i class="fas fa-cog"></i> پنل مدیریت
                </button>
                <button onclick="logoutOwner()" class="owner-btn logout-btn">
                    <i class="fas fa-sign-out-alt"></i> خروج مالک
                </button>
            </div>
        </div>
        
        <div id="loginPanel" class="login-panel">
            <h3><i class="fas fa-lock"></i> ورود مالک</h3>
            <input type="password" id="ownerPassword" class="login-input" placeholder="رمز مالک را وارد کنید">
            <button onclick="loginAsOwner()" class="login-btn">
                <i class="fas fa-sign-in-alt"></i> ورود به عنوان مالک
            </button>
        </div>
        
        <div class="stats-bar">
            <div class="stat-item">
                <span class="stat-value" id="totalMessages">0</span>
                <span>پیام‌ها</span>
            </div>
            <div class="stat-item">
                <span class="stat-value" id="onlineUsers">1</span>
                <span>کاربران</span>
            </div>
            <div class="stat-item">
                <span class="stat-value" id="lastActive">هم‌اکنون</span>
                <span>آخرین فعالیت</span>
            </div>
        </div>
        
        <div class="chat-container" id="chatContainer">
            <!-- پیام‌ها اینجا نمایش داده می‌شوند -->
        </div>
        
        <div class="input-area">
            <div style="flex: 1; position: relative;">
                <textarea id="messageInput" placeholder="پیام خود را اینجا بنویسید... (حداکثر 500 کاراکتر)" maxlength="500"></textarea>
                <button class="emoji-trigger" onclick="toggleEmojiPicker()">😀</button>
                <div id="emojiPicker" class="emoji-picker">
                    <!-- ایموجی‌ها با JavaScript اضافه می‌شوند -->
                </div>
            </div>
            <button id="sendButton" onclick="sendMessage()">
                <i class="fas fa-paper-plane"></i> ارسال
            </button>
        </div>
    </div>
    
    <div id="notification" class="notification"></div>
    
    <script>
        let isOwner = false;
        let currentUser = "user_" + Math.random().toString(36).substr(2, 9);
        let lastMessageId = 0;
        let onlineUsers = new Set([currentUser]);
        let emojiList = ["😀", "😂", "🥰", "😎", "🤔", "😮", "👍", "👎", "❤️", "🔥", "🎉", "🙏", "🤝", "💪", "✨", "🙈", "💯", "🚀", "🎯", "💡", "⚠️", "❓", "✅", "❌"];
        
        // نمایش اعلان
        function showNotification(message, type = "success") {
            const notification = document.getElementById("notification");
            notification.textContent = message;
            notification.className = `notification ${type}`;
            notification.style.display = "block";
            
            setTimeout(() => {
                notification.style.display = "none";
            }, 4000);
        }
        
        // ورود به عنوان مالک
        function loginAsOwner() {
            const password = document.getElementById("ownerPassword").value;
            
            if (!password) {
                showNotification("لطفا رمز مالک را وارد کنید", "warning");
                return;
            }
            
            fetch("/login_owner", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ password: password })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    isOwner = true;
                    document.getElementById("ownerPanel").style.display = "block";
                    document.getElementById("loginPanel").style.display = "none";
                    showNotification("✅ ورود موفقیت‌آمیز به عنوان مالک", "success");
                    loadMessages();
                    updateStats();
                } else {
                    showNotification("❌ رمز اشتباه است", "error");
                }
            })
            .catch(error => {
                showNotification("❌ خطا در ارتباط با سرور", "error");
                console.error(error);
            });
        }
        
        // خروج مالک
        function logoutOwner() {
            isOwner = false;
            document.getElementById("ownerPanel").style.display = "none";
            document.getElementById("loginPanel").style.display = "block";
            showNotification("با موفقیت خارج شدید", "success");
            loadMessages();
        }
        
        // ارسال پیام
        function sendMessage() {
            const messageInput = document.getElementById("messageInput");
            const message = messageInput.value.trim();
            
            if (!message) {
                showNotification("لطفا پیام خود را وارد کنید", "warning");
                return;
            }
            
            fetch("/send_message", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    message: message,
                    user_id: currentUser,
                    is_owner: isOwner
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    messageInput.value = "";
                    loadMessages();
                    updateStats();
                    showNotification("✅ پیام با موفقیت ارسال شد", "success");
                } else {
                    showNotification("❌ خطا در ارسال پیام: " + data.error, "error");
                }
            })
            .catch(error => {
                showNotification("❌ خطا در ارتباط با سرور", "error");
                console.error(error);
            });
        }
        
        // بارگذاری پیام‌ها
        function loadMessages() {
            fetch("/get_messages?is_owner=" + isOwner + "&last_id=" + lastMessageId + "&user_id=" + currentUser)
            .then(response => response.json())
            .then(data => {
                const chatContainer = document.getElementById("chatContainer");
                
                // فقط اگر مالک است یا پیام جدیدی وجود دارد، نمایش دهد
                if (isOwner || data.messages.length > 0) {
                    // فقط پیام‌های جدید را اضافه کن
                    data.messages.forEach(msg => {
                        if (msg.id > lastMessageId) {
                            const messageDiv = document.createElement("div");
                            messageDiv.className = `message ${msg.sender === "مالک" ? "owner" : "anonymous-user"}`;
                            
                            const senderDiv = document.createElement("div");
                            senderDiv.className = "message-sender";
                            
                            const icon = document.createElement("i");
                            icon.className = msg.sender === "مالک" ? "fas fa-crown" : "fas fa-user-secret";
                            senderDiv.appendChild(icon);
                            
                            const senderText = document.createTextNode(msg.sender);
                            senderDiv.appendChild(senderText);
                            
                            const textDiv = document.createElement("div");
                            textDiv.textContent = msg.text;
                            
                            const timeDiv = document.createElement("div");
                            timeDiv.className = "message-time";
                            timeDiv.textContent = msg.time;
                            
                            messageDiv.appendChild(senderDiv);
                            messageDiv.appendChild(textDiv);
                            messageDiv.appendChild(timeDiv);
                            
                            chatContainer.appendChild(messageDiv);
                            
                            // به‌روزرسانی آخرین شناسه پیام
                            lastMessageId = msg.id;
                        }
                    });
                    
                    // اسکرول به پایین
                    chatContainer.scrollTop = chatContainer.scrollHeight;
                }
                
                // بروزرسانی آمار
                if (data.stats) {
                    document.getElementById("totalMessages").textContent = data.stats.total_messages;
                    document.getElementById("onlineUsers").textContent = data.stats.active_users;
                    document.getElementById("userCount").textContent = `کاربران: ${data.stats.active_users}`;
                    document.getElementById("lastActive").textContent = "هم‌اکنون";
                }
                
                // بروزرسانی خودکار هر 2 ثانیه
                setTimeout(loadMessages, 2000);
            })
            .catch(error => {
                console.error("خطا در بارگذاری پیام‌ها:", error);
                setTimeout(loadMessages, 5000); // اگر خطا داشت، 5 ثانیه بعد دوباره تلاش کن
            });
        }
        
        // آمار را بروزرسانی کن
        function updateStats() {
            fetch("/get_stats")
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    document.getElementById("totalMessages").textContent = data.stats.total_messages;
                    document.getElementById("onlineUsers").textContent = data.stats.active_users;
                }
            });
        }
        
        // پاک کردن چت (فقط مالک)
        function clearChat() {
            if (!isOwner) return;
            
            if (confirm("آیا مطمئن هستید که می‌خواهید تمام پیام‌ها را پاک کنید؟ این عمل قابل برگشت نیست.")) {
                fetch("/clear_chat", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({})
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showNotification("✅ چت با موفقیت پاک شد", "success");
                        lastMessageId = 0;
                        loadMessages();
                        updateStats();
                    }
                });
            }
        }
        
        // ایموجی پیکر
        function toggleEmojiPicker() {
            const picker = document.getElementById("emojiPicker");
            if (picker.style.display === "grid") {
                picker.style.display = "none";
            } else {
                picker.style.display = "grid";
                if (picker.children.length === 0) {
                    emojiList.forEach(emoji => {
                        const emojiSpan = document.createElement("span");
                        emojiSpan.className = "emoji";
                        emojiSpan.textContent = emoji;
                        emojiSpan.onclick = () => {
                            const input = document.getElementById("messageInput");
                            input.value += emoji;
                            picker.style.display = "none";
                            input.focus();
                        };
                        picker.appendChild(emojiSpan);
                    });
                }
            }
        }
        
        // بستن ایموجی پیکر با کلیک بیرون
        document.addEventListener("click", function(event) {
            const picker = document.getElementById("emojiPicker");
            const trigger = document.querySelector(".emoji-trigger");
            if (picker.style.display === "grid" && 
                !picker.contains(event.target) && 
                !trigger.contains(event.target)) {
                picker.style.display = "none";
            }
        });
        
        // ارسال پیام با کلید Enter (بدون Shift)
        document.getElementById("messageInput").addEventListener("keydown", function(e) {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
        
        // وقتی کاربر تایپ می‌کند، آخرین فعالیت را آپدیت کن
        document.getElementById("messageInput").addEventListener("input", function() {
            fetch("/update_activity", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ user_id: currentUser })
            });
        });
        
        // بارگذاری اولیه
        document.addEventListener("DOMContentLoaded", function() {
            loadMessages();
            updateStats();
            
            // ثبت کاربر آنلاین
            fetch("/user_online", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ user_id: currentUser })
            });
            
            // وقتی کاربر صفحه را ترک می‌کند، او را حذف کن
            window.addEventListener("beforeunload", function() {
                fetch("/user_offline", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({ user_id: currentUser }),
                    keepalive: true // درخواست حتی پس از بسته شدن صفحه ارسال شود
                });
            });
            
            // بررسی اینکه آیا مالک قبلاً وارد شده یا نه
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.get('owner') === 'true') {
                document.getElementById("ownerPassword").focus();
            }
            
            // نمایش وب‌هوک status
            fetch("/webhook_status")
            .then(response => response.json())
            .then(data => {
                if (data.webhook_active) {
                    console.log("✅ وب‌هوک فعال است");
                }
            });
        });
    </script>
</body>
</html>
"""

# مسیر اصلی - نمایش چت
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, title=CONFIG["chat_title"])

# ارسال پیام
@app.route('/send_message', methods=['POST'])
def send_message():
    data = request.json
    message_text = data.get('message', '').strip()
    user_id = data.get('user_id', 'anonymous')
    is_owner = data.get('is_owner', False)
    
    if not message_text:
        return jsonify({"success": False, "error": "پیام خالی است"})
    
    if len(message_text) > 500:
        return jsonify({"success": False, "error": "پیام بسیار طولانی است"})
    
    # بررسی IP برای کاربران مسدود شده
    user_ip = request.remote_addr
    chat_data = load_data()
    
    if user_ip in chat_data.get("banned_ips", []):
        return jsonify({"success": False, "error": "شما مسدود شده‌اید"})
    
    # آپدیت فعالیت کاربر
    if "active_users" not in chat_data:
        chat_data["active_users"] = {}
    
    chat_data["active_users"][user_id] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # ایجاد پیام جدید
    new_message = {
        "id": len(chat_data["messages"]) + 1,
        "text": message_text,
        "sender": "مالک" if is_owner else "کاربر ناشناس",
        "time": datetime.now().strftime("%H:%M - %Y/%m/%d"),
        "user_id": user_id,
        "ip": user_ip if not is_owner else "owner",
        "visible_to_owner": True
    }
    
    chat_data["messages"].append(new_message)
    chat_data["stats"]["total_messages"] = len(chat_data["messages"])
    
    # محدود کردن تعداد پیام‌ها
    if len(chat_data["messages"]) > CONFIG["max_messages"]:
        chat_data["messages"] = chat_data["messages"][-CONFIG["max_messages"]:]
    
    save_data(chat_data)
    return jsonify({"success": True})

# دریافت پیام‌ها
@app.route('/get_messages')
def get_messages():
    is_owner = request.args.get('is_owner', 'false') == 'true'
    last_id = int(request.args.get('last_id', 0))
    user_id = request.args.get('user_id', '')
    
    chat_data = load_data()
    
    # آپدیت فعالیت کاربر
    if user_id and user_id != "undefined":
        if "active_users" not in chat_data:
            chat_data["active_users"] = {}
        chat_data["active_users"][user_id] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_data(chat_data)
    
    if is_owner:
        # مالک همه پیام‌ها را می‌بیند
        messages = chat_data["messages"]
    else:
        # کاربران عادی فقط پیام‌های مالک را می‌بینند
        messages = [msg for msg in chat_data["messages"] if msg["sender"] == "مالک"]
    
    # فقط پیام‌های جدیدتر از last_id
    filtered_messages = [msg for msg in messages if msg["id"] > last_id]
    
    # آمار کاربران فعال (آخرین 5 دقیقه)
    active_users = 0
    if "active_users" in chat_data:
        current_time = datetime.now()
        for user_time in chat_data["active_users"].values():
            try:
                user_last_active = datetime.strptime(user_time, "%Y-%m-%d %H:%M:%S")
                if (current_time - user_last_active).seconds < 300:  # 5 دقیقه
                    active_users += 1
            except:
                pass
    
    return jsonify({
        "success": True, 
        "messages": filtered_messages[-50:],  # فقط آخرین 50 پیام
        "stats": {
            "total_messages": len(chat_data["messages"]),
            "active_users": max(active_users, 1)
        }
    })

# ورود مالک
@app.route('/login_owner', methods=['POST'])
def login_owner():
    data = request.json
    password = data.get('password', '')
    
    if password == CONFIG["owner_password"]:
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "error": "رمز اشتباه است"})

# پاک کردن چت (فقط مالک)
@app.route('/clear_chat', methods=['POST'])
def clear_chat():
    chat_data = load_data()
    chat_data["messages"] = []
    chat_data["stats"]["total_messages"] = 0
    save_data(chat_data)
    return jsonify({"success": True})

# دریافت آمار
@app.route('/get_stats')
def get_stats():
    chat_data = load_data()
    
    # محاسبه کاربران فعال
    active_users = 0
    if "active_users" in chat_data:
        current_time = datetime.now()
        for user_time in chat_data["active_users"].values():
            try:
                user_last_active = datetime.strptime(user_time, "%Y-%m-%d %H:%M:%S")
                if (current_time - user_last_active).seconds < 300:  # 5 دقیقه
                    active_users += 1
            except:
                pass
    
    return jsonify({
        "success": True,
        "stats": {
            "total_messages": len(chat_data["messages"]),
            "active_users": max(active_users, 1),
            "start_time": chat_data["stats"].get("start_time", "نامشخص")
        }
    })

# ثبت کاربر آنلاین
@app.route('/user_online', methods=['POST'])
def user_online():
    data = request.json
    user_id = data.get('user_id', '')
    
    if user_id:
        chat_data = load_data()
        if "active_users" not in chat_data:
            chat_data["active_users"] = {}
        
        chat_data["active_users"][user_id] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_data(chat_data)
    
    return jsonify({"success": True})

# ثبت کاربر آفلاین
@app.route('/user_offline', methods=['POST'])
def user_offline():
    data = request.json
    user_id = data.get('user_id', '')
    
    if user_id:
        chat_data = load_data()
        if "active_users" in chat_data and user_id in chat_data["active_users"]:
            del chat_data["active_users"][user_id]
            save_data(chat_data)
    
    return jsonify({"success": True})

# آپدیت فعالیت کاربر
@app.route('/update_activity', methods=['POST'])
def update_activity():
    data = request.json
    user_id = data.get('user_id', '')
    
    if user_id:
        chat_data = load_data()
        if "active_users" not in chat_data:
            chat_data["active_users"] = {}
        
        chat_data["active_users"][user_id] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_data(chat_data)
    
    return jsonify({"success": True})

# وضعیت وب‌هوک
@app.route('/webhook_status')
def webhook_status():
    return jsonify({
        "webhook_active": bool(RENDER_WEBHOOK_URL),
        "last_ping": load_data().get("last_webhook", "هرگز")
    })

# پنل مدیریت مالک
@app.route('/admin')
def admin_panel():
    admin_html = """
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>پنل مدیریت مالک</title>
        <style>
            body { 
                font-family: 'Vazirmatn', Tahoma; 
                padding: 20px; 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                margin: 0;
            }
            .container { 
                max-width: 1200px; 
                margin: auto; 
                background: white; 
                padding: 30px; 
                border-radius: 15px;
                box-shadow: 0 15px 35px rgba(0, 0, 0, 0.2);
            }
            h1 {
                color: #333;
                border-bottom: 3px solid #667eea;
                padding-bottom: 10px;
                margin-top: 0;
            }
            .card {
                background: #f8f9fa;
                border-radius: 10px;
                padding: 20px;
                margin-bottom: 20px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.05);
            }
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 20px;
                margin: 20px 0;
            }
            .stat-box {
                background: white;
                border-radius: 10px;
                padding: 20px;
                text-align: center;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
                border-top: 4px solid #667eea;
            }
            .stat-value {
                font-size: 32px;
                font-weight: bold;
                color: #667eea;
                margin: 10px 0;
            }
            table { 
                width: 100%; 
                border-collapse: collapse; 
                margin-top: 20px; 
                background: white;
                border-radius: 10px;
                overflow: hidden;
                box-shadow: 0 5px 15px rgba(0,0,0,0.05);
            }
            th, td { 
                border: 1px solid #ddd; 
                padding: 12px; 
                text-align: right; 
            }
            th { 
                background: linear-gradient(90deg, #667eea, #764ba2);
                color: white; 
                font-weight: 600;
            }
            tr:nth-child(even) {
                background-color: #f8f9fa;
            }
            .btn { 
                padding: 10px 20px; 
                background: linear-gradient(90deg, #667eea, #764ba2);
                color: white; 
                border: none; 
                border-radius: 8px; 
                cursor: pointer; 
                font-weight: 600;
                transition: all 0.3s;
                display: inline-flex;
                align-items: center;
                gap: 8px;
            }
            .btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 8px 20px rgba(102, 126, 234, 0.3);
            }
            .btn-danger {
                background: linear-gradient(90deg, #ff416c, #ff4b2b);
            }
            .btn-success {
                background: linear-gradient(90deg, #00b09b, #96c93d);
            }
            .action-buttons {
                display: flex;
                gap: 10px;
                margin: 20px 0;
                flex-wrap: wrap;
            }
            .form-group {
                margin: 15px 0;
            }
            input[type="password"] {
                padding: 12px;
                border: 2px solid #ddd;
                border-radius: 8px;
                width: 300px;
                font-size: 16px;
            }
            .webhook-status {
                padding: 15px;
                border-radius: 8px;
                margin: 15px 0;
                display: flex;
                align-items: center;
                gap: 10px;
            }
            .webhook-active {
                background: #d4edda;
                color: #155724;
                border: 1px solid #c3e6cb;
            }
            .webhook-inactive {
                background: #f8d7da;
                color: #721c24;
                border: 1px solid #f5c6cb;
            }
            @media (max-width: 768px) {
                .container {
                    padding: 15px;
                }
                .stats-grid {
                    grid-template-columns: 1fr;
                }
                table {
                    font-size: 14px;
                }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1><i class="fas fa-crown"></i> پنل مدیریت مالک</h1>
            <p><a href="/" class="btn"><i class="fas fa-arrow-right"></i> بازگشت به چت</a></p>
            <hr>
            
            <div class="webhook-status {{ 'webhook-active' if webhook_active else 'webhook-inactive' }}">
                <i class="fas {{ 'fa-check-circle' if webhook_active else 'fa-exclamation-circle' }}"></i>
                <div>
                    <strong>وضعیت وب‌هوک:</strong> 
                    {{ 'فعال' if webhook_active else 'غیرفعال' }}
                    {% if last_ping and webhook_active %}
                    <br><small>آخرین ارسال: {{ last_ping }}</small>
                    {% endif %}
                </div>
            </div>
            
            <div class="stats-grid">
                <div class="stat-box">
                    <div><i class="fas fa-comments"></i></div>
                    <div class="stat-value">{{ total_messages }}</div>
                    <div>کل پیام‌ها</div>
                </div>
                <div class="stat-box">
                    <div><i class="fas fa-users"></i></div>
                    <div class="stat-value">{{ active_users }}</div>
                    <div>کاربران فعال</div>
                </div>
                <div class="stat-box">
                    <div><i class="fas fa-calendar"></i></div>
                    <div class="stat-value">{{ start_date }}</div>
                    <div>شروع سیستم</div>
                </div>
                <div class="stat-box">
                    <div><i class="fas fa-shield-alt"></i></div>
                    <div class="stat-value">{{ banned_count }}</div>
                    <div>کاربران مسدود</div>
                </div>
            </div>
            
            <div class="action-buttons">
                <button onclick="clearChat()" class="btn btn-danger">
                    <i class="fas fa-trash"></i> پاک کردن تمام پیام‌ها
                </button>
                <button onclick="pingWebhook()" class="btn btn-success">
                    <i class="fas fa-sync"></i> ارسال وب‌هوک دستی
                </button>
                <button onclick="exportData()" class="btn">
                    <i class="fas fa-download"></i> خروجی JSON
                </button>
            </div>
            
            <div class="card">
                <h3>IPهای فعال اخیر</h3>
                <table>
                    <thead>
                        <tr>
                            <th>IP</th>
                            <th>تعداد پیام</th>
                            <th>آخرین فعالیت</th>
                            <th>عملیات</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for ip, info in ip_stats.items() %}
                        <tr>
                            <td>{{ ip }}</td>
                            <td>{{ info.count }}</td>
                            <td>{{ info.last_seen }}</td>
                            <td>
                                <button onclick="banIP('{{ ip }}')" class="btn btn-danger" style="padding: 6px 12px; font-size: 12px;">
                                    <i class="fas fa-ban"></i> مسدود
                                </button>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            
            <div class="card">
                <h3>پیام‌های اخیر</h3>
                <table>
                    <thead>
                        <tr>
                            <th>زمان</th>
                            <th>فرستنده</th>
                            <th>پیام</th>
                            <th>IP</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for msg in recent_messages %}
                        <tr>
                            <td>{{ msg.time }}</td>
                            <td>{{ msg.sender }}</td>
                            <td>{{ msg.text[:50] }}{% if msg.text|length > 50 %}...{% endif %}</td>
                            <td>{{ msg.ip }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            
            <div class="card">
                <h3>کاربران فعال (۵ دقیقه اخیر)</h3>
                <table>
                    <thead>
                        <tr>
                            <th>شناسه کاربر</th>
                            <th>آخرین فعالیت</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for user_id, last_active in active_users_list %}
                        <tr>
                            <td>{{ user_id[:15] }}...</td>
                            <td>{{ last_active }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        
        <script>
            function clearChat() {
                if (confirm('آیا مطمئن هستید که می‌خواهید تمام پیام‌ها را پاک کنید؟')) {
                    fetch('/clear_chat', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'}
                    }).then(r => r.json()).then(data => {
                        if (data.success) {
                            alert('پیام‌ها با موفقیت پاک شدند');
                            location.reload();
                        }
                    });
                }
            }
            
            function banIP(ip) {
                if (confirm('آیا از مسدود کردن ' + ip + ' مطمئنید؟')) {
                    fetch('/ban_ip', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ip: ip})
                    }).then(r => r.json()).then(data => {
                        if (data.success) {
                            alert('IP مسدود شد');
                            location.reload();
                        }
                    });
                }
            }
            
            function pingWebhook() {
                fetch('/ping_webhook', {
                    method: 'POST'
                }).then(r => r.json()).then(data => {
                    if (data.success) {
                        alert('وب‌هوک ارسال شد: ' + data.message);
                        location.reload();
                    }
                });
            }
            
            function exportData() {
                window.open('/export_data', '_blank');
            }
        </script>
    </body>
    </html>
    """
    
    chat_data = load_data()
    
    # آمار IPها
    ip_stats = {}
    for msg in chat_data["messages"]:
        ip = msg.get("ip", "unknown")
        if ip != "owner":
            if ip not in ip_stats:
                ip_stats[ip] = {"count": 0, "last_seen": msg["time"]}
            ip_stats[ip]["count"] += 1
            ip_stats[ip]["last_seen"] = msg["time"]
    
    # کاربران فعال
    active_users_list = []
    if "active_users" in chat_data:
        current_time = datetime.now()
        for user_id, user_time in chat_data["active_users"].items():
            try:
                user_last_active = datetime.strptime(user_time, "%Y-%m-%d %H:%M:%S")
                if (current_time - user_last_active).seconds < 300:  # 5 دقیقه
                    active_users_list.append((user_id, user_time))
            except:
                pass
    
    from flask import render_template_string
    return render_template_string(admin_html, 
                                 total_messages=len(chat_data["messages"]),
                                 active_users=len(active_users_list),
                                 start_date=chat_data["stats"].get("start_time", "نامشخص").split()[0],
                                 banned_count=len(chat_data.get("banned_ips", [])),
                                 ip_stats=ip_stats,
                                 recent_messages=chat_data["messages"][-20:],
                                 active_users_list=active_users_list[:20],
                                 webhook_active=bool(RENDER_WEBHOOK_URL),
                                 last_ping=chat_data.get("last_webhook", "هرگز"))

# مسدود کردن IP
@app.route('/ban_ip', methods=['POST'])
def ban_ip():
    data = request.json
    ip_to_ban = data.get('ip', '')
    
    if not ip_to_ban:
        return jsonify({"success": False})
    
    chat_data = load_data()
    
    if "banned_ips" not in chat_data:
        chat_data["banned_ips"] = []
    
    if ip_to_ban not in chat_data["banned_ips"]:
        chat_data["banned_ips"].append(ip_to_ban)
    
    save_data(chat_data)
    return jsonify({"success": True})

# ارسال وب‌هوک دستی
@app.route('/ping_webhook', methods=['POST'])
def ping_webhook_manual():
    if RENDER_WEBHOOK_URL:
        try:
            response = requests.get(RENDER_WEBHOOK_URL, timeout=10)
            
            # ذخیره زمان آخرین وب‌هوک
            chat_data = load_data()
            chat_data["last_webhook"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_data(chat_data)
            
            return jsonify({"success": True, "message": f"وب‌هوک ارسال شد (وضعیت: {response.status_code})"})
        except Exception as e:
            return jsonify({"success": False, "message": f"خطا: {str(e)}"})
    else:
        return jsonify({"success": False, "message": "URL وب‌هوک تنظیم نشده است"})

# خروجی داده‌ها
@app.route('/export_data')
def export_data():
    chat_data = load_data()
    from flask import Response
    return Response(
        json.dumps(chat_data, ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={"Content-disposition": "attachment; filename=chat_data.json"}
    )

# مسیر سلامت برای Render
@app.route('/health')
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "webhook_active": bool(RENDER_WEBHOOK_URL),
        "message_count": len(load_data()["messages"])
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    print("=" * 70)
    print("🤖 ربات چت ناشناس با وب‌هوک Render")
    print("=" * 70)
    print(f"🌐 دسترسی: http://localhost:{port}")
    print(f"🔐 پنل مدیریت: http://localhost:{port}/admin")
    print(f"🔑 رمز مالک: {CONFIG['owner_password']}")
    print(f"🔄 وب‌هوک: {'فعال ✅' if RENDER_WEBHOOK_URL else 'غیرفعال ❌'}")
    if RENDER_WEBHOOK_URL:
        print(f"   ارسال هر {WEBHOOK_INTERVAL//60} دقیقه")
    print("=" * 70)
    print("برای توقف ربات: Ctrl+C")
    
    app.run(host='0.0.0.0', port=port, debug=False)
