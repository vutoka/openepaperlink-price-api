# AI Context

This file is portable context for humans and AI tools working on this
repository. It separates what has already been implemented and verified from
what is only planned for future work.

For the reading order, start with `READ_FIRST.md`.

## Project Goal

Use OpenEPaperLink e-paper tags as price labels that can be updated through an
authenticated HTTP API.

The core design decision is that the ESP32-S3 OpenEPaperLink AP itself owns the
price update API. A future Raspberry Pi is only a network bridge for secure
public access through Cloudflare Tunnel.

## Done So Far

### Hardware discovered and tested

- ESP32-S3 AP board is used with the `ESP32_S3_SIMPLE_AP` environment.
- ESP32-C6 radio board is connected to the S3.
- S3 local IP during testing was `192.168.0.24`.
- S3 appeared on Windows as `COM16`.
- C6 appeared on Windows as `COM14` / `COM15`.
- The S3 must use its `COM` connector for this setup. Using the native `USB`
  connector caused the AP/radio link to fail in testing.
- A test tag was detected and updated:
  - Model: `ST-GR2900N`
  - MAC: `00000181500F3B39`
  - OpenEPaperLink hardware type: `17`
  - Firmware version reported by tag: `39`

### Firmware implemented on the S3

The `ESP32_S3_SIMPLE_AP` firmware was modified to add a direct API on TCP port
`8080`.

Modified areas:

- `ESP32_AP-Flasher/src/web.cpp`
  - Added a separate API server on port `8080`.
  - Added authenticated `GET /health`.
  - Added authenticated `POST /price`.
  - `POST /price` generates the OpenEPaperLink content and queues a tag update.
  - The API server is separate from the normal admin UI on port `80`.

- `ESP32_AP-Flasher/include/tag_db.h`
  - Added API token storage state.

- `ESP32_AP-Flasher/src/tag_db.cpp`
  - Loads and stores the API token separately.

- `ESP32_AP-Flasher/wwwroot/index.html`
  - Added a Price API token field.

- `ESP32_AP-Flasher/wwwroot/main.js`
  - Added frontend handling for token status and configuration.

The token is stored on the S3 in `/current/api_token.txt`. The real token must
not be committed to the repository.

### API implemented and verified

LAN base URL used in testing:

```text
http://192.168.0.24:8080
```

Authentication:

```text
Authorization: Bearer <S3_API_TOKEN>
```

Implemented endpoints:

- `GET /health`
- `POST /price`

Successful authenticated health response:

```json
{
  "ok": true,
  "apstate": 1,
  "api": "price-v1"
}
```

Example price request:

```json
{
  "mac": "00000181500F3B39",
  "product": "MLEKO 1L",
  "price": "149.99",
  "currency": "RSD",
  "note": "Akcija"
}
```

Observed status codes:

- `200`: authenticated health check succeeded.
- `202`: price update accepted.
- `401`: missing or invalid bearer token.
- `409`: AP/radio is not online.
- `429`: rate limit; wait at least one second between price requests.

### Build and flash completed

Build command used:

```powershell
.\.venv\Scripts\pio.exe run -d ESP32_AP-Flasher -e ESP32_S3_SIMPLE_AP
```

Upload command used:

```powershell
.\.venv\Scripts\pio.exe run -d ESP32_AP-Flasher -e ESP32_S3_SIMPLE_AP -t upload --upload-port COM16
```

The S3 upload completed successfully. Esptool verified the written blocks. NVS
and SPIFFS were not erased during the application flash.

Recorded firmware SHA-256:

```text
7F99B51341FC06BE839EAB7CC54DDB36ED8A310365802C69408CD1E55AF0875E
```

### End-to-end tag update verified

After flashing the S3 firmware and resetting the C6, authenticated `/health`
returned `apstate: 1`.

`POST /price` returned HTTP `202` for tag `00000181500F3B39`.

The tag completed the transfer:

- `pending: 0`
- update counter increased from `5` to `6`
- image hash changed to `6729c81d4966f3320000000000000000`

### Temporary Cloudflare Quick Tunnel tested

A Windows-hosted Cloudflare Quick Tunnel was tested successfully.

Temporary public URL from the test session:

