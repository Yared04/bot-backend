from datetime import datetime
import pytz
import urllib.parse
import uuid
import sqlite3
import hmac
import hashlib
import time
import os
from datetime import timedelta

def format_date_for_google(date_str: str) -> str:
    """
    Formats an ISO date string to Google Calendar format: YYYYMMDDTHHmmssZ
    """
    if not date_str:
        return ""
    try:
        # Handle potential space instead of T
        safe_date_str = date_str.replace(" ", "T")
        
        # Replace 'Z' suffix with '+00:00' for proper parsing
        # datetime.fromisoformat() doesn't handle 'Z' directly
        if safe_date_str.endswith('Z'):
            safe_date_str = safe_date_str[:-1] + '+00:00'
        
        dt = datetime.fromisoformat(safe_date_str)
        
        # Convert to UTC if not already
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.UTC)
        else:
            dt = dt.astimezone(pytz.UTC)
            
        return dt.strftime("%Y%m%dT%H%M%SZ")
    except Exception as e:
        print(f"Error formatting date for Google Calendar: {e}")
        return ""

def generate_google_calendar_url(title: str, start_date: str, end_date: str, location: str, description: str) -> str:
    """
    Generates a Google Calendar URL with pre-filled event details.
    """
    formatted_start = format_date_for_google(start_date)
    formatted_end = format_date_for_google(end_date)
    
    if not formatted_start or not formatted_end:
        return ""
    
    # Google Calendar uses dates parameter as: START/END
    dates_param = f"{formatted_start}/{formatted_end}"
    
    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": dates_param,
        "details": description,
        "location": location,
    }
    
    # Build the URL
    base_url = "https://calendar.google.com/calendar/render"
    query_string = urllib.parse.urlencode(params)
    return f"{base_url}?{query_string}"

def _split_at_bytes(text: str, max_bytes: int) -> tuple[str, str]:
    """Splits a string at a byte boundary to avoid cutting multi-byte characters."""
    encoded = text.encode('utf-8')
    if len(encoded) <= max_bytes:
        return text, ""
    
    # Find the last valid character boundary within the byte limit
    cut_point = max_bytes
    while cut_point > 0 and (encoded[cut_point] & 0xC0) == 0x80:
        # This byte is a UTF-8 continuation byte, step back
        cut_point -= 1
    
    return encoded[:cut_point].decode('utf-8'), encoded[cut_point:].decode('utf-8')

def generate_ics_string(title: str, start_date: str, end_date: str, location: str, description: str, uid: str = None) -> str:
    """
    Generates an RFC 5545 compliant ICS file content string.
    """
    def format_date(date_str: str) -> str:
        if not date_str:
            return ""
        try:
            # Handle potential space instead of T
            safe_date_str = date_str.replace(" ", "T")
            
            # Replace 'Z' suffix with '+00:00' for proper parsing
            if safe_date_str.endswith('Z'):
                safe_date_str = safe_date_str[:-1] + '+00:00'
            
            # Parse the ISO string
            dt = datetime.fromisoformat(safe_date_str)
            
            # Convert to UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
            else:
                dt = dt.astimezone(pytz.UTC)
                
            return dt.strftime("%Y%m%dT%H%M%SZ")
        except Exception as e:
            print(f"Error formatting date for ICS: {e}")
            return ""

    def escape_text(text: str) -> str:
        if not text:
            return ""
        # Normalize newlines to \n, remove \r, then escape
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    def fold_line(line: str) -> str:
        """Folds long lines according to RFC 5545 (max 75 octets/bytes)."""
        # RFC 5545 limits lines to 75 octets (bytes), not characters.
        line_bytes = line.encode('utf-8')
        if len(line_bytes) <= 75:
            return line
        
        parts = []
        # First line: up to 75 bytes
        first_chunk, remaining = _split_at_bytes(line, 75)
        parts.append(first_chunk)
        
        # Continuation lines: space + up to 74 bytes
        while remaining:
            chunk, remaining = _split_at_bytes(remaining, 74)
            parts.append(" " + chunk)
            
        return "\r\n".join(parts)

    dt_stamp = datetime.now(pytz.UTC).strftime("%Y%m%dT%H%M%SZ")
    final_uid = uid or f"{uuid.uuid4()}@calendar-bot"

    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Esat Events//Calendar Bot//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"DTSTAMP:{dt_stamp}",
        f"UID:{final_uid}",
        f"SUMMARY:{escape_text(title)}",
        f"LOCATION:{escape_text(location)}",
        f"DESCRIPTION:{escape_text(description)}",
        f"DTSTART:{format_date(start_date)}",
        f"DTEND:{format_date(end_date)}",
        "SEQUENCE:0",
        "STATUS:CONFIRMED",
        "TRANSP:OPAQUE",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    
    # Fold lines and join with CRLF
    folded_content = [fold_line(line) for line in ics_lines]
    # RFC 5545 requires CRLF line endings
    return "\r\n".join(folded_content) + "\r\n"



