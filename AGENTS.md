# Imagen Tools MCP — Setup & Konfiguration

> Diese Datei ist die **einzige Quelle** der Projekt-Doku. `CLAUDE.md` importiert sie per
> `@AGENTS.md` — nicht duplizieren, hier pflegen.

MCP-Server (Python) für Bildgenerierung und -bearbeitung mit **`microsoft/mai-image-2.7`** über die
**OpenRouter Image API** (`POST https://openrouter.ai/api/v1/images`). Genau **zwei Tools**.
Bis v0.6 lief der Server über Google Gemini (Vertex/AI Studio). Das ist mit v1.0 komplett entfernt.

## Tools

| Tool | Parameter |
|---|---|
| `create_image` | `prompt` (Pflicht), `aspect_ratio` (Default `16:9`), `background` (`opaque`/`transparent`), `output_path` |
| `edit_image` | `image_path`, `prompt` (Pflicht), `reference_image_paths` (max. 4 weitere), `aspect_ratio`, `background`, `output_path` |

- Erlaubte `aspect_ratio`: `1:1 4:3 3:4 16:9 9:16 3:2 2:3 auto` (Modell-Limit, per Discovery-Endpoint
  `https://openrouter.ai/api/v1/images/models/microsoft/mai-image-2.7/endpoints` nachprüfbar).
- Ohne `output_path` landet das Bild in einer temporären Datei. Der Tool-Output enthält den Pfad,
  die Pixelgröße, die Dauer und die Kosten.
- Ergebnisgröße bei 16:9: 1360×768 px. Eine exakte Zielgröße stellt der Aufrufer selbst her.
- Eingabebilder werden vor dem Upload auf 2048 px längste Kante verkleinert, inklusive EXIF-Rotation.
- Ein Bild kostet etwa 0,03–0,05 USD (gemessen 2026-11-20).

## Zugangsdaten

Der Key kommt nur aus **`OPENROUTER_API_KEY`** und wird nie geloggt. Fehlt die Variable in der
Umgebung (typisch im Dienst-Betrieb, denn launchd und systemd lesen keine Shell-Startdateien), liest
der Server die Zeile `[export ]OPENROUTER_API_KEY=…` aus der ersten vorhandenen Datei mit Treffer:
`IMAGEN_MCP_KEY_FILE` (falls gesetzt), dann `~/.zshrc`, dann `~/.bashrc`. So existiert der Key nur an
einer Stelle. Eine `.env` neben dem Skript wird weiterhin als Fallback gelesen (gitignored).

Nach einer Key-Rotation in `~/.zshrc` muss der Dienst neu gestartet werden (siehe unten).

## Weitere Umgebungsvariablen

| Variable | Bedeutung | Default |
|---|---|---|
| `IMAGEN_MCP_DEBUG` | `0` schaltet das Log ab. | `1` |
| `IMAGEN_MCP_LOG_FILE` | Pfad zur Log-Datei. | `~/.local/state/imagen-tools-mcp/imagen_tools_debug.log` (Windows: `%LOCALAPPDATA%\…`) |
| `IMAGEN_MCP_TRANSPORT` | `stdio` oder `streamable-http`. | `stdio` |
| `IMAGEN_MCP_HOST` | Bind-Adresse im HTTP-Modus. **Nie `0.0.0.0`**, denn der Server hat keine Authentifizierung. | `127.0.0.1` |
| `IMAGEN_MCP_PORT` | Port im HTTP-Modus. | `8901` |

## Installation

```bash
pip install -r requirements.txt   # mcp, Pillow, httpx
```

## Betrieb auf diesem Mac: geteilter HTTP-Prozess über launchd

`~/.claude.json`:

```json
"imagen-tools": { "type": "http", "url": "http://127.0.0.1:8901/mcp" }
```

Plist: `~/Library/LaunchAgents/de.herbe.mcp.imagen-tools.plist` (`KeepAlive`, Logs unter `~/Library/Logs/`).

```bash
launchctl kickstart -k gui/$(id -u)/de.herbe.mcp.imagen-tools   # nach Code-Änderung neu starten
lsof -i :8901 -sTCP:LISTEN                                       # läuft er?
```

Laufende Claude-Code-Sitzungen sehen geänderte Tools erst nach `/mcp` → Reconnect oder einem Neustart.

Der HTTP-Endpunkt bedient `/mcp` und `/mcp/` direkt, ohne Starlette-Mount. Ein Mount würde auf POST mit
307 antworten, und manche Clients folgen dem nicht.

## Betrieb auf hetzner-prod: systemd-User-Dienst

Unit: `~/.config/systemd/user/imagen-tools-mcp.service` (Port 8901, eigene `.venv`). Sie startet den Server
mit `--transport streamable-http` und setzt `IMAGEN_MCP_KEY_FILE=%h/.config/video-pipeline/secrets.env`,
denn dort liegt der gültige Key, der den älteren aus `~/.bashrc` überschreibt. Aktualisieren:

```bash
ssh hetzner-prod 'cd ~/.mcp-servers/imagen-tools-mcp && git pull --ff-only && \
  XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user restart imagen-tools-mcp'
```

Die Video-Pipeline (`video-produktion`, `10-thumbnail/bildgen.py`) nutzt den Server nur im optionalen
Weg `--gemini-weg mcp`, der noch die alten Gemini-Tools aufruft. Der Standardweg geht direkt an die APIs.

Als stdio-Alternative: `{"type":"stdio","command":"python3","args":["/pfad/imagen_tools_mcp.py"]}`.

## Bekannte Fallstricke

- **Nano Studio** (Tauri-App, `~/IdeaProjects/nano-studio`) ruft noch die alten Tools
  `create_image_using_gemini`, `edit_image_using_gemini`, `switch_provider` und `switch_model` auf. Es
  erwartet außerdem einen stdio-Eintrag mit Gemini-Env in `.claude.json`. Mit v1.0 ist es inkompatibel
  und muss bei Bedarf angepasst werden.
- HTTP 402 bedeutet zu wenig OpenRouter-Guthaben, 403 die Moderation. Die Meldungen nennen jeweils den
  nächsten Schritt.
- Bei Timeout (300 s) gibt es bewusst keinen automatischen Neuversuch, weil die Generierung schon
  berechnet sein könnte. Bei 5xx gibt es einen Neuversuch, denn Fehlschläge werden nicht berechnet.
