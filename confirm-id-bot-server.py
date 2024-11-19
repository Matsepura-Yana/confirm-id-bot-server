import logging
from telethon import TelegramClient, events
from telethon.errors import RPCError
from quart import Quart, request, jsonify
from quart_cors import cors
import asyncio
import re
import os
from dotenv import load_dotenv

# Логирование
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

load_dotenv()

# Конфигурация Telegram API
api_id = int(os.getenv("TELEGRAM_API_ID"))
api_hash = os.getenv("TELEGRAM_API_HASH")
bot_username = os.getenv("TELEGRAM_BOT_USERNAME")

# Инициализация приложения Quart
app = Quart(__name__)
app = cors(app)

# Инициализация Telegram-клиента
client = TelegramClient("session_name", api_id, api_hash)

# Глобальная очередь для ответов
response_queue = asyncio.Queue()

# Инициализация Telegram перед запуском сервера
@app.before_serving
async def before_serving():
    await client.start()
    logging.info("Telegram клиент успешно подключен.")

# Завершение работы клиента после остановки сервера
@app.after_serving
async def after_serving():
    await client.disconnect()
    logging.info("Telegram клиент отключен.")

# Обработчик событий для получения сообщений от бота
@client.on(events.NewMessage(from_users=bot_username))
async def handle_new_message(event):
    # Сохраняем сообщение в глобальную очередь
    await response_queue.put(event.message.text)
    logging.info(f"Получено сообщение от бота: {event.message.text}")

# Функция для отправки сообщения в Telegram и ожидания ответа
async def send_to_telegram(user_id, timeout=10):
    try:
        bot_entity = await client.get_entity(bot_username)
        logging.info(f"Отправка сообщения боту: {bot_username}, user_id: {user_id}")

        # Отправляем сообщение боту
        await client.send_message(bot_entity, str(user_id))

        # Ожидаем ответ от бота с тайм-аутом
        response = await asyncio.wait_for(response_queue.get(), timeout=timeout)
        logging.info(f"Ответ от бота: {response}")

        # Проверяем, содержит ли ответ UID пользователя
        if re.search(f"UID: `{user_id}`", response):
            return "ID confirmed"
        elif re.search("User not found", response):
            return "User not found"
        else:
            logging.warning(f"Неожиданный ответ от бота: {response}")
            return "Unexpected response"

    except asyncio.TimeoutError:
        logging.warning("Тайм-аут ожидания ответа от бота.")
        return "Timeout"
    except RPCError as e:
        logging.error(f"Ошибка RPC: {e}")
        return f"Error: {str(e)}"
    except Exception as e:
        logging.error(f"Ошибка при обработке сообщения: {e}")
        return f"Error: {str(e)}"

# Функция с повторными попытками
async def send_with_retries(user_id, retries=3, timeout=10):
    for attempt in range(retries):
        logging.info(f"Попытка {attempt + 1} из {retries} для User ID: {user_id}")
        response = await send_to_telegram(user_id, timeout)
        if response != "Timeout":
            return response
        logging.warning(f"Попытка {attempt + 1} не удалась, пробую снова...")

    return "Timeout"

# Маршрут для верификации ID через Telegram
@app.route('/verify-id', methods=['POST'])
async def verify_id():
    try:
        # Получаем данные из запроса
        data = await request.get_json()
        user_id = data.get('userId')

        # Проверка валидности user_id
        if not user_id or not str(user_id).isdigit():
            return jsonify({'message': 'Invalid or missing User ID'}), 400

        logging.info(f"Получен запрос на проверку ID: {user_id}")

        # Отправляем запрос в Telegram
        response = await send_with_retries(user_id)

        logging.info(f"Ответ от Telegram: {response}")

        # Формируем ответ
        if response == "ID confirmed":
            return jsonify({'message': 'ID confirmed'}), 200
        elif response == "User not found":
            return jsonify({'message': 'User not found'}), 404
        elif response == "Timeout":
            return jsonify({'message': 'Bot did not respond in time'}), 504
        else:
            return jsonify({'message': f'Unexpected response: {response}'}), 500

    except Exception as e:
        logging.error(f"Ошибка обработки запроса: {e}")
        return jsonify({'message': f'Error: {str(e)}'}), 500

# Запуск сервера через Hypercorn
if __name__ == '__main__':
    from hypercorn.asyncio import serve
    from hypercorn.config import Config

    config = Config()
    config.bind = ["127.0.0.1:5000"]

    # Запуск сервера с Hypercorn
    asyncio.run(serve(app, config))
