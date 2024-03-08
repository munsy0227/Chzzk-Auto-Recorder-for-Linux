import json
import asyncio
import aiohttp
import time
import re
import os
import requests
import logging
import hashlib
from threading import Thread

MAX_FILENAME_BYTES = 254  # Maximum number of bytes for filename

def shorten_filename(filename):
    if len(filename.encode('utf-8')) > MAX_FILENAME_BYTES:
        hash_value = hashlib.sha256(filename.encode()).hexdigest()[:8]
        name, extension = os.path.splitext(filename)
        shortened_name = f"{name[:MAX_FILENAME_BYTES - 20]}_{hash_value}{extension}"
        logger.warning(f"Filename {filename} is too long. Shortening to {shortened_name}.")
        return shortened_name
    else:
        return filename

# Logging Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
STREAMLINK_PATH = os.path.join(os.path.dirname(__file__), "venv", "bin", "streamlink")
FFMPEG_PATH = "/usr/bin/ffmpeg"
LIVE_DETAIL_API = "https://api.chzzk.naver.com/service/v2/channels/{channel_id}/live-detail"
TIME_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'time_sleep.txt')
THREAD_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'thread.txt')
CHANNELS_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'channels.json')
DELAYS_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'delays.json')
COOKIE_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookie.json')

# Load Configuration
def load_setting(file_path):
    with open(file_path, "r") as file:
        return file.read().strip()

time_file_content = load_setting(TIME_FILE_PATH)
TIMEOUT = int(time_file_content) if time_file_content.isdigit() else 60
thread_file_content = load_setting(THREAD_FILE_PATH)
STREAM_SEGMENT_THREADS = int(thread_file_content) if thread_file_content.isdigit() else 2
with open(CHANNELS_FILE_PATH, 'r') as channels_file:
    CHANNELS = json.load(channels_file)
DELAYS = json.load(open(DELAYS_FILE_PATH))

# Helper Functions
def get_auth_headers(cookies):
    return {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)',
        'Cookie': f'NID_AUT={cookies.get("NID_AUT", "")}; NID_SES={cookies.get("NID_SES", "")}'
    }

def get_session_cookies():
    with open(COOKIE_FILE_PATH, 'r') as cookie_file:
        return json.load(cookie_file)

async def get_live_info(channel, headers):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(LIVE_DETAIL_API.format(channel_id=channel["id"]), headers=headers) as response:
                response.raise_for_status()
                data = await response.json()
                return data.get("content", {})
    except aiohttp.ClientError as e:
        logger.error(f"Failed to fetch live info for {channel['name']}: {e}")
        return None

async def fetch_stream_url(channel, headers):
    live_info = await get_live_info(channel, headers)
    live_playback_json = json.loads(live_info.get("livePlaybackJson") or "{}").get("media", [])
    if live_playback_json:
        return live_playback_json[0].get("path", "")
    else:
        return None

# Main Recording Function
async def record_stream(channel, headers):
    delay = DELAYS.get(channel.get("identifier"), 0)
    await asyncio.sleep(delay)

    if channel.get("active", "on") == "off":
        logger.info(f"{channel['name']} channel is inactive. Skipping recording.")
        return

    while True:
        stream_url = await fetch_stream_url(channel, headers)
        
        if stream_url:
            try:
                current_time = time.strftime("%Y-%m-%d_%H:%M:%S")
                channel_name = channel.get("name", "Unknown")
                output_dir = channel.get("output_dir", "./recordings")
                output_file = shorten_filename(f"[{current_time}] {channel_name}.ts")
                
                # Ensure output directory exists
                os.makedirs(output_dir, exist_ok=True)

                ffmpeg_command = [
                    FFMPEG_PATH,
                    "-i", stream_url,
                    "-c", "copy",
                    os.path.join(output_dir, output_file)
                ]

                process = await asyncio.create_subprocess_exec(
                    *ffmpeg_command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                # Display standard output in the terminal
                async for line in process.stdout:
                    print(line.decode().strip())

                await process.communicate()

                if process.returncode != 0:
                    logger.error(f"Error occurred while recording {channel_name}: subprocess returned non-zero exit code {process.returncode}")
            except Exception as e:
                logger.error(f"Error occurred while recording {channel_name}: {e}")
        else:
            logger.info(f"No stream URL available for {channel.get('name', 'Unknown')}")

        await asyncio.sleep(TIMEOUT)

async def monitor_stream_url(channel, headers):
    while True:
        stream_url = await fetch_stream_url(channel, headers)
        if stream_url:
            logger.info(f"New stream URL for {channel.get('name', 'Unknown')}: {stream_url}")
        else:
            logger.info(f"No stream URL available for {channel.get('name', 'Unknown')}")
        await asyncio.sleep(21600)  # Refresh URL

# Main Function
async def main():
    headers = get_auth_headers(get_session_cookies())
    tasks = [record_stream(channel, headers) for channel in CHANNELS]
    monitor_tasks = [monitor_stream_url(channel, headers) for channel in CHANNELS]

    try:
        await asyncio.gather(*tasks, *monitor_tasks)
    except KeyboardInterrupt:
        logger.info("Recording stopped by user.")

if __name__ == "__main__":
    asyncio.run(main())

