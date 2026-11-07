# bambu-mcp

A local MCP server so Claude can check and run a Bambu Lab printer (built for a P2S + AMS 2 Pro).

It talks only to the printer on your home network (MQTT on 8883, FTPS on 990) and runs over stdio, so it opens no network port of its own.

## Tools

| Tool | What it does | Moves the printer? |
| --- | --- | --- |
| `get_status` | State, progress, time left, temps | No |
| `get_ams_spools` | Material, color, remaining %, RFID, AMS humidity per slot | No |
| `slice_model` | Slices an STL/STEP/3MF with Bambu's stock P2S presets (shape only) | No |
| `prepare_print` | Checks and uploads a file `slice_model` made, returns time/filament summary | No |
| `start_print` | Pops up a confirm prompt for you (type a 4 letter code), then starts | Yes |
| `pause_print` / `stop_print` | Pause or cancel (always allowed) | Stops it |
| `resume_print` | Resume a paused job | Yes |

## Safety rules

- **LAN only.** Never port-forward 8883/990 or expose this server to the internet.
- **Access code stays local** in `.env` (git-ignored). Don't paste it in chats or screenshots.
- **No raw G-code or temperature tools** on purpose.
- **Only you can start a print.** `start_print` asks you in a client prompt (MCP elicitation) and you type a short code shown only there. Claude never sees the code. A client that can't show prompts can't start prints.
- **Only files this server sliced** (inside `BAMBU_WORK_DIR`, unchanged since slicing) can be printed. Plate and AMS mapping are checked against the file and the loaded spools.
- **Trusted slicing settings only.** `slice_model` copies the model once into a private folder and keeps only its shape (a 3MF is rebuilt without any of its settings). It then slices with Bambu's own P2S system presets from your Bambu Studio install. Settings, custom G-code and scripts stored in a file are never used. Filaments are PLA or PETG only.
- **Read-only mode:** set `BAMBU_READ_ONLY=true` to allow only status, AMS, pause and stop.
- **Cert pinning:** on first connect, the printer's TLS certs for both ports are saved together (`printer_cert_pins.json` in the work folder). If either one changes, the server refuses to send the access code. Delete that file if you replace the printer.

## Setup (Windows)

1. On the printer: turn on **LAN Only Mode** and **Developer Mode**, then note the IP, serial and access code.
2. Install:
   ```
   git clone https://github.com/lelemilee/bambu-mcp
   cd bambu-mcp
   py -m venv .venv
   .venv\Scripts\pip install -e .
   copy .env.example .env
   ```
   Fill in `.env`.
3. Add to Claude Desktop's `claude_desktop_config.json`:
   ```json
   {
     "mcpServers": {
       "bambu": {
         "command": "C:\\path\\to\\bambu-mcp\\.venv\\Scripts\\bambu-mcp.exe",
         "env": { "BAMBU_ENV_FILE": "C:\\path\\to\\bambu-mcp\\.env" }
       }
     }
   }
   ```
4. Restart Claude Desktop and ask "what spools are in my AMS?"

## Notes

- The MQTT/FTPS protocol isn't officially documented; field names follow [OpenBambuAPI](https://github.com/Doridian/OpenBambuAPI). The P2S may differ slightly.
- `remaining_percent` is only known for Bambu RFID spools; others show `null`.
- Default presets: `Bambu Lab P2S 0.4 nozzle`, `0.20mm Standard @BBL P2S`, `Bambu PLA Basic @BBL P2S`, `Bambu PETG HF @BBL P2S`. If your Bambu Studio names them differently, the error lists close matches; set `BAMBU_MACHINE_PRESET`, `BAMBU_PROCESS_PRESET`, `BAMBU_FILAMENT_PRESET_PLA` or `BAMBU_FILAMENT_PRESET_PETG`.
- A 3MF loses its colors, plate layout and per-object settings (objects get auto-arranged). Multi-color by file isn't supported yet.

## Dev

```
pip install -e ".[dev]"
pytest
```

To smoke test against your real Bambu Studio (slices a 10 mm cube with the P2S presets):

```
set BAMBU_SMOKE_STUDIO=C:\Program Files\Bambu Studio\bambu-studio.exe
pytest -k smoke
```
