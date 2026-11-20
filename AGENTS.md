# Imagen Tools MCP — Setup & Konfiguration

> Diese Datei ist die **einzige Quelle** der Projekt-Doku. `CLAUDE.md` importiert sie per
> `@AGENTS.md`, damit Claude Code sie automatisch mitlädt — nicht duplizieren, hier pflegen.

MCP-Server (Python) für Bildgenerierung und -bearbeitung mit Google Gemini.
Läuft auf **Windows, macOS und Linux**.

Unterstützt **zwei Transporte**: `stdio` (Default, eine Instanz je Client) und
`streamable-http` (ein geteilter Prozess für beliebig viele Clients, siehe
[Transporte](#transporte)).

---

## Was der Server braucht

| Baustein | Zweck | Pflicht? |
|---|---|---|
| Python ≥ 3.10 | Laufzeit | ja |
| `google-genai`, `mcp`, `Pillow` | siehe `requirements.txt` | ja |
| Google-Cloud-Projekt mit aktivierter Vertex AI API | Provider `vertex_ai` | ja, für Vertex |
| `gcloud` CLI + Application Default Credentials | Auth für `vertex_ai` | ja, für Vertex |
| Gemini-API-Key (AI Studio) | Provider `ai_studio` | nur für AI Studio |

Der Server unterstützt **zwei Provider**, zwischen denen zur Laufzeit gewechselt werden kann:

- **`vertex_ai`** (Default) — authentifiziert über `gcloud`, zuverlässig für alle Operationen.
- **`ai_studio`** — authentifiziert über API-Key, aber **Bild-Editing mit dem Flash-Modell
  schlägt hier reproduzierbar mit 500 Internal Error fehl**. Für Editing über AI Studio das
  Pro-Modell wählen oder auf `vertex_ai` wechseln.

---

## Installation

```bash
pip install -r requirements.txt
```

Ein venv ist optional — wo systemweites pip erlaubt ist, genügt der Aufruf oben.

---

## Konfiguration über Umgebungsvariablen

Projekt-ID und API-Key kommen ausschließlich aus der Umgebung — **keine Zugangsdaten im Code**.
Gesetzt werden sie am besten direkt im `env`-Block des MCP-Eintrags (siehe unten), dann gelten sie
nur für diesen Server und überleben Shell-Neustarts.

Nicht über die Umgebung steuerbar, sondern im Code festgelegt: Start-Provider und -Modell
(`DEFAULT_PROVIDER`, `DEFAULT_MODEL` — zur Laufzeit über die `switch_*`-Tools änderbar), das
90-s-Timeout pro API-Call und `MAX_INPUT_EDGE` (1568 px).

| Variable | Bedeutung | Default |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | GCP-Projekt-ID. **Ohne diese Variable startet der Server nicht** (bei Provider `vertex_ai`). | — |
| `GEMINI_API_KEY_NANO_BANANA` | API-Key für Provider `ai_studio`. | leer |
| `IMAGEN_MCP_DEBUG` | `0` schaltet das Debug-Log ab. | `1` (an) |
| `IMAGEN_MCP_LOG_FILE` | Voller Pfad zur Log-Datei. | siehe unten |
| `IMAGEN_MCP_TRANSPORT` | `stdio` oder `streamable-http`. | `stdio` |
| `IMAGEN_MCP_HOST` | Bind-Adresse im HTTP-Modus. **Nie `0.0.0.0`** — der Server hat keine Authentifizierung. | `127.0.0.1` |
| `IMAGEN_MCP_PORT` | Port im HTTP-Modus. | `8901` |

Zusätzlich liest der Server beim Start eine **`.env` neben dem Skript**, aber nur als *Fallback*:
bereits gesetzte Umgebungsvariablen werden nie überschrieben. Damit gelten im stdio-Betrieb
weiterhin die Werte aus dem `env`-Block der `.claude.json`, während der launchd-Betrieb (wo kein
MCP-Client Variablen mitgibt) seine Zugangsdaten aus der `.env` bezieht — so müssen **keine
Secrets in die LaunchAgent-Plist**. Die `.env` ist gitignored und sollte Modus `600` haben.

`GOOGLE_GENAI_USE_VERTEXAI` und `GOOGLE_CLOUD_LOCATION` setzt der Server selbst — nicht von Hand
setzen.

### Log-Datei

Ohne `IMAGEN_MCP_LOG_FILE` landet das Log plattformüblich:

- **Windows:** `%LOCALAPPDATA%\imagen-tools-mcp\imagen_tools_debug.log`
- **macOS/Linux:** `~/.local/state/imagen-tools-mcp/imagen_tools_debug.log`

Das Verzeichnis wird beim Start automatisch angelegt. Ist es nicht beschreibbar, loggt der Server
nach stderr statt abzustürzen.

---

## Google-Cloud-Auth einrichten (für `vertex_ai`)

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project DEINE-PROJEKT-ID
```

Das Token läuft periodisch ab. Der Server erkennt das und antwortet dann mit einer Meldung, die
mit dem Marker **`AUTH_EXPIRED`** beginnt — Konsumenten wie *Nano Studio* werten diesen Marker
aus, um ein „Token erneuern"-Modal zu zeigen. Behoben wird es durch erneutes
`gcloud auth application-default login`.

---

## Eintrag in die MCP-Konfiguration

In `~/.claude.json` (bzw. per `claude mcp add`):

```json
{
  "mcpServers": {
    "imagen-tools": {
      "type": "stdio",
      "command": "python3",
      "args": ["/absoluter/pfad/zu/imagen_tools_mcp.py"],
      "env": {
        "GOOGLE_CLOUD_PROJECT": "deine-projekt-id",
        "GEMINI_API_KEY_NANO_BANANA": "dein-api-key"
      }
    }
  }
}
```

Unter **Windows** `"command": "python"` und einen Windows-Pfad verwenden
(`"C:/Users/name/mcp-servers/imagen-tools-mcp/imagen_tools_mcp.py"` — Forward-Slashes
funktionieren auch dort).

### Variante für den geteilten HTTP-Prozess

Setzt voraus, dass der Server läuft (launchd, siehe [Transporte](#transporte)). Der Client startet
dann keinen eigenen Prozess mehr, und es braucht hier **keinen `env`-Block** — die Zugangsdaten
kommen aus der `.env` des Servers:

```json
{
  "mcpServers": {
    "imagen-tools": {
      "type": "http",
      "url": "http://127.0.0.1:8901/mcp"
    }
  }
}
```

---

## Transporte

### stdio (Default)

Jeder MCP-Client startet seine eigene Instanz. Einfach, aber **jede Instanz belegt ~128 MB** —
bei vielen parallelen Claude-Code-Sitzungen summiert sich das auf mehrere Gigabyte.

### streamable-http (geteilter Prozess)

Ein einziger Prozess bedient alle Sitzungen über `http://127.0.0.1:8901/mcp`:

```bash
python3 imagen_tools_mcp.py --transport streamable-http
```

Der Transport ist auch über `IMAGEN_MCP_TRANSPORT` wählbar; stdio bleibt jederzeit als Rückfall
verfügbar.

**Zustand ist pro MCP-Session getrennt.** `switch_provider` und `switch_model` verändern
veränderlichen Zustand. Läge der global im Prozess, würde ein Modellwechsel in Sitzung A das
Verhalten von Sitzung B still mitverändern — ein stiller Korrektheitsfehler. Darum hängt
`{provider, model}` an der `ServerSession` (siehe `_current_state()`, `WeakKeyDictionary`), und
jede neue Session startet auf den Defaults. Die genai-Clients selbst sind davon ausgenommen: sie
sind nach der Konstruktion unveränderlich und werden je Provider einmal erzeugt und geteilt
(max. zwei Instanzen).

Aus demselben Grund setzt `_create_client()` **nicht** mehr `GOOGLE_GENAI_USE_VERTEXAI` /
`GOOGLE_CLOUD_LOCATION` im Prozess-Environment, sondern übergibt `vertexai`, `project` und
`location` explizit an `genai.Client(...)`. Prozessweite env-Mutationen wären in einem geteilten
Prozess ein Nebeneffekt über Session-Grenzen hinweg.

Weiterer Unterschied im HTTP-Modus: Ein fehlgeschlagener Start-Warmup (z. B. abgelaufenes
ADC-Token) bricht den Start **nicht** ab, weil der Prozess unter launchd mit `KeepAlive` sonst in
eine Neustart-Schleife liefe. Stattdessen antworten die Tools mit der `AUTH_EXPIRED`-Meldung.

### Dauerbetrieb über launchd (macOS)

Plist: `~/Library/LaunchAgents/de.herbe.mcp.imagen-tools.plist`
(`RunAtLoad`, `KeepAlive`, `ThrottleInterval 10`, Logs unter `~/Library/Logs/`).

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/de.herbe.mcp.imagen-tools.plist
launchctl list | grep imagen-tools     # läuft?
lsof -i :8901 -sTCP:LISTEN             # lauscht?
launchctl bootout gui/$(id -u)/de.herbe.mcp.imagen-tools   # stoppen
```

Endpunkt prüfen:

```bash
curl -i -X POST http://127.0.0.1:8901/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

---

## Tools

| Tool | Zweck |
|---|---|
| `create_image_using_gemini` | Bild erzeugen. Parameter: `prompt` (Pflicht), `aspect_ratio` (Default `16:9`), `image_size` (`1K`/`2K`/`4K`, Default `2K`). |
| `edit_image_using_gemini` | Bestehendes Bild bearbeiten. Parameter: `image_path`, `prompt`, `image_size`. |
| `switch_provider` | Wechselt zwischen `vertex_ai` und `ai_studio`. Ohne Argument: aktuelle Konfiguration. |
| `switch_model` | Wechselt zwischen `gemini-3.1-flash-image` und `gemini-3-pro-image`. |
| `get_config` | Zeigt aktuellen Provider und Modell. |

Erzeugte Bilder werden in eine temporäre Datei geschrieben; der Tool-Output ist der Pfad dorthin.

### Modelle

- `gemini-3.1-flash-image` (Default) — schnell.
- `gemini-3-pro-image` — höhere Qualität, Editing funktioniert auf allen Providern.

---

## Bekannte Fallstricke

- **Prompts sollten mit „Generate" oder „Create" beginnen.** Beschreibende Fließtexte ohne
  Handlungsverb liefern deutlich schlechtere Ergebnisse.
- **Timeout liegt bei 90 s pro API-Call.** Eingabebilder werden vor dem Editieren automatisch auf
  1568 px längste Kante verkleinert (`MAX_INPUT_EDGE`) — ein ungekürztes Mehr-MB-Kamerafoto trieb
  den Edit-Call sonst über das Timeout. EXIF-Rotation wird dabei mit angewendet.
- **Flash + AI Studio + Editing = 500er.** Der Server erkennt diese Kombination und gibt einen
  Hinweis auf `switch_provider`/`switch_model` zurück, statt den Fehler durchzureichen.
- **Rate Limits (429)** beantwortet der Server mit dem Tipp, per `switch_provider` auf den anderen
  Provider auszuweichen.
- **`GOOGLE_CLOUD_PROJECT` fehlt → Start bricht ab.** Der Server prüft das beim Client-Aufbau und
  wirft einen `ValueError`.

---

## Konsumenten

Neben Coding-Agenten nutzt ein Tauri-Desktop-Client (*Nano Studio*, nicht öffentlich) diesen
Server. Der `AUTH_EXPIRED`-Marker am Anfang der Fehlermeldung ist Teil des Vertrags mit dieser App
— sie zeigt daraufhin ein „Token erneuern"-Modal statt eines generischen Toasts. Beim Umformulieren
von Fehlermeldungen darf der Marker daher nicht verschwinden.
