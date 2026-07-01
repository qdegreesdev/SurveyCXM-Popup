import os
import uuid
import re
import asyncio
from loguru import logger
import edge_tts

# Default TTS Voice
DEFAULT_VOICE = "en-IN-NeerjaNeural"

def clean_text_for_speech(text: str) -> str:
    """Removes HTML tags and emojis from text for clean TTS generation."""
    if not text:
        return ""
    
    # 1. Remove HTML tags
    clean_text = re.sub(r'<[^>]+>', ' ', text)
    
    # 2. Remove URLs
    clean_text = re.sub(r'http[s]?://\S+', '', clean_text)
    
    # 3. Remove Emojis
    emoji_pattern = re.compile(
        r'['
        r'\U0001f600-\U0001f64f'
        r'\U0001f300-\U0001f5ff'
        r'\U0001f680-\U0001f6ff'
        r'\U0001f700-\U0001f77f'
        r'\U0001f780-\U0001f7ff'
        r'\U0001f800-\U0001f8ff'
        r'\U0001f900-\U0001f9ff'
        r'\U0001fa00-\U0001fa6f'
        r'\U0001fa70-\U0001faff'
        r'\u2600-\u26FF'
        r'\u2700-\u27BF'
        r'\uFE0F'
        r']+',
        flags=re.UNICODE
    )
    clean_text = emoji_pattern.sub(r'', clean_text)
    
    # Clean up excessive whitespace
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return clean_text

import time
import glob

def cleanup_old_audio_files(max_age_seconds: int = 1800):
    """Deletes audio files older than max_age_seconds."""
    audio_dir = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')), "static", "audio")
    if not os.path.exists(audio_dir):
        return
        
    now = time.time()
    for filepath in glob.glob(os.path.join(audio_dir, "*.mp3")):
        try:
            if os.path.isfile(filepath):
                file_age = now - os.path.getmtime(filepath)
                if file_age > max_age_seconds:
                    os.remove(filepath)
                    logger.info(f"Cleaned up old audio file: {filepath}")
        except FileNotFoundError:
            pass  # File was likely already deleted by a concurrent request
        except Exception as e:
            logger.warning(f"Failed to clean up {filepath}: {e}")

async def generate_audio_file(text: str, voice: str = DEFAULT_VOICE, filename: str = None) -> str:
    """Generates an MP3 file using Edge-TTS. Accepts pre-generated filename for BackgroundTasks."""
    clean_text = clean_text_for_speech(text)
    if not clean_text:
        return ""
    
    # Ensure static/audio directory exists
    audio_dir = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')), "static", "audio")
    os.makedirs(audio_dir, exist_ok=True)
    
    # Clean up files older than 30 minutes in the background to prevent blocking
    asyncio.create_task(asyncio.to_thread(cleanup_old_audio_files))
    
    if not filename:
        filename = f"tts_{uuid.uuid4().hex}.mp3"
        
    filepath = os.path.join(audio_dir, filename)
    
    try:
        communicate = edge_tts.Communicate(clean_text, voice)
        await asyncio.wait_for(communicate.save(filepath), timeout=60.0)
        return filename
    except Exception as e:
        logger.error(f"TTS Generation failed or timed out: {e}")
        return ""
