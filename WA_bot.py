import os
import logging
import ibm_watson
import json
from functools import wraps
from dotenv import load_dotenv
from telegram.ext import CommandHandler
from telegram.ext import MessageHandler, Filters
from telegram.ext import Updater
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.chataction import ChatAction
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_cloud_sdk_core.api_exception import ApiException

SAVED_INTENT = None

# REQUEST_KWARGS = {
#     'proxy_url': 'socks5://grsst.s5.opennetwork.cc:999/',
#     # Optional, if you need authentication:
#     'urllib3_proxy_kwargs': {
#         'assert_hostname': 'False',
#         'cert_reqs': 'CERT_NONE',
#         'username': '125145015',
#         'password': 'xupI2fev'
#     }
# }

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

user_data = {}

# updater = Updater(token=os.getenv('TOKEN'), use_context=True, request_kwargs=REQUEST_KWARGS)
updater = Updater(token=os.getenv('TOKEN'), use_context=True)
dispatcher = updater.dispatcher


def parse_response(response):
    global SAVED_INTENT
    reply_text = ''
    labels = []
    button_list = []
    try:
        for response_part in response['output']['generic']:
            if response_part['response_type'] == 'text':
                reply_text += response_part['text'] + '\n'
            elif response_part['response_type'] == 'option':
                reply_text += response_part['title']
                if 'description' in response_part:
                    reply_text += '\n' + response_part['description']
                labels = [option['label'] for option in response_part['options']]
            elif response_part['response_type'] == 'suggestion':
                reply_text += response_part['title']
                labels = [suggestion['label'] for suggestion in response_part['suggestions']]
                intents = [suggestion['value']['input']['intents'] for suggestion in response_part['suggestions']]
                confs = [float(intent[0]['confidence']) if intent != [] else 0 for intent in intents]
                labels_confs = [(label, conf) for label, conf in zip(labels, confs)]
                labels_confs = sorted(labels_confs, key=lambda x: x[1], reverse=True)
                labels = [label_conf[0] for label_conf in labels_confs]

                # if 'intents' in response['output'].keys():
                #     if len(response['output']['intents']) > 0:
                #         SAVED_INTENT = response['output']['intents'][0]['intent']
            else:
                reply_text += "Я вас не понял. Попробуйте пожалуйста перефразировать вопрос и я очень постараюсь вас " \
                              "понять. "
        button_list = [[s] for s in labels]
    except IndexError:
        reply_text = 'Watson Assistant is unavailable now :('
    except KeyError:
        reply_text = 'Ошибка обработки текста'

    if len(button_list) > 0:
        reply_markup = ReplyKeyboardMarkup(button_list)
    else:
        reply_markup = ReplyKeyboardRemove()
    return reply_text, reply_markup


def send_action(action):
    def decorator(func):
        @wraps(func)
        def command_func(update, context, *args, **kwargs):
            context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action=action)
            return func(update, context, *args, **kwargs)

        return command_func

    return decorator


def new_session(user_id):
    assistant_session_id = service.create_session(
        assistant_id=assistant_id
    ).get_result()['session_id']
    user_data[user_id] = {}
    user_data[user_id]['session'] = assistant_session_id
    user_data[user_id]['wa_reply'] = None


@send_action(ChatAction.TYPING)
def start(update, context):
    user_id = update.message.from_user.id
    new_session(user_id)
    response = service.message(
        assistant_id,
        user_data[user_id]['session']
    ).get_result()
    with open('log.json', 'w') as f:
        f.write(str(json.dumps(response, indent=4, ensure_ascii=False, )))
    reply_text, reply_markup = parse_response(response)
    context.bot.send_message(chat_id=update.effective_chat.id, text=reply_text, reply_markup=reply_markup)
    # context.bot.send_message(chat_id=update.effective_chat.id, text='Помощь: /help')


@send_action(ChatAction.TYPING)
def help_user(update, context):
    help_message = "Команды бота:\nПомощь: /help\nНачало диалога: /start\nПосле отправки команды /start создается " \
                   "новая сессия с ботом. "
    context.bot.send_message(chat_id=update.effective_chat.id, text=help_message)


@send_action(ChatAction.TYPING)
def wa_reply(update, context):
    global SAVED_INTENT
    user_id = update.message.from_user.id
    if user_id not in user_data:
        new_session(user_id)
    resp_input = {'text': update.message.text}
    if user_data[user_id]['wa_reply'] is not None:
        for suggestion in user_data[user_id]['wa_reply']:
            if update.message.text == suggestion['label'] and suggestion['value']['input']['intents'] != []:
                resp_input = {'text': update.message.text,
                              'intents': [
                                  {'intent': suggestion['value']['input']['intents'][0]['intent'], 'confidence': 1.}]}
        user_data[user_id]['wa_reply'] = None

    try:
        # if SAVED_INTENT is not None:
        #     resp_input = {'text': update.message.text, 'intents': [{'intent': SAVED_INTENT, 'confidence': 1.}]}
        #     SAVED_INTENT = None
        response = service.message(
            assistant_id,
            user_data[user_id]['session'],
            input=resp_input,
        ).get_result()
        if response['output']['generic'][0]['response_type'] == 'suggestion':
            user_data[user_id]['wa_reply'] = response['output']['generic'][0]['suggestions']
        with open('log.json', 'w') as f:
            f.write(str(json.dumps(response, indent=4, ensure_ascii=False, )))
    except ApiException:
        new_session(user_id)
        response = service.message(assistant_id, user_data[user_id]['session'],
                                   input={'text': update.message.text}).get_result()

    logger.debug(response)
    reply_text, reply_markup = parse_response(response)
    context.bot.send_message(chat_id=update.effective_chat.id, text=reply_text, reply_markup=reply_markup)


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
