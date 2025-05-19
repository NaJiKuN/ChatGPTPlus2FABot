import os
import random
import time
from threading import Thread
from telegram import Bot, Update
from telegram.ext import CommandHandler, Updater

# Configuration
BOT_TOKEN = "8119053401:AAHuqgTkiq6M8rT9VSHYEnIl96BHt9lXIZM"
CHAT_ID = -1002329495586
SETUP_KEY = "ZV3YUXYVPOZSUOT43SKVDGFFVWBZXOVI"
INTERVAL = 600  # 10 minutes in seconds

class TwoFactorAuthBot:
    def __init__(self):
        self.bot = Bot(token=BOT_TOKEN)
        self.updater = Updater(token=BOT_TOKEN, use_context=True)
        self.dispatcher = self.updater.dispatcher
        self.running = False
        self.thread = None

        # Add command handlers
        start_handler = CommandHandler('start', self.start)
        setup_handler = CommandHandler('setup', self.setup)
        stop_handler = CommandHandler('stop', self.stop)
        
        self.dispatcher.add_handler(start_handler)
        self.dispatcher.add_handler(setup_handler)
        self.dispatcher.add_handler(stop_handler)

    def start(self, update: Update, context):
        """Send a welcome message when the command /start is issued."""
        welcome_message = (
            "🤖 *Welcome to ChatGPTPlus2FA Bot*\n\n"
            "This bot automatically generates and sends 2FA codes every 10 minutes.\n\n"
            "To set up the bot, use the /setup command followed by your setup key.\n"
            "Example: `/setup YOUR_SETUP_KEY`\n\n"
            "Use /stop to pause the automatic code generation."
        )
        context.bot.send_message(chat_id=update.effective_chat.id, 
                                text=welcome_message, 
                                parse_mode='Markdown')

    def setup(self, update: Update, context):
        """Start the automatic code generation with the provided setup key."""
        if len(context.args) < 1:
            update.message.reply_text("Please provide your setup key. Usage: /setup YOUR_SETUP_KEY")
            return

        user_key = context.args[0]
        if user_key != SETUP_KEY:
            update.message.reply_text("❌ Invalid setup key. Please try again.")
            return

        if self.running:
            update.message.reply_text("✅ Bot is already running and generating codes.")
            return

        self.running = True
        self.thread = Thread(target=self.generate_and_send_codes)
        self.thread.start()
        update.message.reply_text("✅ Setup successful! 2FA codes will be sent every 10 minutes.")

    def stop(self, update: Update, context):
        """Stop the automatic code generation."""
        if not self.running:
            update.message.reply_text("⚠️ The bot is not currently running.")
            return

        self.running = False
        if self.thread:
            self.thread.join()
        update.message.reply_text("⏸️ Automatic code generation has been stopped.")

    def generate_code(self):
        """Generate a random 6-digit code."""
        return str(random.randint(100000, 999999))

    def send_code_message(self, code):
        """Send the code message to the specified chat."""
        message = (
            "🔑 *New Authentication Code Received*\n\n"
            "You have received a new authentication code.\n\n"
            f"`{code}`\n\n"
            "*This code is valid for the next 10 minutes. Please use it promptly.*"
        )
        self.bot.send_message(chat_id=CHAT_ID, 
                             text=message, 
                             parse_mode='Markdown')

    def generate_and_send_codes(self):
        """Continuously generate and send codes every 10 minutes."""
        while self.running:
            code = self.generate_code()
            self.send_code_message(code)
            
            # Wait for the interval, checking every second if we should stop
            for _ in range(INTERVAL):
                if not self.running:
                    return
                time.sleep(1)

    def run(self):
        """Start the bot."""
        self.updater.start_polling()
        self.updater.idle()

if __name__ == '__main__':
    auth_bot = TwoFactorAuthBot()
    auth_bot.run()
