import os
import asyncio
import tempfile
import logging
import traceback
import base64
from datetime import datetime

# ───────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ───────────────────────────────────────────────────────────────────────────────
DEBUG_ENABLED = True  # Set to True to enable debug logging

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
# Google Gen AI SDK Configuration (Vertex AI)
# ───────────────────────────────────────────────────────────────────────────────
# Prerequisites:
#   1. gcloud auth application-default login
#   2. Set environment variable GOOGLE_CLOUD_PROJECT to your GCP project ID
#      Windows: setx GOOGLE_CLOUD_PROJECT "your-project-id"
#      Linux/Mac: export GOOGLE_CLOUD_PROJECT="your-project-id"
#   3. (Optional) gcloud auth application-default set-quota-project <your-project-id>
# ───────────────────────────────────────────────────────────────────────────────
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

# Read project ID from environment variable
if "GOOGLE_CLOUD_PROJECT" not in os.environ:
    raise ValueError(
        "GOOGLE_CLOUD_PROJECT environment variable is not set.\n"
        "Please set it to your Google Cloud project ID:\n"
        "  Windows: setx GOOGLE_CLOUD_PROJECT \"your-project-id\"\n"
        "  Linux/Mac: export GOOGLE_CLOUD_PROJECT=\"your-project-id\""
    )

os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
logger.info(f"Using GCP Project: {os.environ['GOOGLE_CLOUD_PROJECT']}")

logger.info("Loading SDK...")
try:
    from google import genai
    from google.genai.types import GenerateContentConfig, Modality, ImageConfig
    from PIL import Image
    logger.info("SDK imports OK")
except Exception as e:
    logger.error(f"Import failed: {e}\n{traceback.format_exc()}")
    raise

MODEL_ID = "gemini-3-pro-image-preview"
logger.info(f"Model: {MODEL_ID}")

# Initialize client at module load time (BEFORE async event loop starts)
# This ensures credentials are loaded synchronously, avoiding hangs in MCP context
logger.info("Creating client...")
try:
    client = genai.Client()
    # Force credential loading by making a real API call (not just accessing _credentials)
    # This triggers the OAuth token refresh synchronously before the event loop starts
    logger.info("Warming up credentials with real API call...")
    _warmup = client.models.list(config={"page_size": 1})
    # Consume the iterator to actually make the request
    try:
        next(iter(_warmup))
    except StopIteration:
        pass
    logger.info("Client created and warmed up OK")
except Exception as e:
    logger.error(f"Client creation failed: {e}")
    raise


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


async def _call_gemini_image(prompt: str, aspect_ratio: str = "16:9", image_size: str = "2K") -> str:
    normalized_size = _normalize_image_size(image_size)
    logger.info(f"_call_gemini_image: prompt={prompt[:80]}..., aspect_ratio={aspect_ratio}, image_size={image_size} -> {normalized_size}")
    config = GenerateContentConfig(
        response_modalities=[Modality.TEXT, Modality.IMAGE],
        image_config=ImageConfig(
            aspectRatio=aspect_ratio,  # camelCase for API
            imageSize=normalized_size  # "1K", "2K", "4K"
        )
    )

    logger.info("API call starting...")

    # Use synchronous client in a thread to avoid blocking the event loop
    def generate_sync():
        return client.models.generate_content(model=MODEL_ID, contents=prompt, config=config)

    response = await asyncio.wait_for(
        asyncio.to_thread(generate_sync),
        timeout=300.0  # 5 minutes timeout (4K images can take longer)
    )
    logger.info("API call done")
    logger.info(f"Response type: {type(response)}")
    logger.info(f"Has 'parts': {hasattr(response, 'parts')}")
    logger.info(f"Has 'candidates': {hasattr(response, 'candidates')}")

    # Try response.parts first (new SDK structure)
    parts = None
    if hasattr(response, 'parts') and response.parts:
        parts = response.parts
        logger.info(f"Using response.parts (count: {len(parts)})")
    # Fallback to candidates structure (old SDK)
    elif hasattr(response, 'candidates') and response.candidates:
        candidate = response.candidates[0]
        if hasattr(candidate, 'content') and candidate.content and hasattr(candidate.content, 'parts'):
            parts = candidate.content.parts
            logger.info(f"Using response.candidates[0].content.parts (count: {len(parts)})")

    if not parts:
        raise ValueError("No parts found in response")

    image_data, mime_type = None, "image/png"
    for i, part in enumerate(parts):
        logger.info(f"Part {i}: has inline_data={hasattr(part, 'inline_data')}, has text={hasattr(part, 'text')}, has as_image={hasattr(part, 'as_image')}")

        # Log what's in inline_data
        if hasattr(part, 'inline_data'):
            inline = part.inline_data
            logger.info(f"  inline_data type: {type(inline)}")
            logger.info(f"  inline_data value: {inline}")
            if inline:
                logger.info(f"  inline_data.data type: {type(inline.data) if hasattr(inline, 'data') else 'N/A'}")
                logger.info(f"  inline_data.data length: {len(inline.data) if hasattr(inline, 'data') and inline.data else 0}")

        # Log what's in text
        if hasattr(part, 'text'):
            text_val = part.text
            logger.info(f"  text type: {type(text_val)}, length: {len(text_val) if text_val else 0}")
            if text_val:
                logger.info(f"  text preview: {text_val[:100]}")

        # Try inline_data.data directly (base64 encoded)
        if hasattr(part, 'inline_data') and part.inline_data and hasattr(part.inline_data, 'data') and part.inline_data.data:
            raw_data = part.inline_data.data
            mime_type = getattr(part.inline_data, 'mime_type', None) or "image/png"

            # Check if data is base64 string or bytes
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
    
    ext = ".jpg" if "jpeg" in mime_type or "jpg" in mime_type else ".png"
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as f:
        f.write(image_data)
        logger.info(f"Saved: {f.name}")
        return f.name


