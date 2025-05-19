import os
import random
import time
import logging
from threading import Thread
from telegram import Bot, Update
from telegram.ext import CommandHandler, Updater

# إعدادات التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration (يُفضل استخدام متغيرات البيئة)
BOT_TOKEN = os.getenv('BOT_TOKEN', "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM")
CHAT_ID = int(os.getenv('CHAT_ID', "-1002329495586"))
SETUP_KEY = os.getenv('SETUP_KEY', "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI")
INTERVAL = 600  # 10 minutes in seconds

class TwoFactorAuthBot:
    def __init__(self):
        try:
            self.bot = Bot(token=BOT_TOKEN)
            # إعداد Updater مع معلمات لمنع التعارضات
            self.updater = Updater(
                token=BOT_TOKEN,
                use_context=True,
                workers=1,  # عامل واحد فقط
                request_kwargs={'read_timeout': 10, 'connect_timeout': 10}
            )
            
            # حذف التحديثات المعلقة لتفادي التعارض
            self.updater.dispatcher.bot.delete_webhook(drop_pending_updates=True)
            
            self.dispatcher = self.updater.dispatcher
            self.running = False
            self.thread = None

            # إضافة معالجات الأوامر
            start_handler = CommandHandler('start', self.start)
            setup_handler = CommandHandler('setup', self.setup)
            stop_handler = CommandHandler('stop', self.stop)
            
            self.dispatcher.add_handler(start_handler)
            self.dispatcher.add_handler(setup_handler)
            self.dispatcher.add_handler(stop_handler)
            
            logger.info("Bot initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing bot: {e}")
            raise

    def start(self, update: Update, context):
        """إرسال رسالة ترحيبية عند استخدام الأمر /start"""
        try:
            welcome_message = (
                "🤖 *مرحبًا بك في بوت ChatGPTPlus2FA*\n\n"
                "هذا البوت يولد ويرسل رموز المصادقة الثنائية تلقائيًا كل 10 دقائق.\n\n"
                "لإعداد البوت، استخدم الأمر /setup متبوعًا بمفتاح الإعداد.\n"
                "مثال: `/setup YOUR_SETUP_KEY`\n\n"
                "استخدم /stop لإيقاف توليد الرموز التلقائي."
            )
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=welcome_message,
                parse_mode='Markdown'
            )
            logger.info("Sent welcome message")
        except Exception as e:
            logger.error(f"Error in start command: {e}")

    def setup(self, update: Update, context):
        """بدء توليد الرموز التلقائي بالمفتاح الصحيح"""
        try:
            if len(context.args) < 1:
                update.message.reply_text("الرجاء تقديم مفتاح الإعداد. الاستخدام: /setup YOUR_SETUP_KEY")
                return

            user_key = context.args[0]
            if user_key != SETUP_KEY:
                update.message.reply_text("❌ مفتاح إعداد غير صحيح. الرجاء المحاولة مرة أخرى.")
                return

            if self.running:
                update.message.reply_text("✅ البوت يعمل بالفعل ويولد الرموز.")
                return

            self.running = True
            self.thread = Thread(target=self.generate_and_send_codes)
            self.thread.daemon = True  # لجعل الخيط ينتهي مع انتهاء البرنامج
            self.thread.start()
            update.message.reply_text("✅ تم الإعداد بنجاح! سيتم إرسال رموز 2FA كل 10 دقائق.")
            logger.info("2FA code generation started")
        except Exception as e:
            logger.error(f"Error in setup command: {e}")

    def stop(self, update: Update, context):
        """إيقاف توليد الرموز التلقائي"""
        try:
            if not self.running:
                update.message.reply_text("⚠️ البوت ليس قيد التشغيل حاليًا.")
                return

            self.running = False
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=5)
            update.message.reply_text("⏸️ تم إيقاف توليد الرموز التلقائي.")
            logger.info("2FA code generation stopped")
        except Exception as e:
            logger.error(f"Error in stop command: {e}")

    def generate_code(self):
        """توليد رمز عشوائي مكون من 6 أرقام"""
        return str(random.randint(100000, 999999))

    def send_code_message(self, code):
        """إرسال رسالة الرمز إلى الدردشة المحددة"""
        try:
            message = (
                "🔑 *تم استلام رمز مصادقة جديد*\n\n"
                "لقد تلقيت رمز مصادقة جديد.\n\n"
                f"`{code}`\n\n"
                "*هذا الرمز صالح للاستخدام خلال الـ 10 دقائق القادمة. يرجى استخدامه فورًا.*"
            )
            self.bot.send_message(
                chat_id=CHAT_ID,
                text=message,
                parse_mode='Markdown'
            )
            logger.info(f"Sent 2FA code: {code}")
        except Exception as e:
            logger.error(f"Error sending code message: {e}")

    def generate_and_send_codes(self):
        """توليد وإرسال الرموز كل 10 دقائق"""
        logger.info("Starting automatic code generation loop")
        while self.running:
            try:
                code = self.generate_code()
                self.send_code_message(code)
                
                # الانتظار للمدة المحددة مع التحقق من الاستمرارية
                for _ in range(INTERVAL):
                    if not self.running:
                        logger.info("Stopping code generation as requested")
                        return
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Error in code generation loop: {e}")
                time.sleep(10)  # انتظر قبل إعادة المحاولة

    def run(self):
        """تشغيل البوت"""
        try:
            logger.info("Starting bot polling...")
            self.updater.start_polling(
                poll_interval=1,
                timeout=10,
                drop_pending_updates=True
            )
            self.updater.idle()
        except Exception as e:
            logger.error(f"Error in bot run: {e}")
        finally:
            self.running = False
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=
