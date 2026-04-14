import os
import asyncio
import tempfile
import logging
import traceback
import base64
from datetime import datetime

# ───────────────────────────────────────────────────────────────────────────────
# CONFIGURATION / FEATURE FLAGS
# ───────────────────────────────────────────────────────────────────────────────
DEBUG_ENABLED = True  # Set to True to enable debug logging

# Defaults at startup
DEFAULT_PROVIDER = "vertex_ai"  # "vertex_ai" or "ai_studio"
DEFAULT_MODEL = "gemini-3.1-flash-image-preview"  # or "gemini-3-pro-image-preview"

# AI Studio API Key (only needed when provider = "ai_studio")
# Set via environment variable GEMINI_API_KEY_NANO_BANANA or in .claude.json env config
AI_STUDIO_API_KEY = os.environ.get("GEMINI_API_KEY_NANO_BANANA", "")

# ───────────────────────────────────────────────────────────────────────────────
# DEBUG LOGGING (controlled by DEBUG_ENABLED flag)
# ───────────────────────────────────────────────────────────────────────────────
LOG_FILE = os.path.expanduser("~/mcp/imagen_tools_debug.log")
if DEBUG_ENABLED:
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(funcName)s - %(message)s',
        handlers=[logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')]
    )
else:
    logging.basicConfig(level=logging.CRITICAL)  # Suppress all logs

logger = logging.getLogger(__name__)
logger.info("=" * 70)
logger.info(f"MCP Server STARTING at {datetime.now()}")

# ───────────────────────────────────────────────────────────────────────────────
# Google Gen AI SDK - Import
# ───────────────────────────────────────────────────────────────────────────────
logger.info("Loading SDK...")
try:
    from google import genai
    from google.genai.types import GenerateContentConfig, Modality, ImageConfig
    from PIL import Image
    logger.info("SDK imports OK")
except Exception as e:
    logger.error(f"Import failed: {e}\n{traceback.format_exc()}")
    raise

# ───────────────────────────────────────────────────────────────────────────────
# Runtime state (mutable - changed via switch_provider / switch_model tools)
# ───────────────────────────────────────────────────────────────────────────────
_state = {
    "provider": DEFAULT_PROVIDER,
    "model": DEFAULT_MODEL,
    "client": None,
}


def _create_client(provider: str) -> genai.Client:
    """Create a genai Client for the given provider."""
    if provider == "vertex_ai":
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
        if "GOOGLE_CLOUD_PROJECT" not in os.environ:
            raise ValueError("GOOGLE_CLOUD_PROJECT environment variable is not set.")
        os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
        logger.info(f"Creating Vertex AI client - Project: {os.environ['GOOGLE_CLOUD_PROJECT']}")
        return genai.Client()
    elif provider == "ai_studio":
        os.environ.pop("GOOGLE_GENAI_USE_VERTEXAI", None)
        logger.info(f"Creating AI Studio client - API Key: {AI_STUDIO_API_KEY[:10]}...")
        return genai.Client(api_key=AI_STUDIO_API_KEY)
    else:
        raise ValueError(f"Unknown provider: {provider}. Use 'vertex_ai' or 'ai_studio'.")


def _init_client():
    """Initialize the client for the current provider and warm it up."""
    _state["client"] = _create_client(_state["provider"])
    logger.info("Warming up credentials with real API call...")
    _warmup = _state["client"].models.list(config={"page_size": 1})
    try:
        next(iter(_warmup))
    except StopIteration:
        pass
    logger.info(f"Client ready - provider={_state['provider']}, model={_state['model']}")


# Initialize on startup
logger.info(f"Default provider: {DEFAULT_PROVIDER}, model: {DEFAULT_MODEL}")
try:
    _init_client()
except Exception as e:
    logger.error(f"Client creation failed: {e}")
    raise


def _other_provider() -> str:
    return "ai_studio" if _state["provider"] == "vertex_ai" else "vertex_ai"


def _other_model() -> str:
    return "gemini-3-pro-image-preview" if _state["model"] == "gemini-3.1-flash-image-preview" else "gemini-3.1-flash-image-preview"


