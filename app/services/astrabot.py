import base64
import io
import json
import math
import re
from datetime import datetime
from typing import Tuple, Optional
import docx

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, UnidentifiedImageError
from groq import AsyncGroq

from app.config import settings
from app.services.converter import pdf_to_text_and_json

MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
DEVANAGARI = re.compile(r"[\u0900-\u097f]")

class AstraBotError(Exception): pass
class InvalidImageError(AstraBotError): pass
class OllamaUnavailableError(AstraBotError): pass
class OllamaResponseError(AstraBotError): pass

# ==========================================
# HELPER: IMAGE PROCESSING (PIL)
# ==========================================
def _load_image(image_bytes: bytes) -> Image.Image:
    if not image_bytes: raise InvalidImageError("Empty image.")
    if len(image_bytes) > MAX_IMAGE_BYTES: raise InvalidImageError("Image too large.")
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS: raise InvalidImageError("Dimensions too large.")
            return ImageOps.exif_transpose(source).convert("RGB")
    except Exception as exc:
        raise InvalidImageError("Not a valid image file.") from exc

def _load_banner_font(size: int, text: str) -> ImageFont.ImageFont:
    font_paths = []
    if DEVANAGARI.search(text):
        font_paths.extend(("C:\\Windows\\Fonts\\Nirmala.ttc", "C:\\Windows\\Fonts\\mangal.ttf"))
    font_paths.extend(("C:\\Windows\\Fonts\\arialbd.ttf", "C:\\Windows\\Fonts\\arial.ttf", "arial.ttf"))
    for fp in font_paths:
        try: return ImageFont.truetype(fp, size=size)
        except OSError: continue
    return ImageFont.load_default()

def _encode_jpeg(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90, optimize=True)
    return output.getvalue()

