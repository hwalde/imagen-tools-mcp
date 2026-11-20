# Imagen Tools MCP Server

**Bilder erzeugen und bearbeiten mit `microsoft/mai-image-2.7` über OpenRouter, direkt aus deinem Coding-Agenten.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)

## Tools

| Tool | Zweck |
|---|---|
| `create_image` | Bild erzeugen (`prompt`, `aspect_ratio`, `background`, `output_path`) |
| `edit_image` | Bild bearbeiten (`image_path`, `prompt`, `reference_image_paths`, `aspect_ratio`, `background`, `output_path`) |

Der Tool-Output enthält den Pfad zur Bilddatei, die Pixelgröße und die Kosten.

## Installation

```bash
pip install -r requirements.txt
export OPENROUTER_API_KEY=...   # z. B. in ~/.zshrc
```

```json
{ "mcpServers": { "imagen-tools": { "type": "stdio", "command": "python3",
  "args": ["/absoluter/pfad/zu/imagen_tools_mcp.py"] } } }
```

## Dokumentation

Vollständige Setup-, Konfigurations- und Betriebsdoku — alle Umgebungsvariablen, Google-Cloud-Auth
und die Fallstricke im Detail: **[AGENTS.md](./AGENTS.md)**.

## Version

1.0.0

## Lizenz

[MIT](./LICENSE) © Herbert Walde
