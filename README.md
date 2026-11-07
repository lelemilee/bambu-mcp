# bambu-mcp

A local MCP server so Claude can check and run a Bambu Lab printer (built for a P2S + AMS 2 Pro).

It talks only to the printer on your home network (MQTT on 8883, FTPS on 990) and runs over stdio, so it opens no network port of its own.

## Tools

| Tool | What it does | Moves the printer? |
| --- | --- | --- |
| `get_status` | State, progress, time left, temps | No |
| `get_ams_spools` | Material, color, remaining %, RFID, AMS humidity per slot | No |
| `slice_model` | Slices a Bambu Studio 3MF project with the Bambu Studio CLI | No |
| `prepare_print` | Uploads a sliced `.gcode.3mf`, returns a one-time confirm code + summary | No |
| `start_print` | Starts the prepared job, needs the confirm code (single use, 5 min) | Yes |
| `pause_print` / `stop_print` | Pause or cancel (always allowed) | Stops it |
| `resume_print` | Resume a paused job | Yes |

## Safety rules

- **LAN only.** Never port-forward 8883/990 or expose this server to the internet.
- **Access code stays local** in `.env` (git-ignored). Don't paste it in chats or screenshots.
- **No raw G-code or temperature tools** on purpose.
- **Two-step print:** `prepare_print` then `start_print` with the code. Check the camera before you say go.
- **Read-only mode:** set `BAMBU_READ_ONLY=true` to allow only status, AMS, pause and stop.
- The printer's TLS cert is self-signed, so it isn't verified. Another reason to keep this on your own network.

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
- Slicing expects a 3MF project saved from Bambu Studio (it carries the printer, filament and process settings).

## Dev

```
pip install -e ".[dev]"
pytest
```
