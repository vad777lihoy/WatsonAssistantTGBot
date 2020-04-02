import os
import logging
import ibm_watson
import httplib2
import json
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
from telegram.ext import CommandHandler
from telegram.ext import MessageHandler, Filters
from telegram.ext import Updater, CallbackQueryHandler
from telegram import ReplyKeyboardMarkup, ReplyMarkup, InlineKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton
from telegram.chataction import ChatAction
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_cloud_sdk_core.api_exception import ApiException
from  googleapiclient.discovery import build
from oauth2client.service_account import ServiceAccountCredentials

SAVED_INTENT = None

# Google Sheets config
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SHEET_ID = '0'
SPREADSHEET_ID = '19Ql673P0DGGIllL-S-t-UmqazfskTzUg9k8iWJIyX4c'
CREDENTIALS_FILE = 'credentials.json'

# .env params
load_dotenv()
assistant_id = os.getenv('ASSISTANT_ID')
apikey = os.getenv('APIKEY')
token = os.getenv('TOKEN')
url = os.getenv('URL')

# Emoji
heart_icon = u'\U00002764'
dislike_icon = u'\U0001F44E'

# Logging config
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

# Google Sheets auth
credentials = ServiceAccountCredentials.from_json_keyfile_name(
    CREDENTIALS_FILE,
    [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
)
httpAuth = credentials.authorize(httplib2.Http())

google_sheets_service = build('sheets', 'v4', http = httpAuth)

batch_update_spreadsheet_request_body = {
    'requests': {
        'appendCells': {
            'sheetId': SHEET_ID,
            'rows': [],
            'fields': '*'
        }
    },
}

# Watson Assistant auth
authenticator = IAMAuthenticator(apikey)
service = ibm_watson.AssistantV2(
    version='2019-02-28',
    authenticator=authenticator)

service.set_service_url(url)

feedback_button_list = [[
    InlineKeyboardButton(heart_icon, callback_data='like'),
    InlineKeyboardButton(dislike_icon, callback_data='dislike')
]]

user_data = {}

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
# updater = Updater(token=token, use_context=True, request_kwargs=REQUEST_KWARGS)
updater = Updater(token=token, use_context=True)
dispatcher = updater.dispatcher

def returnCellData(s):
    return {
        'userEnteredValue': {
            'stringValue': s
        },
    }

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
            else:
                reply_text += "Я вас не понял. Попробуйте пожалуйста перефразировать вопрос и я очень постараюсь вас " \
                              "понять. "

            if 'intents' in response['output'].keys():
                if len(response['output']['intents']) > 0:
                    SAVED_INTENT = response['output']['intents'][0]['intent']

        button_list = [[s] for s in labels]
    except IndexError:
        reply_text = 'Watson Assistant is unavailable now :('
    except KeyError:
        reply_text = 'Ошибка обработки текста'

    if len(button_list) > 0:
        reply_markup = ReplyKeyboardMarkup(button_list, one_time_keyboard=True)
    else:
        reply_markup = InlineKeyboardMarkup(feedback_button_list)
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
    input_text = update.message.text

    if user_id not in user_data:
        new_session(user_id)
    resp_input = {'text': input_text}

    user_data[user_id]['input'] = input_text
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

def feedback_callback(update, context):
    global SAVED_INTENT
    query = update.callback_query
    user_id = query.from_user.id

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_name = query.from_user.full_name
    text = query.message.text
    user_input = None

    if (user_id in user_data.keys() and 'input' in user_data[user_id].keys()):
        user_input = user_data[user_id]['input']

    batch_update_spreadsheet_request_body['requests']['appendCells']['rows'].append({
        'values': [
            returnCellData(timestamp),
            returnCellData(full_name),
            returnCellData(user_input),
            returnCellData(text),
            returnCellData(SAVED_INTENT),
            returnCellData(query.data)
        ]
    })

    #pylint: disable=no-member
    google_sheets_service.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body=batch_update_spreadsheet_request_body).execute()
    batch_update_spreadsheet_request_body['requests']['appendCells']['rows'] = []

start_handler = CommandHandler('start', start)
dispatcher.add_handler(start_handler)

help_handler = CommandHandler('help', help_user)
dispatcher.add_handler(help_handler)

unknown_handler = MessageHandler(Filters.command, unknown)
dispatcher.add_handler(unknown_handler)

message_handler = MessageHandler(Filters.text, wa_reply)
dispatcher.add_handler(message_handler)

dispatcher.add_handler(CallbackQueryHandler(feedback_callback))

updater.start_polling()
