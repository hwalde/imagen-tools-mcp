# Imagen Tools MCP Server

**Bilder erzeugen und bearbeiten mit Google Gemini — direkt aus deinem Coding-Agenten.**

Ein MCP-Server, der `gemini-3.1-flash-image` und `gemini-3-pro-image` anbindet — wahlweise über
**Vertex AI** oder **AI Studio**, umschaltbar zur Laufzeit, ohne Neustart.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

---

## Features

- **Bilder erzeugen** in 1K, 2K oder 4K — Aspect Ratios von 1:1 über 16:9 bis 21:9
- **Bilder bearbeiten** per Prompt; Eingabebilder werden automatisch passend heruntergerechnet,
  inklusive EXIF-Rotation, damit auch ein Hochkant-Handyfoto sauber durchläuft
- **Provider und Modell zur Laufzeit wechseln** — Flash für Tempo, Pro für Qualität
- **Fehler, die weiterhelfen:** Bei abgelaufenen Credentials, Rate Limits oder der bekannten
  Flash-über-AI-Studio-Macke beim Editieren bekommt der Agent keinen Stacktrace, sondern den
  konkreten nächsten Schritt

## Tools

| Tool | Zweck |
|---|---|
| `create_image_using_gemini` | Bild erzeugen (`prompt`, `aspect_ratio`, `image_size`) |
| `edit_image_using_gemini` | Bild bearbeiten (`image_path`, `prompt`, `image_size`) |
| `switch_provider` | `vertex_ai` ⇄ `ai_studio` |
| `switch_model` | Flash ⇄ Pro |
| `get_config` | Aktuelle Konfiguration anzeigen |

Erzeugte Bilder landen in einer temporären Datei; der Tool-Output ist der Pfad dorthin.

## Installation

```bash
pip install -r requirements.txt
gcloud auth application-default login
```

Dann in `~/.claude.json` eintragen:

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

Unter Windows `"command": "python"` verwenden. Für den Betrieb über Vertex AI brauchst du ein
Google-Cloud-Projekt mit aktivierter Vertex-AI-API; alternativ genügt für `ai_studio` ein
Gemini-API-Key.

## Gut zu wissen

- **Prompts sollten mit „Generate" oder „Create" beginnen.** Beschreibende Fließtexte ohne
  Handlungsverb liefern spürbar schlechtere Bilder.
- **Editing mit Flash funktioniert nur über `vertex_ai`.** Über AI Studio wirft diese Kombination
  reproduzierbar 500er — dann auf das Pro-Modell oder auf Vertex wechseln.
- **Rate Limit erwischt?** `switch_provider` weicht auf den jeweils anderen Provider aus.

## Dokumentation

Vollständige Setup-, Konfigurations- und Betriebsdoku — alle Umgebungsvariablen, Google-Cloud-Auth
und die Fallstricke im Detail: **[AGENTS.md](./AGENTS.md)**.

## Version

0.6.0

## Lizenz

[MIT](./LICENSE) © Herbert Walde