# --- Database & Security Helpers ---

DB_PATH = "calendar_events.db"

def init_db(client_1_bot_token=None, client_1_channel_id=None):
    """
    Initializes the database and performs migrations.
    Also accepts optional client config to bootstrap (seed) the DB.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            title TEXT,
            start_date TEXT,
            end_date TEXT,
            location TEXT,
            description TEXT
        )
    ''')
    # Migration: Add expires_at if it doesn't exist
    try:
        cursor.execute("PRAGMA table_info(events)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'expires_at' not in columns:
            cursor.execute("ALTER TABLE events ADD COLUMN expires_at TEXT")
            conn.commit()
    except Exception as e:
        print(f"Migration error: {e}")

    # Create Clients Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS clients (
            client_id TEXT PRIMARY KEY,
            bot_token TEXT,
            channel_id TEXT
        )
    ''')

    # Seed hardcoded client if provided
    # This is useful for first-time setup or migration 
    # to ensure the app works immediately with env vars
    if client_1_bot_token and client_1_channel_id:
        MIGRATE_CLIENTS = {
            "366965858": {"bot_token": client_1_bot_token, "channel_id": client_1_channel_id},
        }
        
        for c_id, data in MIGRATE_CLIENTS.items():
            try:
                # Upsert logic (or INSERT OR IGNORE)
                cursor.execute("INSERT OR IGNORE INTO clients (client_id, bot_token, channel_id) VALUES (?, ?, ?)",
                               (c_id, data["bot_token"], data["channel_id"]))
            except Exception as e:
                print(f"Client seeding error for {c_id}: {e}")
    
    conn.commit()
    conn.close()

def get_client(client_id):
    """Fetch client configuration from database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clients WHERE client_id = ?", (client_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return dict(row)
        return None
    except Exception as e:
        print(f"Error fetching client: {e}")
        return None

def verify_telegram_init_data(init_data: str, bot_token: str) -> bool:
    """
    Verifies the Telegram initData using HMAC-SHA256 and provides replay protection.
    """
    try:
        parsed = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
        data = {}
        hash_value = None

        for k, v in parsed:
            if k == "hash":
                hash_value = v
            else:
                data[k] = v

        if not hash_value or not bot_token:
            return False

        # Replay Protection: Check if auth_date is older than 24 hours
        auth_date = int(data.get("auth_date", 0))
        if time.time() - auth_date > 86400: # 24 hours
            # print("Auth error: initData expired")
            return False

        # Build check string EXACTLY as Telegram expects
        data_check_string = "\n".join(
            f"{k}={data[k]}" for k in sorted(data.keys())
        )

        secret_key = hmac.new(b"WebAppData", bot_token.strip().encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        return hmac.compare_digest(calculated_hash, hash_value)
    except Exception as e:
        return False

def cleanup_expired_events():
    """Deletes events that have expired (end_date + 48h)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("DELETE FROM events WHERE expires_at < ?", (now,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Cleanup error: {e}")

def save_event(title, start_date, end_date, location, description):
    event_id = str(uuid.uuid4())
    # Set expiry to end_date + 48 hours
    try:
        # Handle end_date format (ISO or similar)
        end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        expires_at = (end_dt + timedelta(hours=48)).isoformat()
    except:
        # Fallback to 7 days from now if parsing fails
        expires_at = (datetime.now() + timedelta(days=7)).isoformat()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO events (id, title, start_date, end_date, location, description, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (event_id, title, start_date, end_date, location, description, expires_at))
    conn.commit()
    conn.close()
    
    # Run a quick cleanup as well
    cleanup_expired_events()
    return event_id

def get_event(event_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM events WHERE id = ?", (event_id,))
    row = cursor.fetchone()
    conn.close()
    return row