def _status_text() -> str:
    return f"[Aktuelle Konfiguration: provider={_state['provider']}, model={_state['model']}]"


# ───────────────────────────────────────────────────────────────────────────────
# Image generation / editing
# ───────────────────────────────────────────────────────────────────────────────

def _normalize_image_size(size: str) -> str:
    """Normalize image_size to valid API values: 1K, 2K, 4K"""
    if not size:
        return "2K"
    size_upper = size.upper().strip()
    # Direct match
    if size_upper in ("1K", "2K", "4K"):
        return size_upper
    # Handle variations like "4096x2304", "4096", "4k"
    if "4" in size_upper or "4096" in size_upper:
        return "4K"
    if "2" in size_upper or "2048" in size_upper:
        return "2K"
    if "1" in size_upper or "1024" in size_upper:
        return "1K"
    return "2K"  # Default


def _extract_image_data(response) -> tuple:
    """Extract image data and mime_type from a Gemini response. Returns (bytes, mime_type)."""
    parts = None
    if hasattr(response, 'parts') and response.parts:
        parts = response.parts
        logger.info(f"Using response.parts (count: {len(parts)})")
    elif hasattr(response, 'candidates') and response.candidates:
        candidate = response.candidates[0]
        if hasattr(candidate, 'content') and candidate.content and hasattr(candidate.content, 'parts'):
            parts = candidate.content.parts
            logger.info(f"Using response.candidates[0].content.parts (count: {len(parts)})")

    if not parts:
        raise ValueError("No parts found in response")

    image_data, mime_type = None, "image/png"
    for i, part in enumerate(parts):
        logger.info(f"Part {i}: has inline_data={hasattr(part, 'inline_data')}, has text={hasattr(part, 'text')}")

        if hasattr(part, 'inline_data') and part.inline_data and hasattr(part.inline_data, 'data') and part.inline_data.data:
            raw_data = part.inline_data.data
            mime_type = getattr(part.inline_data, 'mime_type', None) or "image/png"

            if isinstance(raw_data, str):
                logger.info(f"Decoding base64 string (length: {len(raw_data)})")
                image_data = base64.b64decode(raw_data)
            elif isinstance(raw_data, bytes):
                logger.info(f"Using raw bytes (length: {len(raw_data)})")
                image_data = raw_data
            else:
                logger.warning(f"Unknown data type: {type(raw_data)}")
                continue

            logger.info(f"Image data extracted: {len(image_data)} bytes, {mime_type}")
            break

    if not image_data:
        raise ValueError("No image data found in any part")

    return image_data, mime_type


def _save_image(image_data: bytes, mime_type: str) -> str:
    """Save image data to a temp file and return the path."""
    ext = ".jpg" if "jpeg" in mime_type or "jpg" in mime_type else ".png"
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as f:
        f.write(image_data)
        logger.info(f"Saved: {f.name}")
        return f.name


async def _call_gemini_image(prompt: str, aspect_ratio: str = "16:9", image_size: str = "2K") -> str:
    normalized_size = _normalize_image_size(image_size)
    logger.info(f"_call_gemini_image: prompt={prompt[:80]}..., aspect_ratio={aspect_ratio}, image_size={image_size} -> {normalized_size}")
    logger.info(f"  provider={_state['provider']}, model={_state['model']}")

    config = GenerateContentConfig(
        response_modalities=[Modality.TEXT, Modality.IMAGE],
        image_config=ImageConfig(
            aspectRatio=aspect_ratio,
            imageSize=normalized_size
        )
    )

    logger.info("API call starting...")

    def generate_sync():
        return _state["client"].models.generate_content(
            model=_state["model"], contents=prompt, config=config
        )

    response = await asyncio.wait_for(
        asyncio.to_thread(generate_sync),
        timeout=300.0
    )
    logger.info("API call done")

    image_data, mime_type = _extract_image_data(response)
    return _save_image(image_data, mime_type)


