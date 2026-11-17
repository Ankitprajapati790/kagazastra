import base64
import io
import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Literal

from PIL import (Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, UnidentifiedImageError)
from pydantic import (BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator)
from groq import AsyncGroq

# ==========================================
# GROQ API CONFIGURATION
# ==========================================
# Yahan apni nayi Groq API Key daalein
GROQ_API_KEY = "YOUR_NEW_GROQ_API_KEY_HERE" 

MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_ACTIONS = 5
DEFAULT_TIMEZONE = "Asia/Kolkata"

ACTION_ADD_TEXT = "add_text"
ACTION_ADD_DATE = "add_date"
ACTION_ADD_CAPTION = "add_caption"
ACTION_CHANGE_TEXT = "change_text"
ACTION_CHANGE_LANGUAGE = "change_language"
ACTION_CHANGE_FONT_SIZE = "change_font_size"
ACTION_CHANGE_COLOR = "change_color"
ACTION_CHANGE_POSITION = "change_position"
ACTION_RESIZE = "resize"
ACTION_COMPRESS = "compress"
ACTION_CROP = "crop"
ACTION_ROTATE = "rotate"
ACTION_CONVERT_FORMAT = "convert_format"
ACTION_ADJUST_BRIGHTNESS = "adjust_brightness"
ACTION_REMOVE_BACKGROUND = "remove_background"
ACTION_REMOVE_DATE = "remove_date"
ACTION_DESCRIBE = "describe"
ACTION_UNSUPPORTED = "unsupported"

SUPPORTED_ACTIONS = frozenset({
    ACTION_ADD_TEXT, ACTION_ADD_DATE, ACTION_ADD_CAPTION, ACTION_CHANGE_TEXT,
    ACTION_CHANGE_LANGUAGE, ACTION_CHANGE_FONT_SIZE, ACTION_CHANGE_COLOR,
    ACTION_CHANGE_POSITION, ACTION_RESIZE, ACTION_COMPRESS, ACTION_CROP,
    ACTION_ROTATE, ACTION_CONVERT_FORMAT, ACTION_ADJUST_BRIGHTNESS,
    ACTION_REMOVE_BACKGROUND, ACTION_REMOVE_DATE, ACTION_DESCRIBE, ACTION_UNSUPPORTED,
})

POSITION_CENTER = "center"
POSITION_TOP = "top"
POSITION_BOTTOM = "bottom"
POSITION_LEFT = "left"
POSITION_RIGHT = "right"
POSITION_TOP_LEFT = "top_left"
POSITION_TOP_RIGHT = "top_right"
POSITION_BOTTOM_LEFT = "bottom_left"
POSITION_BOTTOM_RIGHT = "bottom_right"

POSITION_VALUES = frozenset({
    POSITION_CENTER, POSITION_TOP, POSITION_BOTTOM, POSITION_LEFT, POSITION_RIGHT,
    POSITION_TOP_LEFT, POSITION_TOP_RIGHT, POSITION_BOTTOM_LEFT, POSITION_BOTTOM_RIGHT
})

DATE_FORMAT_DD_MM_YYYY = "DD/MM/YYYY"
DATE_FORMAT_YYYY_MM_DD = "YYYY-MM-DD"
DATE_FORMAT_HINDI = "HINDI"
DATE_FORMAT_VALUES = frozenset({DATE_FORMAT_DD_MM_YYYY, DATE_FORMAT_YYYY_MM_DD, DATE_FORMAT_HINDI})

LANGUAGE_AUTO = "auto"
LANGUAGE_HI = "hi"
LANGUAGE_EN = "en"
LANGUAGE_VALUES = frozenset({LANGUAGE_AUTO, LANGUAGE_EN, LANGUAGE_HI})

COLOR_BLACK = "black"
COLOR_WHITE = "white"
COLOR_RED = "red"
COLOR_GREEN = "green"
COLOR_BLUE = "blue"
COLOR_YELLOW = "yellow"

