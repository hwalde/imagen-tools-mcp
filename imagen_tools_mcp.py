"""Imagen Tools MCP — Bilder erzeugen und bearbeiten über OpenRouter.

Modell: microsoft/mai-image-2.7 (OpenRouter Image API, POST /api/v1/images).
Genau zwei Tools: create_image und edit_image.

Der API-Key kommt ausschließlich aus OPENROUTER_API_KEY und wird nie geloggt
oder ausgegeben.
"""
import os
import re
import sys
import io
import time
import base64
import asyncio
import logging
import tempfile
import traceback
from datetime import datetime

# ───────────────────────────────────────────────────────────────────────────────
# KONFIGURATION
# ───────────────────────────────────────────────────────────────────────────────

MODEL = "microsoft/mai-image-2.7"
API_URL = "https://openrouter.ai/api/v1/images"
TIMEOUT_S = 300  # Bildgenerierung kann deutlich über 90 s dauern
ASPECT_RATIOS = ["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "auto"]
BACKGROUNDS = ["opaque", "transparent"]
MAX_REFERENCES = 5  # Limit von mai-image-2.7 (input_references)
# Eingabebilder werden vor dem Upload auf diese längste Kante verkleinert,
# damit große Kamerafotos den Request nicht unnötig aufblähen.
MAX_INPUT_EDGE = 2048


def _load_dotenv():
    """Lädt eine .env neben diesem Skript — nur als Fallback.

    Bereits gesetzte Umgebungsvariablen werden nie überschrieben."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


def _load_key_from_shell_files():
    """Fallback für Dienst-Betrieb (launchd/systemd lesen keine Shell-Startdateien).

    Statt den Key in eine weitere Datei zu kopieren (Drift bei Rotation), wird die
    Zeile `[export ]OPENROUTER_API_KEY=...` aus einer vorhandenen Datei gelesen:
    zuerst aus IMAGEN_MCP_KEY_FILE (falls gesetzt), sonst aus ~/.zshrc, dann ~/.bashrc.
    Die erste Datei mit Treffer gewinnt, innerhalb der Datei der letzte Treffer.
    Nur wenn die Variable nicht schon in der Umgebung steht."""
    if os.environ.get("OPENROUTER_API_KEY"):
        return
    candidates = [os.environ.get("IMAGEN_MCP_KEY_FILE"), "~/.zshrc", "~/.bashrc"]
    for cand in candidates:
        if not cand:
            continue
        value = None
        try:
            with open(os.path.expanduser(cand), "r", encoding="utf-8") as fh:
                for line in fh:
                    m = re.match(r'^\s*(?:export\s+)?OPENROUTER_API_KEY=(.+?)\s*$', line)
                    if m:
                        value = m.group(1).strip().strip('"').strip("'")
        except OSError:
            continue
        if value:
            os.environ["OPENROUTER_API_KEY"] = value
            return


_load_dotenv()
_load_key_from_shell_files()

DEBUG_ENABLED = os.environ.get("IMAGEN_MCP_DEBUG", "1") not in ("0", "false", "False")

# ───────────────────────────────────────────────────────────────────────────────
# LOGGING
# ───────────────────────────────────────────────────────────────────────────────
def _default_log_file() -> str:
    override = os.environ.get("IMAGEN_MCP_LOG_FILE")
    if override:
        return override
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "imagen-tools-mcp", "imagen_tools_debug.log")


LOG_FILE = _default_log_file()
if DEBUG_ENABLED:
    handlers = []
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        handlers.append(logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"))
    except OSError:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(funcName)s - %(message)s",
        handlers=handlers,
    )
else:
    logging.basicConfig(level=logging.CRITICAL)

logger = logging.getLogger("imagen_tools_mcp")
logger.info("=" * 70)
logger.info(f"MCP Server STARTING at {datetime.now()} (model={MODEL})")

import httpx
from PIL import Image, ImageOps
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, CallToolResult

app = Server("imagen-tools")


# ───────────────────────────────────────────────────────────────────────────────
# FEHLER
# ───────────────────────────────────────────────────────────────────────────────
class ToolError(Exception):
    """Fehler mit bereits verständlicher Meldung für den Agenten."""


_HTTP_HINTS = {
    400: "Ungültige Anfrage (Parameter prüfen, z. B. aspect_ratio oder Bildformat).",
    401: "OPENROUTER_API_KEY ungültig oder abgelaufen.",
    402: "Zu wenig Guthaben auf dem OpenRouter-Konto (https://openrouter.ai/settings/credits).",
    403: "Anfrage abgelehnt (Moderation/Inhaltsfilter). Prompt umformulieren.",
    404: "Modell oder Endpoint nicht gefunden.",
    408: "Zeitüberschreitung beim Anbieter.",
    429: "Rate-Limit erreicht – kurz warten und erneut versuchen.",
    502: "Anbieter-Fehler; fehlgeschlagene Generierungen werden nicht berechnet. Erneut versuchen.",
}


def _error_message(resp: httpx.Response) -> str:
    try:
        j = resp.json()
        err = j.get("error", j)
        if isinstance(err, dict):
            msg = err.get("message") or str(err)
            meta = err.get("metadata") or {}
            extra = meta.get("raw") or meta.get("reasons")
            if extra:
                msg += f" [{str(extra)[:400]}]"
            return msg
        return str(err)[:600]
    except Exception:
        return resp.text[:600] or "(keine Fehlermeldung)"


# ───────────────────────────────────────────────────────────────────────────────
# BILD-HILFEN
# ───────────────────────────────────────────────────────────────────────────────
def _image_to_data_url(path: str) -> str:
    """Lädt ein Bild, korrigiert EXIF-Rotation, verkleinert es und liefert eine Data-URL."""
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        raise ToolError(f"Bild nicht gefunden: {path}")
    try:
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img)
            has_alpha = img.mode in ("RGBA", "LA", "P")
            img = img.convert("RGBA" if has_alpha else "RGB")
            longest = max(img.size)
            if longest > MAX_INPUT_EDGE:
                scale = MAX_INPUT_EDGE / longest
                img = img.resize(
                    (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                    Image.Resampling.LANCZOS,
                )
            buf = io.BytesIO()
            if has_alpha:
                img.save(buf, "PNG", optimize=True)
                mime = "image/png"
            else:
                img.save(buf, "JPEG", quality=92)
                mime = "image/jpeg"
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Bild konnte nicht gelesen werden ({path}): {e}")
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _ext_for(media_type: str, data: bytes) -> str:
    mt = (media_type or "").lower()
    if "jpeg" in mt or "jpg" in mt or data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if "webp" in mt or data[8:12] == b"WEBP":
        return ".webp"
    return ".png"


def _save_image(data: bytes, media_type: str, output_path: str | None) -> str:
    ext = _ext_for(media_type, data)
    if output_path:
        out = os.path.abspath(os.path.expanduser(output_path))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        given_ext = os.path.splitext(out)[1].lower()
        fmt = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}.get(given_ext)
        if fmt is None:
            out = out + ext
        elif ext != {".jpeg": ".jpg"}.get(given_ext, given_ext):
            # Gewünschtes Format per Pillow herstellen.
            with Image.open(io.BytesIO(data)) as im:
                if fmt == "JPEG" and im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                im.save(out, fmt, **({"quality": 92} if fmt != "PNG" else {}))
            return out
        with open(out, "wb") as f:
            f.write(data)
        return out
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext, prefix="imagen_") as f:
        f.write(data)
        return f.name


def _pixels(data: bytes) -> str:
    try:
        with Image.open(io.BytesIO(data)) as im:
            return f"{im.width}x{im.height}"
    except Exception:
        return "?"


# ───────────────────────────────────────────────────────────────────────────────
# OPENROUTER-AUFRUF
# ───────────────────────────────────────────────────────────────────────────────
async def _generate(prompt: str, aspect_ratio: str | None, background: str | None,
                    image_paths: list[str], output_path: str | None) -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise ToolError("OPENROUTER_API_KEY ist nicht gesetzt (weder in der Umgebung noch in IMAGEN_MCP_KEY_FILE, ~/.zshrc oder ~/.bashrc).")
    if not prompt or not prompt.strip():
        raise ToolError("Leerer Prompt.")
    if aspect_ratio and aspect_ratio not in ASPECT_RATIOS:
        raise ToolError(f"aspect_ratio '{aspect_ratio}' nicht erlaubt. Erlaubt: {', '.join(ASPECT_RATIOS)}")
    if background and background not in BACKGROUNDS:
        raise ToolError(f"background '{background}' nicht erlaubt. Erlaubt: {', '.join(BACKGROUNDS)}")
    if len(image_paths) > MAX_REFERENCES:
        raise ToolError(f"Höchstens {MAX_REFERENCES} Eingabebilder erlaubt, übergeben: {len(image_paths)}")

    body: dict = {"model": MODEL, "prompt": prompt.strip()}
    if aspect_ratio:
        body["aspect_ratio"] = aspect_ratio
    if background:
        body["background"] = background
    if image_paths:
        body["input_references"] = [
            {"type": "image_url", "image_url": {"url": _image_to_data_url(p)}} for p in image_paths
        ]

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Title": "imagen-tools-mcp",
    }
    logger.info(f"POST {API_URL} model={MODEL} aspect={aspect_ratio} background={background} "
                f"inputs={len(image_paths)} prompt_len={len(body['prompt'])}")
    t0 = time.time()
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        resp = None
        for attempt in (1, 2):
            try:
                resp = await client.post(API_URL, json=body, headers=headers)
            except httpx.TimeoutException:
                raise ToolError(f"Zeitüberschreitung nach {TIMEOUT_S} s. Kein automatischer Neuversuch "
                                "(Generierung könnte bereits berechnet sein, siehe https://openrouter.ai/activity).")
            except httpx.HTTPError as e:
                raise ToolError(f"Netzwerkfehler: {e}")
            if resp.status_code >= 500 and attempt == 1:
                logger.warning(f"HTTP {resp.status_code}, neuer Versuch in 5 s")
                await asyncio.sleep(5)
                continue
            break
    dauer = round(time.time() - t0, 1)

    if resp.status_code != 200:
        msg = _error_message(resp)
        hint = _HTTP_HINTS.get(resp.status_code, "")
        logger.error(f"HTTP {resp.status_code}: {msg}")
        raise ToolError(f"OpenRouter HTTP {resp.status_code}: {msg}" + (f"\nHinweis: {hint}" if hint else ""))

    j = resp.json()
    data = j.get("data") or []
    if not data:
        raise ToolError("Antwort enthält kein Bild: " + str({k: v for k, v in j.items() if k != "data"})[:600])
    d = data[0]
    b64 = d.get("b64_json")
    if not b64 and str(d.get("url", "")).startswith("data:"):
        b64 = d["url"].partition(",")[2]
    if b64:
        img_bytes = base64.b64decode(b64)
    elif d.get("url"):
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(d["url"])
            r.raise_for_status()
            img_bytes = r.content
    else:
        raise ToolError("Bild-Eintrag ohne Bilddaten in der Antwort.")

    path = _save_image(img_bytes, d.get("media_type") or "", output_path)
    cost = (j.get("usage") or {}).get("cost")
    logger.info(f"Saved {path} ({_pixels(img_bytes)}) in {dauer}s cost={cost}")
    info = f"{path}\n({_pixels(img_bytes)} px, {dauer} s"
    if cost is not None:
        info += f", Kosten {cost} USD"
    return info + f", Modell {MODEL})"


# ───────────────────────────────────────────────────────────────────────────────
# TOOLS
# ───────────────────────────────────────────────────────────────────────────────
_OUTPUT_PATH_PROP = {
    "type": "string",
    "description": "Optional: Zielpfad für das Bild (.png/.jpg/.webp). Ohne Angabe landet es in einer temporären Datei.",
}
_BACKGROUND_PROP = {
    "type": "string",
    "enum": BACKGROUNDS,
    "description": "Optional: 'transparent' für freigestellte PNGs (z. B. Logos, Icons, Objekte).",
}


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="create_image",
            description=(
                f"Erzeugt ein neues Bild aus einem Text-Prompt mit {MODEL} über OpenRouter. "
                "Liefert den Pfad der gespeicherten Bilddatei zurück."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Ausführliche Bildbeschreibung."},
                    "aspect_ratio": {
                        "type": "string",
                        "enum": ASPECT_RATIOS,
                        "default": "16:9",
                        "description": "Seitenverhältnis. Default 16:9.",
                    },
                    "background": _BACKGROUND_PROP,
                    "output_path": _OUTPUT_PATH_PROP,
                },
                "required": ["prompt"],
            },
        ),
        Tool(
            name="edit_image",
            description=(
                f"Bearbeitet ein bestehendes Bild per Prompt mit {MODEL} über OpenRouter. "
                f"Optional bis zu {MAX_REFERENCES - 1} weitere Referenzbilder (z. B. Stil, Person, Objekt). "
                "Liefert den Pfad der gespeicherten Bilddatei zurück."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "image_path": {"type": "string", "description": "Absoluter Pfad zum Ausgangsbild."},
                    "prompt": {"type": "string", "description": "Was am Bild geändert werden soll."},
                    "reference_image_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": MAX_REFERENCES - 1,
                        "description": "Optional: weitere Referenzbilder (absolute Pfade).",
                    },
                    "aspect_ratio": {
                        "type": "string",
                        "enum": ASPECT_RATIOS,
                        "description": "Optional: Seitenverhältnis des Ergebnisses. Ohne Angabe entscheidet das Modell.",
                    },
                    "background": _BACKGROUND_PROP,
                    "output_path": _OUTPUT_PATH_PROP,
                },
                "required": ["image_path", "prompt"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    arguments = arguments or {}
    logger.info(f"call_tool: {name}")
    try:
        if name == "create_image":
            result = await _generate(
                prompt=arguments.get("prompt", ""),
                aspect_ratio=arguments.get("aspect_ratio") or "16:9",
                background=arguments.get("background"),
                image_paths=[],
                output_path=arguments.get("output_path"),
            )
        elif name == "edit_image":
            image_path = arguments.get("image_path")
            if not image_path:
                raise ToolError("image_path fehlt.")
            refs = arguments.get("reference_image_paths") or []
            result = await _generate(
                prompt=arguments.get("prompt", ""),
                aspect_ratio=arguments.get("aspect_ratio"),
                background=arguments.get("background"),
                image_paths=[image_path, *refs],
                output_path=arguments.get("output_path"),
            )
        else:
            raise ToolError(f"Unbekanntes Tool: {name}. Verfügbar: create_image, edit_image")
        return [TextContent(type="text", text=result)]
    except ToolError as e:
        return CallToolResult(content=[TextContent(type="text", text=f"Fehler: {e}")], isError=True)
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {e}\n{traceback.format_exc()}")
        return CallToolResult(content=[TextContent(type="text", text=f"Fehler: {type(e).__name__}: {e}")],
                              isError=True)


# ───────────────────────────────────────────────────────────────────────────────
# TRANSPORTE
# ───────────────────────────────────────────────────────────────────────────────
async def _main_stdio():
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())


HTTP_HOST = os.environ.get("IMAGEN_MCP_HOST", "127.0.0.1")  # NIE 0.0.0.0
HTTP_PORT = int(os.environ.get("IMAGEN_MCP_PORT", "8901"))


def _run_http():
    """Minimale ASGI-App für den MCP-Endpunkt unter /mcp.

    Bewusst ohne Starlette-Routing: dessen Mount("/mcp") antwortet auf POST /mcp
    mit einem 307 auf /mcp/, und Clients, die einem Redirect bei POST nicht
    folgen, scheitern daran. Hier werden /mcp und /mcp/ direkt bedient."""
    import uvicorn
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    session_manager = StreamableHTTPSessionManager(app=app, json_response=False)

    async def asgi_app(scope, receive, send):
        if scope["type"] == "lifespan":
            manager_cm = None
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    try:
                        manager_cm = session_manager.run()
                        await manager_cm.__aenter__()
                        logger.info(f"streamable-http ready on http://{HTTP_HOST}:{HTTP_PORT}/mcp")
                        await send({"type": "lifespan.startup.complete"})
                    except Exception as exc:
                        logger.error(f"Startup failed: {exc}")
                        await send({"type": "lifespan.startup.failed", "message": str(exc)})
                        return
                elif message["type"] == "lifespan.shutdown":
                    if manager_cm is not None:
                        try:
                            await manager_cm.__aexit__(None, None, None)
                        except Exception as exc:
                            logger.warning(f"Shutdown of session manager: {exc}")
                    await send({"type": "lifespan.shutdown.complete"})
                    return
            return

        if scope["type"] != "http":
            return

        if scope.get("path", "").rstrip("/") != "/mcp":
            await send({
                "type": "http.response.start",
                "status": 404,
                "headers": [(b"content-type", b"text/plain; charset=utf-8")],
            })
            await send({"type": "http.response.body", "body": b"Not Found"})
            return

        await session_manager.handle_request(scope, receive, send)

    uvicorn.run(asgi_app, host=HTTP_HOST, port=HTTP_PORT, log_level="info")


if __name__ == "__main__":
    transport = os.environ.get("IMAGEN_MCP_TRANSPORT", "stdio")
    args = sys.argv[1:]
    if "--transport" in args:
        transport = args[args.index("--transport") + 1]
    elif "--http" in args:
        transport = "streamable-http"
    transport = transport.replace("_", "-").lower()

    if not os.environ.get("OPENROUTER_API_KEY"):
        logger.warning("OPENROUTER_API_KEY fehlt – Tools antworten mit Fehlermeldung.")

    logger.info(f"Starting... transport={transport}")
    if transport in ("streamable-http", "http"):
        _run_http()
    elif transport == "stdio":
        asyncio.run(_main_stdio())
    else:
        raise SystemExit(f"Unbekannter Transport: {transport!r}. Erlaubt: stdio, streamable-http")