async def _edit_gemini_image(image_path: str, prompt: str, image_size: str = None) -> str:
    logger.info(f"_edit_gemini_image: {image_path}")
    logger.info(f"  provider={_state['provider']}, model={_state['model']}")

    if not os.path.exists(image_path):
        raise ValueError(f"Not found: {image_path}")

    input_image = Image.open(image_path)
    config = GenerateContentConfig(response_modalities=[Modality.TEXT, Modality.IMAGE])

    logger.info("API edit call starting...")

    def generate_sync():
        return _state["client"].models.generate_content(
            model=_state["model"], contents=[input_image, prompt], config=config
        )

    response = await asyncio.wait_for(
        asyncio.to_thread(generate_sync),
        timeout=300.0
    )
    logger.info("API edit call done")

    image_data, mime_type = _extract_image_data(response)
    return _save_image(image_data, mime_type)


# ───────────────────────────────────────────────────────────────────────────────
# MCP Server
# ───────────────────────────────────────────────────────────────────────────────
logger.info("Loading MCP...")
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types
logger.info("MCP loaded")

app = Server("imagen_tools", version="0.6.0")


@app.list_tools()
async def list_tools():
    logger.info("list_tools()")
    return [
        types.Tool(
            name="create_image_using_gemini",
            description=(
                "Create image with Gemini. Supports aspect_ratio (1:1, 16:9, 9:16, 4:3, 3:4, etc.) and image_size (1K, 2K, 4K for resolution). "
                "Available models: 'gemini-3.1-flash-image-preview' (Flash, fast) and 'gemini-3-pro-image-preview' (Pro, higher quality). "
                "Use 'switch_model' to change the model."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Image description/prompt"},
                    "aspect_ratio": {"type": "string", "description": "Aspect ratio: 1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3, 4:5, 5:4, 21:9. Default: 16:9"},
                    "image_size": {"type": "string", "description": "Resolution: 1K, 2K, or 4K. Default: 2K"}
                },
                "required": ["prompt"]
            }
        ),
        types.Tool(
            name="edit_image_using_gemini",
            description=(
                "Edit existing image with Gemini. "
                "IMPORTANT: Editing with Flash model only works reliably via 'vertex_ai' provider. "
                "If using 'ai_studio', switch to Pro model ('switch_model') or to 'vertex_ai' ('switch_provider')."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "image_path": {"type": "string", "description": "Path to the image to edit"},
                    "prompt": {"type": "string", "description": "Edit instructions"},
                    "image_size": {"type": "string", "description": "Resolution: 1K, 2K, or 4K"}
                },
                "required": ["image_path", "prompt"]
            }
        ),
        types.Tool(
            name="switch_provider",
            description=(
                "Switch the API provider. Options: 'vertex_ai' (reliable for all operations, uses gcloud auth) "
                "or 'ai_studio' (uses API key, but Flash editing is unreliable). "
                "Models: 'gemini-3.1-flash-image-preview' (Flash) and 'gemini-3-pro-image-preview' (Pro). "
                "Use 'switch_model' to change the model. Call without arguments to see current config."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "Target provider: 'vertex_ai' or 'ai_studio'. Omit to see current config.", "enum": ["vertex_ai", "ai_studio"]}
                },
                "required": []
            }
        ),
        types.Tool(
            name="switch_model",
            description=(
                "Switch the model. Options: 'gemini-3-pro-image-preview' (Pro, higher quality, editing works on all providers) "
                "or 'gemini-3.1-flash-image-preview' (Flash, faster, but editing only works on 'vertex_ai' provider). "
                "Providers: 'vertex_ai' and 'ai_studio'. Use 'switch_provider' to change the provider. "
                "Call without arguments to see current config."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {"type": "string", "description": "Target model. Omit to see current config.", "enum": ["gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview"]}
                },
                "required": []
            }
        ),
        types.Tool(
            name="get_config",
            description="Show the current provider and model configuration.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
    ]


def _build_rate_limit_hint(operation: str) -> str:
    """Build a helpful hint message for rate limit errors."""
    other = _other_provider()
    return (
        f"Rate Limit erreicht bei provider={_state['provider']}. "
        f"Tipp: Verwende 'switch_provider' um auf '{other}' zu wechseln und versuche es erneut. "
        f"{_status_text()}"
    )


