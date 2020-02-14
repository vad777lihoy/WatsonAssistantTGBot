import os
import logging
import ibm_watson
from dotenv import load_dotenv
from telegram.ext import CommandHandler
from telegram.ext import MessageHandler, Filters
from telegram.ext import Updater
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator

load_dotenv()
assistant_id = os.getenv('ASSISTANT_ID')
apikey = os.getenv('APIKEY')

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

authenticator = IAMAuthenticator(apikey)
service = ibm_watson.AssistantV2(
    version='2019-02-28',
    authenticator=authenticator)

service.set_service_url(os.getenv('URL'))

users = {}

updater = Updater(token=os.getenv('TOKEN'), use_context=True)
dispatcher = updater.dispatcher


def start(update, context):
    user_id = update.message.from_user.id
    assistant_session_id = service.create_session(
        assistant_id=assistant_id
    ).get_result()['session_id']
    users[user_id] = assistant_session_id
    response = service.message(
        assistant_id,
        assistant_session_id
    ).get_result()
    reply_text = ''
    try:
        reply_text = response['output']['generic'][0]['text']
    except IndexError:
        reply_text = 'Watson Assistant is unavailable now :('
    context.bot.send_message(chat_id=update.effective_chat.id, text=reply_text)
    context.bot.send_message(chat_id=update.effective_chat.id, text='Помощь: /help')


def help_user(update, context):
    help_message = """
    Команды бота:
    Помощь: /help
    Начало диалога: /start\n
    
    После отправки команды /start создается сессия с Watson Assistant.
    Сессия существует 5 минут, поэтому  после разговора для нового разговора необходимо ввести команду /start
    Исправление в разработке.
    """
    context.bot.send_message(chat_id=update.effective_chat.id, text=help_message)


def wa_reply(update, context):
    user_id = update.message.from_user.id
    if user_id not in users:
        assistant_session_id = service.create_session(
            assistant_id=assistant_id
        ).get_result()['session_id']
        users[user_id] = assistant_session_id
    response = service.message(
        assistant_id,
        users[user_id],
        input={'text': update.message.text}
    ).get_result()
    logger.debug(response)
    reply_text = ''
    try:
        if response['output']['generic'][0]['response_type'] == 'text':
            for line in response['output']['generic']:
                reply_text += line['text'] + '\n'
        elif response['output']['generic'][0]['title']:
            reply_text = response['output']['generic'][0]['title']
    except IndexError:
        reply_text = 'Watson Assistant is unavailable now :('

    context.bot.send_message(chat_id=update.effective_chat.id, text=reply_text)


def unknown(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, I didn't understand that command.")


start_handler = CommandHandler('start', start)
dispatcher.add_handler(start_handler)

help_handler = CommandHandler('help', help_user)
dispatcher.add_handler(help_handler)

unknown_handler = MessageHandler(Filters.command, unknown)
dispatcher.add_handler(unknown_handler)

message_handler = MessageHandler(Filters.text, wa_reply)
dispatcher.add_handler(message_handler)

updater.start_polling()
# updater.idle()
