from flask import Flask, jsonify
import os
import threading
import time

app = Flask(__name__)

# تابع برای اجرای ربات تلگرام
def run_telegram_bot():
    """اجرای ربات تلگرام در یک ترد جدا"""
    try:
        from main import main
        main()
    except Exception as e:
        print(f"خطا در اجرای ربات تلگرام: {e}")

@app.route('/')
def home():
    return jsonify({
        "status": "running",
        "service": "mother-bot",
        "message": "ربات مادر ساخت ربات چت ناشناس"
    })

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": time.time()
    })

@app.route('/status')
def status():
    return jsonify({
        "status": "active",
        "telegram": "running" if 'MOTHER_BOT_TOKEN' in os.environ else "not_configured"
    })

if __name__ == '__main__':
    # شروع ربات تلگرام در ترد جداگانه
    bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()
    
    # شروع وب سرور Flask
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
