import os
import hmac
import hashlib
import uuid
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, Form, UploadFile, File, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from telethon import Button, TelegramClient
from dotenv import load_dotenv
import urllib.parse
import urllib.request
import time
from io import BytesIO

# Import helpers from utils
from utils import (
    generate_ics_string, 
    generate_google_calendar_url, 
    init_db, 
    get_client, 
    verify_telegram_init_data, 
    save_event, 
    get_event
)

# Load environment variables from .env file
load_dotenv()
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
CLIENT_1_BOT_TOKEN = os.getenv("CLIENT_1_BOT_TOKEN")
CLIENT_1_CHANNEL_ID = os.getenv("CLIENT_1_CHANNEL_ID")

app = FastAPI()

# ✅ Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],
)

bot = TelegramClient("session", API_ID, API_HASH)


# Initialize DB and seed with env var client if needed
init_db(CLIENT_1_BOT_TOKEN, CLIENT_1_CHANNEL_ID)

# --- Endpoints ---

@app.get("/calendar/render")
async def calendar_redirect(
    request: Request,
    id: str
):
    """
    Smart redirect endpoint that uses an event ID to fetch details.
    This hides the actual event details from the URL.
    """
    event = get_event(id)
    if not event:
        return HTMLResponse(content="<h2>Event not found or expired.</h2>", status_code=404)

    from utils import generate_google_calendar_url
    user_agent = request.headers.get("user-agent", "").lower()
    is_ios = "iphone" in user_agent or "ipad" in user_agent or "macintosh" in user_agent
    
    if is_ios:
        backend_base_url = os.getenv("BACKEND_PUBLIC_URL", "http://localhost:2000").rstrip("/")
        # Use path-based URL with .ics extension for iOS auto-detection
        ics_url = f"{backend_base_url}/calendar/download/{id}.ics"
        return RedirectResponse(url=ics_url, status_code=302)
    else:
        google_url = generate_google_calendar_url(
            event["title"], event["start_date"], event["end_date"], 
            event["location"], event["description"]
        )
        return RedirectResponse(url=google_url, status_code=302)

@app.get("/calendar/download/{event_filename}")
async def download_ics(
    event_filename: str
):
    """
    Serves ICS file. Expects filename like {event_id}.ics
    """
    # Extract ID from filename (e.g., "uuid.ics" -> "uuid")
    if not event_filename.endswith(".ics"):
        raise HTTPException(status_code=400, detail="Invalid file format")
    
    event_id = event_filename.replace(".ics", "")
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    ics_content = generate_ics_string(
        event["title"], event["start_date"], event["end_date"], 
        event["location"], event["description"], uid=event_id
    )
    
    # Optimized headers for mobile Safari/iOS
    # Content-Disposition "attachment" ensures a cleaner "Do you want to download?" prompt
    # method=PUBLISH in Content-Type hints that this is a standalone event
    return Response(
        content=ics_content,
        media_type="text/calendar; charset=utf-8; method=PUBLISH",
        headers={
            "Content-Disposition": f"attachment; filename={event_filename}",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

# Initialize the Telethon client for the bot
@app.post("/post_event")
async def post_event(
    request: Request,
    files: Optional[list[UploadFile]] = File([]),
    client_id: str = Form(...),
    title: Optional[str] = Form(''),
    description: str = Form(...),
    location: Optional[str] = Form(''),
    start_date: Optional[str] = Form(''),
    end_date: Optional[str] = Form(''),
    calendarButton: bool = Form(...),
    telegram_init_data: str = Form(""),
):
    data = get_client(client_id)
    if not data:
        raise HTTPException(status_code=404, detail="Client not found")

    # --- Authentication ---
    bot_token = data["bot_token"]
    if not telegram_init_data:
        # Fallback to check header just in case, but form is primary now
        telegram_init_data = request.headers.get("Authorization", "")
    
    if not telegram_init_data:
        # If still empty, it's an unauthorized request
        raise HTTPException(status_code=401, detail="Authentication required (initData missing)")
    
    # Check if telegram_init_data is valid
    if not verify_telegram_init_data(telegram_init_data, bot_token):
        raise HTTPException(status_code=403, detail="Invalid Telegram authentication (verification failed)")

    channel_id = data["channel_id"]
    backend_base_url = os.getenv("BACKEND_PUBLIC_URL", "http://localhost:2000").rstrip("/")
    
    # Save event to DB and get unique ID
    event_id = save_event(title, start_date, end_date, location, description)
    calendar_url = f"{backend_base_url}/calendar/render?id={event_id}"

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=2000, reload=True)