# Cleared the corrupted Hindi/Hinglish map and replaced with clean regex matching
DEVANAGARI_RE = re.compile(r"[\u0900-\u097f]")

class AstraBotError(Exception):
    pass

class InvalidImageError(AstraBotError):
    pass

class OllamaUnavailableError(AstraBotError):
    pass

class OllamaResponseError(AstraBotError):
    pass

class ImageAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        ACTION_ADD_TEXT, ACTION_ADD_DATE, ACTION_ADD_CAPTION,
        ACTION_CHANGE_TEXT, ACTION_CHANGE_LANGUAGE, ACTION_CHANGE_FONT_SIZE,
        ACTION_CHANGE_COLOR, ACTION_CHANGE_POSITION, ACTION_RESIZE,
        ACTION_COMPRESS, ACTION_CROP, ACTION_ROTATE, ACTION_CONVERT_FORMAT,
        ACTION_ADJUST_BRIGHTNESS, ACTION_REMOVE_BACKGROUND, ACTION_REMOVE_DATE,
        ACTION_DESCRIBE, ACTION_UNSUPPORTED,
    ]
    text: str | None = Field(default=None, max_length=200)
    font_size: int | None = Field(default=None, ge=6, le=300)
    color: str | None = Field(default=None, max_length=7)
    position: str | None = None
    language: str | None = None
    width: int | None = Field(default=None, ge=1, le=8192)
    height: int | None = Field(default=None, ge=1, le=8192)
    max_kb: int | None = Field(default=None, ge=1, le=2048)
    angle: float | None = Field(default=None, ge=-360, le=360)
    crop_box: tuple[float, float, float, float] | None = None
    brightness: float | None = Field(default=None, ge=0.1, le=3.0)
    date_format: str | None = None

    @field_validator("position")
    @classmethod
    def validate_position(cls, v):
        if v is not None and v not in POSITION_VALUES:
            raise ValueError(f"position must be one of {sorted(POSITION_VALUES)}")
        return v

    @field_validator("color")
    @classmethod
    def validate_color(cls, v):
        if v is not None:
            v = v.lstrip("#")
            if not re.fullmatch(r"[0-9A-Fa-f]{6}", v) and v.lower() not in [COLOR_BLACK, COLOR_WHITE, COLOR_RED, COLOR_GREEN, COLOR_BLUE, COLOR_YELLOW]:
                raise ValueError("color must be a valid name or hex colour")
        return v

    @model_validator(mode="after")
    def validate_action_parameters(self):
        action = self.action
        if action == ACTION_ADD_TEXT and self.text is None:
            raise ValueError("add_text requires text")
        elif action == ACTION_RESIZE and (self.width is None or self.height is None):
            raise ValueError("resize requires width and height")
        elif action == ACTION_COMPRESS and self.max_kb is None:
            raise ValueError("compress requires max_kb")
        elif action == ACTION_ROTATE and self.angle is None:
            raise ValueError("rotate requires angle")
        elif action == ACTION_CROP:
            if self.crop_box is None:
                raise ValueError("crop requires crop_box")
            left, top, right, bottom = self.crop_box
            if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
                raise ValueError("crop_box must be a normalized rectangle")
        return self

class AstraBotPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actions: list[ImageAction] = Field(min_length=1, max_length=MAX_ACTIONS)
    message: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_action_sequence(self):
        action_names = [a.action for a in self.actions]
        if ACTION_UNSUPPORTED in action_names and len(action_names) != 1:
            raise ValueError("unsupported must be the only action")
        if ACTION_DESCRIBE in action_names and len(action_names) != 1:
            raise ValueError("describe must be the only action")
        for i, a in enumerate(self.actions):
            if a.action == ACTION_COMPRESS and i != len(self.actions) - 1:
                raise ValueError("compress must be the final action")
        return self

