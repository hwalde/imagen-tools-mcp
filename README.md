# Imagen Tools MCP Server

MCP-Server (stdio, Python) für Bildgenerierung und -bearbeitung mit Google Gemini — über
**Vertex AI** oder **AI Studio**. Läuft auf Windows, macOS und Linux.

## Features

- **Bildgenerierung** mit `gemini-3.1-flash-image` (schnell) oder `gemini-3-pro-image` (Qualität)
- **Bildbearbeitung** bestehender Bilder per Prompt (Eingabebilder werden automatisch
  heruntergerechnet, inkl. EXIF-Rotation)
- **Provider-/Modell-Wechsel zur Laufzeit** über eigene Tools
- **Auflösungen** 1K, 2K, 4K · **Aspect Ratios** 1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3, 4:5, 5:4, 21:9
- Sprechende Fehlerbehandlung für abgelaufene Credentials, Rate Limits und die bekannte
  Flash+AI-Studio-Editing-Macke

## Schnellstart

```bash
pip install -r requirements.txt
gcloud auth application-default login
```

MCP-Eintrag (`~/.claude.json`):

```json
{
  "mcpServers": {
    "imagen-tools": {
      "type": "stdio",
      "command": "python3",
      "args": ["/absoluter/pfad/zu/imagen_tools_mcp.py"],
      "env": { "GOOGLE_CLOUD_PROJECT": "deine-projekt-id" }
    }
  }
}
```

## Tools

| Tool | Zweck |
|---|---|
| `create_image_using_gemini` | Bild erzeugen (`prompt`, `aspect_ratio`, `image_size`) |
| `edit_image_using_gemini` | Bild bearbeiten (`image_path`, `prompt`, `image_size`) |
| `switch_provider` | `vertex_ai` ⇄ `ai_studio` |
| `switch_model` | Flash ⇄ Pro |
| `get_config` | Aktuelle Konfiguration anzeigen |

## Dokumentation

**Vollständige Setup-, Konfigurations- und Betriebsdoku inklusive aller Umgebungsvariablen und
Fallstricke: [CLAUDE.md](./CLAUDE.md).**

## Version

0.6.0

## Lizenz

Proprietär