async def _edit_gemini_image(image_path: str, prompt: str, image_size: str = None) -> str:
    """
    Edits an existing image using Gemini.
    Note: image_size parameter is currently ignored as GenerateContentConfig
    doesn't support ImageConfig. The output size depends on the model.
    """
    logger.info(f"_edit_gemini_image: {image_path}")
    if not os.path.exists(image_path):
        raise ValueError(f"Not found: {image_path}")

    input_image = Image.open(image_path)
    config = GenerateContentConfig(response_modalities=[Modality.TEXT, Modality.IMAGE])

    logger.info("API edit call starting...")

    # Use synchronous client in a thread to avoid blocking the event loop
    def generate_sync():
        return client.models.generate_content(model=MODEL_ID, contents=[input_image, prompt], config=config)

    response = await asyncio.wait_for(
        asyncio.to_thread(generate_sync),
        timeout=300.0  # 5 minutes timeout (4K images can take longer)
    )
    logger.info("API edit call done")

    # Try response.parts first (new SDK structure)
    parts = None
    if hasattr(response, 'parts') and response.parts:
        parts = response.parts
    elif hasattr(response, 'candidates') and response.candidates:
        candidate = response.candidates[0]
        if hasattr(candidate, 'content') and candidate.content and hasattr(candidate.content, 'parts'):
            parts = candidate.content.parts

    if not parts:
        raise ValueError("No parts found in response")

    image_data, mime_type = None, "image/png"
    for part in parts:
        if hasattr(part, 'inline_data') and part.inline_data and hasattr(part.inline_data, 'data') and part.inline_data.data:
            raw_data = part.inline_data.data
            mime_type = getattr(part.inline_data, 'mime_type', None) or "image/png"

            # Check if data is base64 string or bytes
            if isinstance(raw_data, str):
                image_data = base64.b64decode(raw_data)
            elif isinstance(raw_data, bytes):
                image_data = raw_data
            else:
                continue
            break

    if not image_data:
        raise ValueError("No image data")
    
    ext = ".jpg" if "jpeg" in mime_type or "jpg" in mime_type else ".png"
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as f:
        f.write(image_data)
        logger.info(f"Edited saved: {f.name}")
        return f.name


# ───────────────────────────────────────────────────────────────────────────────
# MCP Server
# ───────────────────────────────────────────────────────────────────────────────
logger.info("Loading MCP...")
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types
logger.info("MCP loaded")

app = Server("imagen_tools", version="0.5.0")


@app.list_tools()
async def list_tools():
    logger.info("list_tools()")
    return [
        types.Tool(
            name="create_image_using_gemini",
            description="Create image with Gemini. Supports aspect_ratio (1:1, 16:9, 9:16, 4:3, 3:4, etc.) and image_size (1K, 2K, 4K for resolution).",
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
            description="Edit existing image with Gemini.",
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
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    logger.info(f"call_tool: {name} {arguments}")
    try:
        if name == "create_image_using_gemini":
            path = await _call_gemini_image(arguments["prompt"], arguments.get("aspect_ratio", "16:9"), arguments.get("image_size", "2K"))
            return [types.TextContent(type="text", text=path)]
        if name == "edit_image_using_gemini":
            path = await _edit_gemini_image(arguments["image_path"], arguments["prompt"], arguments.get("image_size"))
            return [types.TextContent(type="text", text=path)]
        raise ValueError(f"Unknown: {name}")
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
