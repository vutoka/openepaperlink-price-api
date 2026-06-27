# Device Session Notes

## 2026-06-14

- Connected target identified as ESP32-C6 (QFN40), revision 0.2.
- Base MAC: `58:8c:81:26:6a:1c`.
- Physical flash size: 8 MB (manufacturer `c8`, device `4017`).
- `COM14`: CH343 UART bridge connected to the ESP32-C6.
- `COM15`: native Espressif USB serial/JTAG interface for the same ESP32-C6.
- ESP32-S3 was not initially exposed as a separate serial device, but was
  later found on the local network.

Installed C6 firmware:

- Project: `OpenEPaperLink_esp32_C6`
- Version: `2.75-12-gbb361850`
- Compile time: `Dec 17 2024 07:24:41`
- ESP-IDF: `v5.4-dev-1030-g0479494e7a`
- Image flash configuration: 4 MB, 80 MHz, DIO

Partition table:

- `nvs`: offset `0x9000`, size 24 KB
- `factory`: offset `0x10000`, size 1 MB
- `littlefs`: offset `0x110000`, size 3008 KB

Read-only backup:

- File: `device_backups/2026-06-14/esp32-c6_58-8c-81-26-6a-1c_8mb.bin`
- Size: 8,388,608 bytes
- SHA-256: `620A9FB4ECB6F45E90F4CD531432F16061018D29B4F781B53FAA86B8026B2BEF`
- Nothing was erased or flashed during inspection.

### Working AP setup

- ESP32-S3 environment: `ESP32_S3_SIMPLE_AP`.
- S3 flash: 16 MB; PSRAM: 8 MB.
- OpenEPaperLink web interface: `http://192.168.0.24/`.
  This is a DHCP address and may change after a router or AP restart.
- The S3 detects the C6 radio (`hasC6: 1`).
- The S3 initially showed AP state `failed`.
- Moving the S3 USB cable from its native `USB` connector to its `COM`
  connector fixed initialization. Use the S3 `COM` connector for this setup.
- After moving the cable, AP state changed to `online`.
- No firmware was changed to fix this; only the S3 USB connection was moved.
- If only the S3 is unplugged or reset, the C6 can remain at the negotiated
  2 Mbaud UART speed while the restarted S3 begins at 115200 baud. This makes
  the AP return to `failed`.
- Confirmed recovery: reset the C6 after restarting the S3. The AP changes
  from `failed` to `online` within several seconds.
- Reliable restart procedure: reset/power-cycle both boards together, or
  restart S3 first and then reset C6.

### Detected tag

- Model printed on case: `ST-GR2900N`.
- The tag was already flashed with OpenEPaperLink firmware, as confirmed by
  the maintainer and by the tag displaying `Waiting for data`.
- Tag MAC: `00000181500F3B39`.
- OpenEPaperLink hardware type: `17`.
- Firmware version reported by tag: `39`.
- Battery: 3000 mV.
- Last observed signal: RSSI `-29`, LQI `81`.
- Tag reported channel `11`.
- The tag appeared in the web interface once the AP became `online`.

### Current state and next step

- S3/C6 AP is working and the first tag is registered.
- A local REST price service was added at `tools/price_api.py`.
- API documentation is in `PRICE_API.md`.
- Endpoints: `GET /health`, `GET /tags`, and `POST /price`.
- A test request sent `TEST PROIZVOD`, `199.99 RSD`, and `API test`.
- The AP accepted the request, generated the image, and the tag completed the
  transfer. Its update counter increased from 4 to 5.
- A direct S3 API was then added to the `ESP32_S3_SIMPLE_AP` firmware:
  `GET /health` and `POST /price` on TCP port 8080.
- The S3 API uses a bearer token stored separately in
  `/current/api_token.txt`; the token is not returned by AP config endpoints.
- Port 8080 intentionally exposes only the price API. Port 80 must remain
  private because it contains unauthenticated administration and OTA routes.
- Build verification succeeded:
  `pio run -d ESP32_AP-Flasher -e ESP32_S3_SIMPLE_AP`.
- The S3 `COM` connector is exposed as `COM16`.
- Before flashing, critical S3 regions were backed up under
  `device_backups/2026-06-14/s3-critical/`:
  - `bootloader-region.bin` (36,864 bytes), SHA-256
    `D7C22366B3667BF46DFEE96CCD62C1A67E07F30422F148C216BE316FF9A0D1F5`
  - `nvs.bin` (20,480 bytes), SHA-256
    `9B9159887DBC71F7F8D2FB5F6F0388199E38A3A003D08287002488A3DE5118AC`
  - `otadata.bin` (8,192 bytes), SHA-256
    `F94C5D786A7A8FAB06AC5D10E33BF37711A6697636DC037559EA19CC410A17F0`
- Full 16 MB backups were attempted at 921600 and 460800 baud, but the
  CH343 serial link intermittently returned short/corrupt blocks. The
  critical backups at 115200 baud completed successfully.