def _parse_plan(content: str) -> AstraBotPlan:
    stripped = content.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        first_newline = stripped.find("\n")
        if first_newline == -1:
            raise ValueError("AI returned an empty JSON code block.")
        stripped = stripped[first_newline + 1:-3].strip()

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError("AI returned invalid JSON.") from exc

    if not isinstance(data, dict) or not isinstance(data.get("actions"), list):
        raise ValueError("AI response must contain an actions array.")

    actions_raw = data["actions"]
    normalized_actions = []
    for action in actions_raw:
        if not isinstance(action, dict) or "action" not in action:
            raise ValueError("Each action must be a JSON object with an action field.")
        action_name = action["action"]
        if action_name not in SUPPORTED_ACTIONS:
            raise ValueError(f"AI returned unsupported action {action_name!r}.")
        
        validated = ImageAction.model_validate({**action})
        normalized_actions.append(validated)

    data["actions"] = normalized_actions
    try:
        return AstraBotPlan.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"Action plan validation failed: {exc}") from exc

def _load_image(image_bytes: bytes) -> Image.Image:
    if not image_bytes:
        raise InvalidImageError("Please upload a non-empty image.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise InvalidImageError("Image is too large. Maximum upload size is 12 MB.")

    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise InvalidImageError("Image dimensions exceed the 40-megapixel limit.")
            image = ImageOps.exif_transpose(source).convert("RGB")
    except InvalidImageError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise InvalidImageError("The uploaded file is not a valid, supported image.") from exc

    return image

def _load_banner_font(size: int, text: str) -> ImageFont.ImageFont:
    font_paths = []
    if DEVANAGARI_RE.search(text):
        font_paths.extend(("C:\\Windows\\Fonts\\Nirmala.ttc", "C:\\Windows\\Fonts\\NirmalaB.ttc", "C:\\Windows\\Fonts\\mangal.ttf"))
    font_paths.extend(("C:\\Windows\\Fonts\\arialbd.ttf", "C:\\Windows\\Fonts\\arial.ttf", "arial.ttf"))

    for font_path in font_paths:
        try:
            return ImageFont.truetype(font_path, size=size)
        except OSError:
            continue
    if DEVANAGARI_RE.search(text):
        raise OllamaResponseError("Hindi text cannot be rendered. Please install Nirmala UI font.")
    return ImageFont.load_default()

def _validate_output_size(width: int, height: int) -> None:
    if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
        raise AstraBotError("The requested edit would exceed the 40-megapixel output limit.")

def _color_to_rgb(color_name: str) -> tuple[int, int, int]:
    color_map = {
        COLOR_BLACK: (0, 0, 0),
        COLOR_WHITE: (255, 255, 255),
        COLOR_RED: (255, 0, 0),
        COLOR_GREEN: (0, 128, 0),
        COLOR_BLUE: (0, 0, 255),
        COLOR_YELLOW: (255, 255, 0),
    }
    if color_name.lower() in color_map:
        return color_map[color_name.lower()]
    if re.fullmatch(r"[0-9A-Fa-f]{6}", color_name.lstrip("#")):
        hex_color = color_name.lstrip("#")
        return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return color_map[COLOR_WHITE]

def _add_text_to_image(image: Image.Image, text: str, position: str = POSITION_BOTTOM_RIGHT, font_size: int = 32, color: str = COLOR_WHITE) -> Image.Image:
    draw = ImageDraw.Draw(image)
    font = _load_banner_font(font_size, text)
    bbox = font.getbbox(text)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    img_w, img_h = image.size
    padding = max(8, font_size // 4)

    positions = {
        POSITION_CENTER: ((img_w - text_w) // 2, (img_h - text_h) // 2),
        POSITION_TOP: ((img_w - text_w) // 2, padding),
        POSITION_BOTTOM: ((img_w - text_w) // 2, img_h - text_h - padding),
        POSITION_LEFT: (padding, (img_h - text_h) // 2),
        POSITION_RIGHT: (img_w - text_w - padding, (img_h - text_h) // 2),
        POSITION_TOP_LEFT: (padding, padding),
        POSITION_TOP_RIGHT: (img_w - text_w - padding, padding),
        POSITION_BOTTOM_LEFT: (padding, img_h - text_h - padding),
        POSITION_BOTTOM_RIGHT: (img_w - text_w - padding, img_h - text_h - padding),
    }
    x, y = positions.get(position, positions[POSITION_BOTTOM_RIGHT])

    fill_rgb = _color_to_rgb(color)
    draw.text((x, y), text, fill=fill_rgb, font=font)
    return image

def _get_current_date(date_format: str = DATE_FORMAT_DD_MM_YYYY) -> str:
    import zoneinfo
    try:
        tz = zoneinfo.ZoneInfo(DEFAULT_TIMEZONE)
    except Exception:
        tz = timezone.utc
    now = datetime.now(tz)

    if date_format == DATE_FORMAT_DD_MM_YYYY: return now.strftime('%d/%m/%Y')
    if date_format == DATE_FORMAT_YYYY_MM_DD: return now.strftime('%Y-%m-%d')
    if date_format == DATE_FORMAT_HINDI: return now.strftime('%d %B %Y')
    return now.strftime('%d/%m/%Y')

def _add_date_to_image(image: Image.Image, date_format: str = DATE_FORMAT_DD_MM_YYYY, position: str = POSITION_BOTTOM_RIGHT) -> Image.Image:
    date_text = _get_current_date(date_format)
    return _add_text_to_image(image, date_text, position=position)

def _encode_jpeg(image: Image.Image, quality: int = 90) -> bytes:
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=quality, optimize=True)
    return output.getvalue()

def _compress_to_limit(image: Image.Image, max_kb: int) -> bytes:
    max_bytes = max_kb * 1024
    working = image
    for _ in range(12):
        for quality in range(90, 14, -5):
            result = _encode_jpeg(working, quality)
            if len(result) <= max_bytes:
                return result
        if working.width <= 1 or working.height <= 1:
            break
        next_size = (max(1, int(working.width * 0.85)), max(1, int(working.height * 0.85)))
        working = working.resize(next_size, Image.Resampling.LANCZOS)
    raise AstraBotError(f"Could not fit this image within {max_kb} KB.")

def _apply_action(image: Image.Image, action: ImageAction, candidate_name: str | None = None) -> Image.Image:
    if action.action == ACTION_ADD_TEXT:
        return _add_text_to_image(image, action.text or "", position=action.position or POSITION_BOTTOM_RIGHT, font_size=action.font_size or 32, color=action.color or COLOR_WHITE)
    if action.action == ACTION_ADD_DATE:
        return _add_date_to_image(image, date_format=action.date_format or DATE_FORMAT_DD_MM_YYYY, position=action.position or POSITION_BOTTOM_RIGHT)
    if action.action == ACTION_ADD_CAPTION:
        return _add_text_to_image(image, action.text or "", position=action.position or POSITION_BOTTOM_RIGHT, font_size=action.font_size or 28, color=action.color or COLOR_WHITE)
    if action.action == ACTION_RESIZE:
        if action.width is None or action.height is None: raise OllamaResponseError("resize requires width and height")
        _validate_output_size(action.width, action.height)
        return image.resize((action.width, action.height), Image.Resampling.LANCZOS)
    if action.action == ACTION_COMPRESS:
        if action.max_kb is None: raise OllamaResponseError("compress requires max_kb")
        return _compress_to_limit(image, action.max_kb)
    if action.action == ACTION_CROP:
        if action.crop_box is None: raise OllamaResponseError("crop requires crop_box")
        left, top, right, bottom = action.crop_box
        width, height = image.size
        crop_box = (int(left * width), int(top * height), int(right * width), int(bottom * height))
        _validate_output_size(crop_box[2] - crop_box[0], crop_box[3] - crop_box[1])
        return image.crop(crop_box)
    if action.action == ACTION_ROTATE:
        if action.angle is None: raise OllamaResponseError("rotate requires angle")
        radians = math.radians(action.angle)
        rotated_width = math.ceil(image.width * abs(math.cos(radians)) + image.height * abs(math.sin(radians)))
        rotated_height = math.ceil(image.height * abs(math.cos(radians)) + image.width * abs(math.sin(radians)))
        _validate_output_size(rotated_width, rotated_height)
        return image.rotate(action.angle, resample=Image.Resampling.BICUBIC, expand=True)
    if action.action == ACTION_ADJUST_BRIGHTNESS:
        factor = action.brightness or 1.2
        return ImageEnhance.Brightness(image).enhance(factor)
    
    # Text image pe overwrite ho jata hai, so skipping complex ones for now
    return image

# ==========================================
# GROQ API REQUEST LOGIC
# ==========================================
async def _request_plan(prompt: str, image_bytes: bytes, candidate_name: str | None) -> AstraBotPlan:
    image_base64 = base64.b64encode(image_bytes).decode("ascii")
    
    user_content = f"User request: {prompt.strip()}"
    if candidate_name and candidate_name.strip():
        user_content += f"\nCandidate name for a requested banner (use exactly): {candidate_name.strip()}"

    schema_str = json.dumps(AstraBotPlan.model_json_schema())
    system_instruction = (
        "You are AstraBot, an image-action planner. Understand Hindi, English, and Hinglish requests. "
        "Return ONLY a valid JSON object matching this exact schema: " + schema_str + "\n"
        "Always put the action name in the `action` field. Choose from: add_text, add_date, add_caption, resize, compress, crop, rotate, adjust_brightness, describe, unsupported. "
        "Use 'unsupported' for generative edits. Keep the message concise and in the user's language."
    )

    try:
        client = AsyncGroq(api_key=GROQ_API_KEY)
        
        chat_completion = await client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": system_instruction + "\n\n" + user_content},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                        },
                    ],
                }
            ],
            model="qwen/qwen3.8-27b", # Working Groq model with vision support
            temperature=0,
            max_tokens=1024
        )
        
        content = chat_completion.choices[0].message.content
        if not content:
            raise ValueError("AI returned an empty response.")
    except Exception as exc:
        raise OllamaUnavailableError(f"Groq API Error: {str(exc)}")

    try:
        return _parse_plan(content)
    except (ValidationError, ValueError) as exc:
        raise OllamaResponseError(f"AI returned an invalid action plan: {exc}") from exc

# ==========================================
# MAIN EXECUTION
# ==========================================
async def process_image_with_pure_ai(prompt: str, image_bytes: bytes, candidate_name: str | None = None) -> tuple[bytes | None, str]:
    if not prompt.strip():
        raise AstraBotError("Please enter an image instruction.")

    image = _load_image(image_bytes)

    # Quick Regex check for Name/Date (Fast Path)
    if any(w in prompt.lower() for w in ["name", "naam", "नाम", "date", "tarikh", "तारीख"]):
        # Directly let the AI handle it for better accuracy
        pass

    # Groq API Call
    plan = await _request_plan(prompt, image_bytes, candidate_name)

    if plan.actions[0].action in (ACTION_UNSUPPORTED, ACTION_DESCRIBE):
        return None, plan.message

    for action in plan.actions:
        if action.action == ACTION_COMPRESS:
            if action.max_kb is None: raise OllamaResponseError("AI omitted max size.")
            compressed = _compress_to_limit(image, action.max_kb)
            actual_kb = len(compressed) / 1024
            achieved = "achieved" if actual_kb <= action.max_kb else "not achieved"
            return compressed, f"{plan.message} Actual size: {actual_kb:.1f} KB (target {action.max_kb} KB, {achieved})."
        image = _apply_action(image, action, candidate_name)

    return _encode_jpeg(image), plan.message

# Backward-compatible names
parse_voice_command_with_ai = process_image_with_pure_ai
parse_voice_command = process_image_with_pure_ai