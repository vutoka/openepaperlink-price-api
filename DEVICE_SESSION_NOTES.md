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

## 2026-07-08 / 2026-07-09

### Raspberry Pi setup

- Raspberry Pi 3B was prepared with Raspberry Pi OS Lite.
- Hostname: `price-pi`.
- User: `trivan`.
- SSH key-based login from the Windows laptop was configured.
- Windows private key path:
  `C:\Users\Vuk Djokic\.ssh\price-pi_ed25519`.
- Initial phone hotspot network:
  - Phone/gateway: `192.168.31.10`
  - Windows laptop: `192.168.31.66`
  - Raspberry Pi: `192.168.31.93`
- The Pi was updated with `apt update` and `apt full-upgrade`, then rebooted
  successfully.

### Raspberry price proxy

- A Raspberry-local proxy was added in the repository:
  - `tools/raspberry_price_proxy.py`
  - `tools/price-proxy.service`
  - `tools/price-proxy.env.example`
- The proxy uses only the Python standard library.
- Local mock tests passed:
  - bad public token returns `401`;
  - `GET /health` forwards to the ESP API;
  - `POST /price` forwards and preserves the ESP `202` response.
- Files were installed on the Pi:
  - `/opt/price-proxy/app.py`
  - `/etc/price-proxy.env`
  - `/etc/systemd/system/price-proxy.service`
- `/etc/price-proxy.env` is root-only (`0600`) and must not be committed.
- The `price-proxy` systemd service was left `disabled` and `inactive` until
  live validation is completed.

### ESP Wi-Fi recovery and current IP

- The ESP32-S3 had old Wi-Fi credentials for an unavailable network.
- The expected fallback SSID is `OpenEPaperLink`, with no password, and setup
  URL `http://192.168.4.1/setup`.
- On this `ESP32_S3_SIMPLE_AP` build, holding `BOOT/GPIO0` did not expose the
  fallback network. This is consistent with the build using
  `ARDUINO_USB_CDC_ON_BOOT` but not `HAS_USB`; the GPIO0 reset path in
  `wifimanager.cpp` is behind `#ifndef HAS_USB` and did not help in this
  hardware session.
- The working recovery path was Improv serial provisioning over the S3 USB/COM
  connector.
- Confirmed S3 serial port: `COM16`.
- The ESP was provisioned to the current hotspot/store Wi-Fi through the Improv
  serial protocol. Do not commit the Wi-Fi SSID/password.
- After provisioning, the ESP appeared on the hotspot as:
  - ESP32-S3 API/admin IP: `192.168.31.203`
  - MAC observed from Raspberry neighbor table: `ac:a7:04:26:a2:ac`
- From Raspberry, `http://192.168.31.203/` returned HTTP `200`.
- From Raspberry, unauthenticated
  `http://192.168.31.203:8080/health` returned:

```json
{"ok":false,"error":"unauthorized"}
```

This confirms the ESP price API is reachable and requires a bearer token.

### Tokens and stopping point

- New random tokens were generated locally during the session:
  - one ESP API token for Raspberry -> ESP;
  - one public API token for home server -> Raspberry.
- The ESP token was submitted to the ESP admin endpoint
  `POST /save_apcfg` as form field `apitoken`.
- `/etc/price-proxy.env` on the Pi was updated with:
  - `ESP_BASE_URL=http://192.168.31.203:8080`
  - generated `PUBLIC_API_TOKEN`
  - generated `ESP_API_TOKEN`
- The actual token values are intentionally not stored in this repository.
- The session stopped before completing the final live proxy health check and
  before enabling/starting `price-proxy`.

Next steps:

1. Test the ESP API from the Pi using the protected env file.
2. Start and enable `price-proxy`.
3. Test `http://127.0.0.1:8000/health` on the Pi.
4. Test `POST /price` through the Pi proxy.
5. Configure named Cloudflare Tunnel to point to `http://localhost:8000`.

## 2026-07-31

### Full stack power-on and end-to-end verification

- All three components (ESP32-S3/C6, Raspberry Pi, and the Windows laptop used
  for testing) were power-cycled independently on the phone hotspot network
  (`192.168.31.0/24`) and verified end to end.
- `price-proxy.service` and `cloudflared-quicktunnel.service` were confirmed
  `active`/`enabled` and started automatically without manual intervention.
- The Cloudflare Quick Tunnel hostname is random per service start; the
  current URL was read from
  `sudo journalctl -u cloudflared-quicktunnel | grep -o 'https://[a-zA-Z0-9.-]*trycloudflare.com' | tail -1`
  as documented in `PRICE_API.md`.
- A real authenticated `POST /price` was sent through the public tunnel URL
  and reached the tag successfully (`esp_status: 202`).

### Troubleshooting: Pi could not reach the ESP over Wi-Fi

- After power-on, the ESP API was reachable directly from the Windows laptop
  (`192.168.31.203`, HTTP `200`/`401` as expected), but the Raspberry Pi could
  not reach the same address: `ping` returned `Destination Host Unreachable`
  and `ip neigh show 192.168.31.203` showed state `FAILED`, even after
  `ip neigh flush`.
- This was an ARP/Layer-2 resolution problem between those two specific
  Wi-Fi clients on the phone hotspot, not a code, config, token, DNS, or
  Cloudflare Tunnel problem — the proxy, tunnel, and bearer token were all
  independently confirmed correct while this was happening (the proxy's own
  error was `"cannot reach ESP API: [Errno 113] No route to host"`).
- The same Pi-to-ESP path had worked earlier in a previous session over the
  same hotspot (see 2026-07-08/09 above), so this looked like a transient
  hotspot ARP-table glitch rather than a fixed client-isolation policy.
- Toggling airplane mode on the hotspot phone briefly to try to force an ARP
  refresh made things worse: the hotspot dropped for a few seconds, and the
  ESP32-S3 fell back to its own standalone AP (`OpenEPaperLink`, no password,
  setup page at `http://192.168.4.1/setup` — see the 2026-07-08/09 note above)
  instead of automatically rejoining the hotspot. The Windows laptop and the
  Pi both silently rejoined the hotspot on their own.
- Power-cycling the ESP32-S3 (not just the hotspot) fixed both problems at
  once: it rejoined the hotspot cleanly on the same address (`192.168.31.203`)
  and the Pi could then reach it immediately (confirmed via `curl`, and the
  proxy's `/health` and `/price` forwarding both worked afterward).

### Takeaway for next time

- If the Pi-to-ESP hop fails with `No route to host` right after powering
  everything on, the fastest fix observed was a plain power-cycle of the
  ESP32-S3 board, not the hotspot/router. Restarting the hotspot risks
  knocking the ESP into its fallback AP mode, which requires re-provisioning
  Wi-Fi credentials via `http://192.168.4.1/setup` (or Improv serial) to
  recover.
- This class of intermittent Wi-Fi/ARP issue between Pi and ESP is a known
  weakness of the phone-hotspot setup and is the main reason the production
  plan recommends Ethernet for the Raspberry Pi (see `AI_CONTEXT.md`).
