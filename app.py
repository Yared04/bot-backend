from flask import Flask, request, jsonify
from flask_cors import CORS
from telebot import TeleBot, types
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()
CLIENT_1_BOT_TOKEN = os.getenv("CLIENT_1_BOT_TOKEN")
CLIENT_1_CHANNEL_ID = os.getenv("CLIENT_1_CHANNEL_ID")
CLIENT_1_WEB_APP = os.getenv("CLIENT_1_WEB_APP")

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

clients = {
    "client_1": {"bot_token": CLIENT_1_BOT_TOKEN, "channel_id": CLIENT_1_CHANNEL_ID , "web_app": CLIENT_1_WEB_APP},
}

@app.route('/post_event', methods=['POST'])
def post_event():
    data = request.form  # Extract form data (text fields)
    files = request.files.getlist('files')  # Extract uploaded files
    client_id = data.get("client_id")

    if client_id in clients:
        bot_token = clients[client_id]["bot_token"]
        channel_id = clients[client_id]["channel_id"]
        web_app = clients[client_id]["web_app"]
        title = data.get("title")
        description = data.get("description")
        location = data.get("location")

        start_date = data.get('start_date')  # First 29 characters
        end_date = data.get("end_date")  # Everything after the first 29 characters

        # Construct the URL with encoded parameters
        calendar_url = f"{web_app}?title={title}&loc={location}&start_date={start_date}&end_date={end_date}"

        bot = TeleBot(bot_token)
        message = f"<b>{title}</b>\n\n{description}"

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Open Mini App", url=calendar_url))
        
        bot.send_photo(channel_id, files[0], caption=message, reply_markup=markup, parse_mode="HTML")
     
        return jsonify({"status": "success", "message": "Event posted!"}), 200
    else:
        return jsonify({"status": "error", "message": "Client not found!"}), 400

if __name__ == '__main__':
    app.run(port=5000, debug=True)