```text
https://quad-decimal-backing-mailto.trycloudflare.com
```

This URL is temporary and not production. It stops when the Windows
`cloudflared` process or computer stops.

The temporary tunnel forwarded only to:

```text
http://192.168.0.24:8080
```

It was verified that:

- `/health` without token returns HTTP `401`
- `/health` with token returns HTTP `200`

### Backups created

See `DEVICE_SESSION_NOTES.md` for exact backup paths and SHA-256 hashes.

Summary:

- Full C6 8 MB backup exists.
- S3 critical regions were backed up successfully.
- Full S3 16 MB backup attempts were unreliable because the CH343 serial link
  returned intermittent short/corrupt blocks at higher baud rates.

## Known Operational Notes

Use the S3 `COM` connector, not the native `USB` connector.

If the S3 is reset or unplugged while the C6 remains powered, the S3 can return
at 115200 baud while the C6 remains at the negotiated higher UART speed. The AP
may then show failed/offline state.

Recovery procedure:

1. Reset or power-cycle the S3.
2. Wait several seconds.
3. Reset the C6.
4. Confirm `/health` returns `apstate: 1`.

Port exposure rule:

- Port `8080` is the intended public API surface.
- Port `80` is the local OpenEPaperLink admin/OTA interface and must not be
  exposed publicly.

## Planned Next Work

These items are not done yet.

### Raspberry Pi Cloudflare Tunnel

Planned production architecture:

```text
External client / Postman / business app
        -> HTTPS
Cloudflare Tunnel
        -> Raspberry Pi on local network
        -> HTTP on LAN
ESP32-S3 OpenEPaperLink AP API, port 8080
        -> C6 radio
        -> e-paper tags
```

The Raspberry Pi will not run the price API. It will only run `cloudflared` as
a stable tunnel to the S3 API.

Recommended hardware:

- Raspberry Pi 3 Model B or similar.
- Official or high-quality 5.1 V / 2.5 A power supply.
- 32 GB reliable microSD card.
- Ventilated case.
- Passive heatsinks.
- Ethernet cable.

Setup plan:

1. Install Raspberry Pi OS Lite.
2. Enable SSH.
3. Connect the Pi to the same LAN as the S3, preferably over Ethernet.
4. Reserve the S3 IP address in the router.
5. Install `cloudflared`.
6. Confirm the Pi can call `http://192.168.0.24:8080/health`.
7. Create a named Cloudflare Tunnel.
8. Configure only the public API hostname to forward to
   `http://192.168.0.24:8080`.
9. Install the tunnel as a `systemd` service.
10. Rotate the S3 bearer token before production.
11. Test public `GET /health` and `POST /price`.
12. Stop the temporary Windows Quick Tunnel.

### Production hardening

Planned but not done:

- Rotate the S3 bearer token.
- Move from temporary `trycloudflare.com` URL to a named Cloudflare Tunnel and
  stable hostname.
- Add router DHCP reservation for S3.
- Decide whether to add Tailscale for private admin access.
- Decide whether to add a Pi-side backend only if product catalog, barcode
  mapping, audit logs, retry queues, or multi-store support become necessary.

### Power reliability

Planned but not done:

- For short outages, consider a UPS.
- A Raspberry Pi UPS HAT only keeps the Pi alive.
- For actual API availability during power loss, use an external UPS that
  powers the router, Raspberry Pi, S3, and C6 together.

## What Not To Commit

Before pushing, verify these are not committed:

- Real bearer tokens.
- Wi-Fi passwords.
- Cloudflare credentials.
- `.env` files with secrets.
- `.venv/`.
- `.pio/` build output.
- Cloudflare logs.
- Large binary device backups, unless intentionally shared.

Suggested checks:

```powershell
git status --short
rg -n "token|password|passwd|secret|Authorization|Bearer|ssid|wifi|cloudflare|apiKey|apikey|key"
```

## Related Files

- `READ_FIRST.md`: entry point for humans and AI agents.
- `DEVICE_SESSION_NOTES.md`: detailed session log and exact hardware notes.
- `PRICE_API.md`: API usage and Postman examples.
- `tools/price_api.py`: older optional computer-side proxy, not the preferred
  production path.