- The direct S3 API firmware was installed successfully over `COM16`.
  Esptool verified the bootloader, partition table, OTA data, and application
  writes. NVS and SPIFFS were not erased.
- A 32-byte random bearer token was configured on the S3. The actual token is
  intentionally not stored in this repository.
- Authentication was verified: unauthenticated `/health` returns HTTP 401,
  while an authenticated request returns HTTP 200.
- Immediately after flashing, the S3 reported `apstate: 5`; reset the C6 once
  to restore the UART/AP link before testing `POST /price`.
- After the C6 reset, authenticated `/health` returned `apstate: 1` and
  `POST /price` returned HTTP 202 for tag `00000181500F3B39`.
- The direct S3 API test sent `TEST PROIZVOD`, `199.99 RSD`, and
  `S3 API test`. The tag completed the transfer (`pending: 0`), its update
  counter increased from 5 to 6, and its image hash changed to
  `6729c81d4966f3320000000000000000`.
- A Cloudflare Quick Tunnel is running on the Windows computer and forwards
  only to `http://192.168.0.24:8080`.
- Current temporary public URL:
  `https://quad-decimal-backing-mailto.trycloudflare.com`
- The tunnel was verified externally: `/health` returns HTTP 401 without a
  bearer token and HTTP 200 with the configured token.
- The Quick Tunnel URL is temporary, has no uptime guarantee, and stops when
  the `cloudflared` process or computer stops. The production Raspberry Pi
  setup should use a named Cloudflare Tunnel and a permanent hostname.

### Active temporary tunnel

- As of the end of this session, `cloudflared.exe` is running on the Windows
  computer as process ID `24096`.
- Public base URL:
  `https://quad-decimal-backing-mailto.trycloudflare.com`
- Postman endpoint:
  `POST https://quad-decimal-backing-mailto.trycloudflare.com/price`
- Postman authorization type: Bearer Token.
- Postman body type: raw JSON (`Content-Type: application/json`).
- Example body:

```json
{
  "mac": "00000181500F3B39",
  "product": "MLEKO 1L",
  "price": "149.99",
  "currency": "RSD",
  "note": "Akcija"
}
```

- Do not store the current token in this repository. Rotate it before
  production because it was used during interactive testing.
- The current compiled S3 firmware SHA-256 is
  `7F99B51341FC06BE839EAB7CC54DDB36ED8A310365802C69408CD1E55AF0875E`.

### What to obtain for the Raspberry Pi setup

Required:

- Raspberry Pi Zero 2 W, Raspberry Pi 3, Raspberry Pi 4, or newer.
  A Pi Zero 2 W is sufficient for this single Cloudflare Tunnel.
- Compatible stable power supply. For a Pi Zero 2 W, use a good regulated
  5 V / 2.5 A supply and the correct micro-USB power cable.
- MicroSD card, at least 16 GB, preferably a reliable 32 GB card.
- A microSD card reader for installing Raspberry Pi OS.
- Wi-Fi access to the same local network as the S3.

Recommended:

- Raspberry Pi case.
- Ethernet connection for better reliability. A Pi Zero 2 W requires a
  micro-USB OTG Ethernet adapter; Pi 3/4/5 models have built-in Ethernet.
- Router access so a DHCP reservation can be created for the S3.
- A Cloudflare account.
- A domain managed by Cloudflare for a stable hostname such as
  `prices.example.com`. The temporary `trycloudflare.com` URL does not require
  a domain, but it is not suitable for a permanent service.

Not required:

- No monitor, keyboard, or mouse is needed after Raspberry Pi OS is prepared.
- No router port forwarding is needed when using Cloudflare Tunnel.
- The S3 and C6 do not need to be connected by USB to the Raspberry Pi. They
  only need power and network access; the Pi reaches the S3 over LAN/Wi-Fi.

### Raspberry Pi plan for the next session

1. Install 64-bit Raspberry Pi OS Lite and enable SSH during imaging.
2. Connect the Pi to the same network as the S3 and install `cloudflared`.
3. Reserve the S3 address in the router using its Wi-Fi MAC, or otherwise
   ensure that `192.168.0.24` does not change.
4. Confirm from the Pi that
   `http://192.168.0.24:8080/health` is reachable with the bearer token.
5. Create a named Cloudflare Tunnel in the Cloudflare dashboard.
6. Configure only the chosen public hostname to forward to
   `http://192.168.0.24:8080`.
7. Install the tunnel as a `systemd` service so it starts automatically after
   reboot and restarts after a failure.
8. Rotate the S3 API bearer token, store it in the calling application or
   Postman environment, and do not write it into source control.
9. Verify public `GET /health` and `POST /price`, then stop the Windows Quick
   Tunnel.

Security boundary:

- Expose only S3 port `8080` through Cloudflare.
- Never expose S3 port `80`; it contains the administration and OTA interface.
- Cloudflare provides HTTPS between the external client and Cloudflare, and
  the Pi forwards HTTP only inside the trusted local network to the S3.