def _build_edit_flash_ai_studio_hint() -> str:
    """Build a hint for the known Flash+AI Studio edit problem."""
    return (
        "Image-Editing mit dem Flash-Modell ueber AI Studio ist bekannt unzuverlaessig (500 Internal Error). "
        "Verwende 'switch_provider' um auf 'vertex_ai' zu wechseln, oder "
        "'switch_model' um auf 'gemini-3-pro-image-preview' zu wechseln. "
        "Beide Alternativen funktionieren zuverlaessig fuer Editing. "
        f"{_status_text()}"
    )


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    logger.info(f"call_tool: {name} {arguments}")
    try:
        if name == "create_image_using_gemini":
            try:
                path = await _call_gemini_image(
                    arguments["prompt"],
                    arguments.get("aspect_ratio", "16:9"),
                    arguments.get("image_size", "2K")
                )
                return [types.TextContent(type="text", text=f"{path}\n{_status_text()}")]
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    hint = _build_rate_limit_hint("create")
                    logger.error(f"Rate limit hit: {e}")
                    return [types.TextContent(type="text", text=f"FEHLER: {error_str}\n\n{hint}")]
                raise

        if name == "edit_image_using_gemini":
            try:
                path = await _edit_gemini_image(
                    arguments["image_path"],
                    arguments["prompt"],
                    arguments.get("image_size")
                )
                return [types.TextContent(type="text", text=f"{path}\n{_status_text()}")]
            except Exception as e:
                error_str = str(e)
                # Known issue: Flash + AI Studio edit = 500
                if ("500" in error_str or "INTERNAL" in error_str) \
                        and _state["provider"] == "ai_studio" \
                        and "flash" in _state["model"].lower():
                    hint = _build_edit_flash_ai_studio_hint()
                    logger.error(f"Known Flash+AI Studio edit issue: {e}")
                    return [types.TextContent(type="text", text=f"FEHLER: {error_str}\n\n{hint}")]
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    hint = _build_rate_limit_hint("edit")
                    logger.error(f"Rate limit hit: {e}")
                    return [types.TextContent(type="text", text=f"FEHLER: {error_str}\n\n{hint}")]
                raise

        if name == "switch_provider":
            new_provider = arguments.get("provider")
            if not new_provider:
                return [types.TextContent(type="text", text=_status_text())]
            if new_provider == _state["provider"]:
                return [types.TextContent(type="text", text=f"Provider ist bereits '{new_provider}'. {_status_text()}")]
            old_provider = _state["provider"]
            _state["provider"] = new_provider
            try:
                _state["client"] = _create_client(new_provider)
                logger.info(f"Switched provider: {old_provider} -> {new_provider}")
                return [types.TextContent(type="text", text=f"Provider gewechselt: {old_provider} -> {new_provider}. {_status_text()}")]
            except Exception as e:
                _state["provider"] = old_provider
                _state["client"] = _create_client(old_provider)
                logger.error(f"Failed to switch provider: {e}")
                return [types.TextContent(type="text", text=f"FEHLER beim Provider-Wechsel: {e}. Zurueck auf '{old_provider}'. {_status_text()}")]

        if name == "switch_model":
            new_model = arguments.get("model")
            if not new_model:
                return [types.TextContent(type="text", text=_status_text())]
            if new_model == _state["model"]:
                return [types.TextContent(type="text", text=f"Modell ist bereits '{new_model}'. {_status_text()}")]
            old_model = _state["model"]
            _state["model"] = new_model
            logger.info(f"Switched model: {old_model} -> {new_model}")
            return [types.TextContent(type="text", text=f"Modell gewechselt: {old_model} -> {new_model}. {_status_text()}")]

        if name == "get_config":
            return [types.TextContent(type="text", text=_status_text())]

        raise ValueError(f"Unknown tool: {name}")
    except Exception as e:
        logger.error(f"Error: {e}\n{traceback.format_exc()}")
        raise


async def _main():
    logger.info("_main() start")
    async with stdio_server() as (r, w):
        logger.info("stdio ready")
        await app.run(r, w, app.create_initialization_options())


if __name__ == "__main__":
    logger.info("Starting...")
    asyncio.run(_main())
