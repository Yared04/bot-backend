from io import BytesIO
from typing import Optional
from fastapi import FastAPI, Form, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from telethon import Button, TelegramClient
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
CLIENT_1_BOT_TOKEN = os.getenv("CLIENT_1_BOT_TOKEN")
CLIENT_1_CHANNEL_ID = os.getenv("CLIENT_1_CHANNEL_ID")
CLIENT_1_WEB_APP = os.getenv("CLIENT_1_WEB_APP")

app = FastAPI()

# ✅ Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (change this to specific frontend URL for security)
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)

clients = {
    "366965858": {"bot_token": CLIENT_1_BOT_TOKEN, "channel_id": CLIENT_1_CHANNEL_ID , "web_app": CLIENT_1_WEB_APP},
}

bot = TelegramClient("session", API_ID, API_HASH)

@app.get("/")
async def read_root():
    return {"message": "Hello, World!"}

# Initialize the Telethon client for the bot
@app.post("/post_event")
async def post_event(
    files: Optional[list[UploadFile]] = File([]),
    client_id: str = Form(...),
    title: Optional[str] = Form(''),
    description: str = Form(...),
    location: Optional[str] = Form(''),
    start_date: Optional[str] = Form(''),
    end_date: Optional[str] = Form(''),
    calendarButton: bool = Form(...),
):
    if client_id in clients:
        bot_token = clients[client_id]["bot_token"]
        channel_id = clients[client_id]["channel_id"]
        web_app = clients[client_id]["web_app"]

        # Construct the URL with encoded parameters
        calendar_url = f"{web_app}?title={title}&loc={location}&start_date={start_date}&end_date={end_date}"

        # Connect the bot to Telegram
        await bot.start(bot_token=bot_token)

        message = f"<b>{title}</b>\n\n{description}"

        # If calendarButton is False, send the event without a calendar button
        if calendarButton and start_date and end_date:
            button = [
                Button.url('Add to Calendar 📆', calendar_url),
            ]
        else:
            button = None
        
        # If no files are uploaded, send the event as a message
        if len(files) == 0:
            await bot.send_message(
                channel_id,
                message,
                parse_mode="html",
                buttons=button
            )

            return {"status": "success", "message": "Event posted!"}

        # Upload the file to Telegram and get a media object
        media = []
        for file in files:
            content = await file.read()  # Read the file as bytes
            file_stream = BytesIO(content)
            file_stream.name = file.filename  # Give it a name to preserve file type

            # Upload the file properly
            uploaded_file = await bot.upload_file(file_stream)
            media.append(uploaded_file)  # Handle non-image files

        
        if len(media) <= 1:
            # Send a single file with an inline button
            await bot.send_file(
                channel_id, media[0], caption=message, parse_mode="html",
                buttons=button
            )
        else:
            # Send files as an album and send the calendar button separately
            await bot.send_file(
                channel_id, media, caption=message, parse_mode="html"
            )
            if calendarButton:
                await bot.send_message(
                    channel_id, "Click here to add the event above to your calendar:",
                    buttons=button
                )
        

        return {"status": "success", "message": "Event posted!"}

    else:
        return {"status": "error", "message": "Client not found!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=2000, reload=True)
