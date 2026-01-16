# Imagen Tools MCP Server

MCP (Model Context Protocol) Server für Google Gemini Imagen-Bildgenerierung über Vertex AI.

## Features

- **Bildgenerierung**: Erstellt Bilder mit Gemini 3 Pro Image (`gemini-3-pro-image-preview`)
- **Bildbearbeitung**: Bearbeitet bestehende Bilder mit Prompts
- **Auflösungsunterstützung**: 1K, 2K, 4K
- **Aspect Ratios**: 1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3, 4:5, 5:4, 21:9
- **Base64-Dekodierung**: Automatische Handhabung von base64-kodierten Bilddaten

## Voraussetzungen

### Google Cloud Setup

1. Google Cloud SDK installieren
2. Authentifizierung einrichten:
   ```bash
   gcloud auth application-default login
   gcloud auth application-default set-quota-project gen-lang-client-0300367995
   ```

### Python Dependencies

```bash
pip install -r requirements.txt
```

Erfordert:
- `google-genai` >= 1.59.0
- `mcp`
- `Pillow`

## Verwendung

### Als MCP Server

In `~/.claude/settings.json` (oder entsprechender Konfiguration):

```json
{
  "mcpServers": {
    "imagen-tools": {
      "command": "python",
      "args": ["C:/Users/herbe/mcp/imagen_tools_mcp.py"]
    }
  }
}
```

### Tools

#### `create_image_using_gemini`

Erstellt ein neues Bild.

**Parameter:**
- `prompt` (required): Bildbeschreibung (sollte mit "Generate" oder "Create" beginnen)
- `aspect_ratio` (optional): Seitenverhältnis (default: "16:9")
- `image_size` (optional): Auflösung - "1K", "2K", "4K" (default: "2K")

**Beispiel:**
```python
create_image_using_gemini(
    prompt="Generate an infographic showing AI and human collaboration",
    aspect_ratio="16:9",
    image_size="4K"
)
```

#### `edit_image_using_gemini`

Bearbeitet ein bestehendes Bild.

**Parameter:**
- `image_path` (required): Pfad zum Quellbild
- `prompt` (required): Bearbeitungsanweisungen
- `image_size` (optional): Auflösung - "1K", "2K", "4K"

## Konfiguration

### Umgebungsvariablen

Werden automatisch im Code gesetzt:
- `GOOGLE_GENAI_USE_VERTEXAI=True`
- `GOOGLE_CLOUD_PROJECT=gen-lang-client-0300367995`
- `GOOGLE_CLOUD_LOCATION=global`

### Debug-Logging

Debug-Logging ist aktiviert und schreibt nach: `~/mcp/imagen_tools_debug.log`

Zum Deaktivieren: `DEBUG_ENABLED = False` in Zeile 11 setzen.

## Auflösungen

- **1K**: ~1376x768 (16:9) = 1.1 Megapixel
- **2K**: ~2752x1536 (16:9) = 4.2 Megapixel
- **4K**: ~5504x3072 (16:9) = 16.9 Megapixel

## Timeouts

- Standard: 300 Sekunden (5 Minuten)
- 4K-Bilder können 2-3 Minuten dauern

## Wichtige Hinweise

### Prompt-Format

Das Modell funktioniert am besten mit Prompts, die mit **"Generate"** oder **"Create"** beginnen.

❌ Schlecht:
```
Die moderne Softwareentwicklung hat sich verändert...
```

✅ Gut:
```
Generate an infographic illustrating modern software development...
```

### Response-Struktur

Die API gibt immer **TEXT** und **IMAGE** zurück. Bilddaten befinden sich in `response.parts` als base64-kodierte `inline_data`.

## Version

0.5.0

## Lizenz

Proprietär