def _apply_banner(image: Image.Image, text: str, include_date: bool) -> Image.Image:
    date_text = f"DOP: {datetime.now():%d/%m/%Y}" if include_date else ""
    lines = [line for line in (text, date_text) if line]
    if not lines: return image

    font_size = max(14, min(36, int(max(50, image.height * 0.16) * 0.3)))
    font = _load_banner_font(font_size, text or date_text)
    available_width = max(1, image.width - 16)
    
    padding = max(8, font_size // 2)
    line_height = max(font.getbbox(line)[3] - font.getbbox(line)[1] for line in lines)
    gap = max(2, font_size // 5) if len(lines) > 1 else 0
    strip_height = max(50, int(image.height * 0.16), padding * 2 + len(lines) * line_height + (len(lines) - 1) * gap)
    
    result = Image.new("RGB", (image.width, image.height + strip_height), "white")
    result.paste(image, (0, 0))
    draw = ImageDraw.Draw(result)
    y = image.height + padding
    for line in lines:
        draw.text((image.width // 2, y), line, fill="black", anchor="mt", font=font)
        y += line_height + gap
    return result

# ==========================================
# SMART DOCUMENT AI (Strictly English & File-Only)
# ==========================================
async def _process_document_ai(command: str, file_bytes: bytes, filename: str) -> Tuple[None, str]:
    ext = filename.split('.')[-1].lower()
    text = ""
    try:
        if ext == 'pdf':
            text = pdf_to_text_and_json(file_bytes)["full_text"]
        elif ext in ['docx', 'doc']:
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
        elif ext == 'txt':
            text = file_bytes.decode('utf-8', errors='ignore')
        else:
            return None, f"Main {ext.upper()} files nahi padh sakta."
    except Exception as e:
        return None, f"File padhne mein error: {str(e)}"

    if not text.strip(): return None, "This file contains no readable text."

    # ✅ STRICT PROMPT FOR DOCUMENT: Force English & Only Document Context
    system = (
        "You are AstraBot, an AI Document Assistant. "
        "The user has uploaded a file. Here is the extracted text:\n\n"
        f"{text[:30000]}\n\n"
        "STRICT RULES:\n"
        "1. Answer the user's question based ONLY on the text provided above.\n"
        "2. If the user asks 'What is this?' or 'Tell me about this file', summarize the ACTUAL CONTENT of this document, not generic definitions.\n"
        "3. You MUST reply in English. Do not use Hindi unless the user explicitly asks you to translate into Hindi.\n"
        "4. If the answer is not present in the text, say: 'I could not find that information in the document.'"
    )
    user_msg = f"User Question: {command}"

    try:
        client = AsyncGroq(api_key=settings.GROQ_API_KEY.get_secret_value())
        res = await client.chat.completions.create(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
            model="openai/gpt-oss-120b",
            temperature=0.3,
            max_tokens=2000
        )
        return None, res.choices[0].message.content
    except Exception as e:
        raise AstraBotError(f"AI Error: {str(e)}")

# ==========================================
# SMART IMAGE AI (Strictly English & Vision-Only)
# ==========================================
async def _process_image_ai(command: str, file_bytes: bytes, candidate_name: Optional[str] = None) -> Tuple[Optional[bytes], str]:
    image = _load_image(file_bytes)
    image_base64 = base64.b64encode(file_bytes).decode("ascii")
    
    if candidate_name:
        command += f" (Name provided: {candidate_name})"

    # ✅ STRICT PROMPT FOR IMAGE: Force English Chat & Exact JSON for Editing
    system_prompt = (
        "You are AstraBot, an AI Vision Assistant. The user has uploaded an image.\n\n"
        "STRICT RULES:\n"
        "1. If the user asks a question (e.g., 'What is this?', 'Read this'), describe the image accurately in ENGLISH.\n"
        "2. If the user asks you to EDIT the image (e.g., 'add name Sunil', 'write date'), you MUST reply ONLY with a JSON block wrapped in <edit> tags:\n"
        "<edit>{\"text\": \"Sunil Kumar\", \"include_date\": false}</edit>\n"
        "Do NOT write anything else if you are editing.\n"
        "Always use English for your normal chat replies."
    )
    
    user_content = f"User Command: {command}"

    try:
        client = AsyncGroq(api_key=settings.GROQ_API_KEY.get_secret_value())
        res = await client.chat.completions.create(
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": system_prompt + "\n\n" + user_content},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                ]
            }],
            model="qwen/qwen3.8-27b",
            temperature=0.2,
            max_tokens=1024
        )
        ai_text = res.choices[0].message.content
        
        # Check if AI wants to edit
        if "<edit>" in ai_text and "</edit>" in ai_text:
            json_str = re.search(r"<edit>(.*?)</edit>", ai_text, re.DOTALL).group(1)
            data = json.loads(json_str)
            
            text_to_write = data.get("text", candidate_name or "")
            include_date = data.get("include_date", False)
            
            edited_image = _apply_banner(image, text_to_write, include_date)
            return _encode_jpeg(edited_image), "✅ Done! I have edited the image."
        else:
            return None, ai_text.strip()

    except Exception as e:
        raise AstraBotError(f"Image AI Error: {str(e)}")

# ==========================================
# MAIN EXECUTION
# ==========================================
async def process_image_with_pure_ai(prompt: str, file_bytes: bytes, filename: str, candidate_name: str | None = None) -> Tuple[Optional[bytes], str]:
    if not prompt.strip(): raise AstraBotError("Please enter a message.")
    
    ext = filename.split('.')[-1].lower()

    if ext in ['pdf', 'docx', 'doc', 'txt']:
        return await _process_document_ai(prompt, file_bytes, filename)
    elif ext in ['jpg', 'jpeg', 'png', 'webp']:
        return await _process_image_ai(prompt, file_bytes, candidate_name)
    else:
        raise AstraBotError(f"Main {ext.upper()} files support nahi karta.")

parse_voice_command_with_ai = process_image_with_pure_ai
parse_voice_command = process_image_with_pure_ai