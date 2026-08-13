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

## 2026-08-04

### Standard power-on order

Follow this order every time the full stack is powered on from cold. Doing
S3 and C6 in the wrong order (or together) can leave the C6 radio
desynchronized from the S3 even while the AP reports `apstate: 1` (looks
"online" but no tag actually checks in):

1. Turn on the phone hotspot and wait a few seconds for it to stabilize.
2. Power on the ESP32-S3 first. Wait until its web interface
   (`http://<esp-ip>/`, currently `http://192.168.31.203/`) loads normally.
3. Only then power on/reset the C6. Wait 10-20 seconds.
4. Confirm real radio connectivity, not just `apstate`: check `/get_db` (or
   the web UI) for at least one tag with a recent `lastseen`. `apstate: 1`
   alone does not prove the C6 link is healthy — it only reflects the
   S3-C6 UART handshake.
5. Power on the Raspberry Pi last, so `price-proxy` succeeds on its first
   attempt instead of retrying while the ESP is still booting.
6. Read the new Quick Tunnel URL from the Pi:
   `sudo journalctl -u cloudflared-quicktunnel --no-pager | grep -o 'https://[a-zA-Z0-9.-]*trycloudflare.com' | tail -1`

Tag check-in after a cold C6 restart can take several minutes (tags only
wake on their own schedule), not seconds — do not assume failure too early.

### Root cause found for a stuck "disconnected" tag icon

On this date, all 6 known tags had not checked in for ~15.5 hours (frozen
`lastseen` across all of them, not just one), while `apstate` reported `1`
the entire time. `nightlyreboot: 1` is enabled in the AP config (reboots at
03:56 if uptime > 2h); this is the suspected trigger, since an S3-only
reboot leaves the C6 on its previously negotiated UART baud rate (see the
2026-06-14 note above).

- A simultaneous power-cycle of both boards did not fix it.
- The sequential order above (S3 first, then C6) did fix it, but the
  recovery was not instantaneous — it took several minutes after the C6
  reset before tags started reporting fresh `lastseen` values.
- One side effect observed: the tag data for the very first check-in after
  a long radio outage can be corrupted/garbage (e.g. `hwType: 253` with no
  matching `resources/tagtypes/FD.json`, plus an impossible `temperature`
  and out-of-range `batteryMv` in the same record). `hwType 253` is not a
  real tag type here; the tag had reported `hwType: 17` in every prior
  session. `web.cpp`'s price endpoint hard-rejects anything but
  `hwType == 17`, so a price POST right after reconnect can fail with
  `"price-v1 currently supports hwType 17 only"` even for a known-good
  tag. This has cleared itself on the tag's next normal check-in in
  practice; if it doesn't, forcing a fresh check-in (button/NFC on the tag,
  or a battery pull) should get a clean packet.

### `apstate: 5` (AP_STATE_FAILED) and the yellow/blinking LED

Later the same session, `apstate` moved to `5` (`AP_STATE_FAILED` in
`include/serialap.h`; the enum is `0 OFFLINE, 1 ONLINE, 2 FLASHING,
3 WAIT_RESET, 4 REQUIRED_POWER_CYCLE, 5 FAILED, 6 COMING_ONLINE,
7 NORADIO`) while every tag's reported telemetry became garbage at once
(`hwType`, `batteryMv`, `temperature`, `ver` all nonsensical/inconsistent
across tags that had previously reported clean values).

- The firmware has its own watchdog for this (`serialap.cpp` around line
  1083): if the S3 gets no valid activity from the C6 for too long while
  `ONLINE` or already `FAILED`, it automatically retries a ping, and after
  5 failed attempts calls `bringAPOnline()` to reset the C6 itself in
  software. If that auto-recovery also fails, it sets `AP_STATE_FAILED`
  and plays an explicit `Yellow, Yellow, Red` LED pattern
  (`showColorPattern`, `serialap.cpp:1098`) — this is the "blinking LED"
  symptom. It then re-arms itself to retry again after another interval.
- Resetting only the C6 by hand while the S3 had been running continuously
  reproduced the same baud-desync failure mode as before, just mirrored:
  `apstate` oscillated between `0` (OFFLINE) and `5` (FAILED) for at least
  a minute and never reached `1`.
- Restarting **both** boards again in the documented order (S3 first, then
  C6) did bring `apstate` back to `1`, with tags checking in on schedule
  (fresh `lastseen` every cycle) — but this time the corrupted-telemetry
  side effect did **not** self-clear on later check-ins the way it did
  earlier in the day. `hwType` stayed `0` (the tagRecord default in
  `tag_db.h`, not `17`) across several consecutive fresh check-ins for the
  same tag, and two extra phantom tag entries appeared with all-zero
  fields and MAC addresses that were near-duplicates of a real tag's MAC
  (one byte different) — consistent with bit-level corruption on the
  radio link rather than a one-off sync glitch.
- A normal-looking tag screen does **not** confirm the link is healthy: an
  e-ink display holds its last successfully delivered image with no power
  and no connection, so it can look fine while the live link underneath is
  degraded.
- Not yet confirmed whether a full power-off (unplug, not just the reset
  button) of both boards for ~30 seconds clears this, versus needing more
  time for the RF environment to settle, versus a genuine hardware issue
  (antenna/connector on the C6 board). Picking this up is the first thing
  to check next session — retry the sequence, and if `hwType`/`batteryMv`
  are still wrong after a full cold power-off, escalate to a physical
  inspection of the C6 board's antenna/connector rather than more
  restarts.

## 2026-08-05

### Root cause #1: S3 firmware crash on repeated recovery attempts

Live serial debugging (PuTTY on the S3's `COM` port, 115200 baud) caught a
reproducible `Guru Meditation Error: Core 0 panic'ed (Double exception)`
(`EXCCAUSE 0x2`, identical `PC 0x40381ae2` both times), occurring every time
several `rxSerialTask starting` lines appeared before any matching `rxSerialTask
stopped` line. Re-wiring the S3<->C6 UART lines did **not** stop the crash from
recurring — proof the crash itself is a firmware bug, not a wiring symptom
(the wiring problem, found separately below, is what *triggers* the recovery
path that exposes this bug).

Root cause (`ESP32_AP-Flasher/src/serialap.cpp`, `ota.cpp`,
`include/serialap.h`): `rxSerialTask()` keeps its protocol state in `static`
locals (`cmdbuffer`, `packetp`, `pktindex`, `RXState`, `charindex`), shared by
every instance of the task rather than per-instance. `bringAPOnline()`'s
task-creation check (`if (gSerialTaskState != SERIAL_STATE_RUNNING) { ...
xTaskCreate(...) }`) was unguarded, and the only place that requests a stop
(`ota.cpp`'s `C6firmwareUpdateTask`, used by the C6 OTA-flash web route) only
set `gSerialTaskState = SERIAL_STATE_STOP` and waited a flat, unconditional
500ms — it never actually confirmed the old task reached
`SERIAL_STATE_STOPPED`. Under repeated failed-ping recovery cycles, this let a
second `rxSerialTask` start while the first one was still alive, and the two
instances corrupted the shared static state / heap pointer, producing the
crash.

Fix: added `serialTaskLifecycleMutex` (`SemaphoreHandle_t`, same idiom as the
existing `txActive`/`fsMutex`/`wsMutex`) and a `stopRxSerialTask(timeoutMs)`
helper that actually polls for `SERIAL_STATE_STOPPED` before returning.
`bringAPOnline()`'s task-creation block and `ota.cpp`'s stop sequence both now
take this mutex, guaranteeing at most one live `rxSerialTask` instance at any
time. Built (`pio run -e ESP32_S3_SIMPLE_AP`, success) and flashed to the S3
over `COM16`. Confirmed on hardware: the same trigger scenario that reliably
crashed the board twice in a row (with `RTC_SW_CPU_RST` in the reboot log) no
longer crashes it — subsequent resets show `rst:0x1 (POWERON)` only, i.e.
caused by manual power-cycling, not a panic.

### Root cause #2: C6 wires were on the wrong physical pins

The C6 dev board's pins silkscreened **"TX"/"RX"** are its primary console
UART (the same UART already carried out over USB by the onboard CH343 bridge
chip, visible on the host PC as a `USB-Enhanced-SERIAL CH343` COM port). The
firmware's actual S3<->C6 link uses a *separate* hardware UART
(`ARM_Tag_FW/OpenEPaperLink_esp32_C6_AP/main/second_uart.c`, UART port 1), on
different fixed GPIOs — for the "Default" hardware profile (the one active
here; see `main/second_uart.h`):

```text
C6 GPIO 2 = RX
C6 GPIO 3 = TX
```

The wires had been connected to the "TX"/"RX"-labeled pins instead, meaning
the S3 was never talking to the pins the firmware actually listens on. This
also explained a side symptom found while debugging: connecting the S3 wires
caused the C6's own CH343 console to go completely silent (bus contention —
S3 driving the same physical UART0 lines the CH343 chip uses), and
reconnecting only the C6 side to console showed no interference at all when
disconnected from S3, isolating it to those specific pins.

**New diagnostic technique for future sessions**: the C6 has its own
independent USB-serial console (CH343 bridge port, separate from whatever the
S3 exposes) that can be watched on its own, with no dependency on the S3 link
at all. While debugging, this showed the C6's own 802.15.4 radio actively
receiving/transmitting real frames to a tag (`RADIO: RX <len>` /
`RADIO: TX <len>` log lines, from `esp_ieee802154_receive_done`/
`_transmit_done` in `main/radio.c` — the printed number is the frame length in
bytes, not a GPIO pin) *even while the S3<->C6 UART link was completely dead*.
This is the fastest way in the future to tell "C6 and its radio are fine, the
S3 link specifically is the problem" apart from "C6 itself is dead" — connect
directly to the C6's own console before assuming the whole board has failed.

After moving both signal wires to C6 GPIO2/GPIO3 (S3 side unchanged: S3 GPIO2
-> C6 GPIO2, S3 GPIO1 <- C6 GPIO3, common GND unchanged): the C6 console
stayed alive with the S3 connected (no more silence), and began logging
`MAIN: RDY? In` roughly every 30 seconds (`main/main.c`, the C6 recognizing an
incoming `RDY?` ping from the S3's watchdog loop and replying `ACK>`) —
confirming two-way UART traffic for the first time this session.
`GET /get_ap_config` on the S3 (`http://192.168.31.203/`) confirmed
`"apstate": "1"` (ONLINE).

**Not yet fully closed**: `GET /get_db` at the same point still showed
`lastseen` values roughly 32 hours old (from before this session's fixes),
not a fresh check-in. Per the existing note above, tag check-in after a link
recovery can take several minutes and shouldn't be judged as failed
immediately — next session should re-check `/get_db` for a `lastseen` close
to current time to confirm a real tag round-trip end-to-end, not just a
healthy `apstate`.

## 2026-08-07

End-to-end price delivery was visually confirmed on real tags for the first
time: `POST /price` -> S3 -> C6 -> 802.15.4 radio -> e-ink display. Two tags
showed the pushed test price. This closes the open item from the 2026-08-05
entry above (a fresh `lastseen` / real tag round-trip, not just a healthy
`apstate`).

Getting there required fixing four independent problems, listed in the order
they were found.

### 1. S3 was unreachable because of a stale static IP

`GET /get_ap_config` could not be reached on any known address. Scanning the
home subnet found no Espressif device and no host with ports 80/8080 open.

Root cause: the S3 had Wi-Fi settings saved from the July phone-hotspot setup
(`192.168.31.x`, see the 2026-07-08 entry), including a static IP. It was
associating with the home router (`192.168.0.x`) successfully but assigning
itself an address from a subnet that does not exist there, so it was invisible.
Because the association *succeeded*, `startManagementServer()`
(`wifimanager.cpp:258-273`) never ran, so the `OpenEPaperLink` fallback config
AP never appeared either — which is what made this look like a dead board.

Fix: hold the BOOT button (GPIO0) for 5+ seconds while the firmware is running.
`wifimanager.cpp:103-131` polls GPIO0 and clears the saved ssid/pw/ip/mask/gw/
dns, then reboots. The `OpenEPaperLink` config AP then appears at
`http://192.168.4.1/setup`. Re-entered the home 2.4GHz SSID with **no** static
IP. The S3 is now at `192.168.0.34` (MAC `ac:a7:04:26:a2:ac`).

Note for future debugging: the S3 splits its console across two ports.
`ARDUINO_USB_CDC_ON_BOOT` is defined for `ESP32_S3_SIMPLE_AP`
(`platformio.ini`), so `Serial` is the **native USB port**, while the "COM"
connector (the USB-serial bridge, COM16 here) only carries raw `printf()`
output. `serialap.cpp` uses `#define LOG(...) printf(...)`, everything else
uses `Serial.*`. That is why COM16 shows only `rxSerialTask starting`, ROM boot
banners and panic dumps, and none of the Wi-Fi/IP logs — the console looks dead
when it is not.

### 2. AP_STATE_FAILED deadlock (fixed in code)

If the C6 was not ready when the S3 booted, `apInfo.state` went to
`AP_STATE_FAILED`. The recovery loop in `APTask` only pings the C6 when the
link has been **idle** for 30 seconds:

```cpp
if (((state == AP_STATE_ONLINE) || (state == AP_STATE_FAILED)) &&
    (millis() - lastAPActivity > AP_ACTIVITY_MAX_INTERVAL))
```

But `lastAPActivity` is refreshed on every tag transmission
(`serialap.cpp:533, 543, 567`). With tags checking in regularly the idle
condition never became true, `sendPing()` never ran, and the state stayed
`FAILED` forever. The AP was stuck *because* it was busy.

That state also gates content generation — `main.cpp:199` only calls
`contentRunner()` when the state is `ONLINE` or `NORADIO` — so nothing was ever
sent to the tags.

Fix (`serialap.cpp`, `APTask` watchdog loop): recent AP activity is itself
proof the link works, so recover from `FAILED` directly instead of waiting for
an idle window that never comes.

### 3. The 2 Mbaud UART upgrade (fixed in code)

After a successful handshake **at 115200**, `bringAPOnline()` sent `HSPD` and
switched both sides to 2,000,000 baud (`serialap.cpp:887-893`; the C6 side is
`main/main.c:291-295`). The handshake therefore always succeeded and `apstate`
briefly reached `1`, then the link died immediately after the switch, the
watchdog dropped it offline, and the retry re-connected at 115200 — an endless
flap. This matched the observed behaviour exactly: `apstate` oscillating
between `1` and `0`/`5` every 30-60 seconds.

Fix: added `-D AP_UART_STAY_115200` to the `ESP32_S3_SIMPLE_AP` env and guarded
the highspeed switch with it. Slower image transfers, stable link.

### 4. Wiring quality (fixed in hardware)

Disabling the 2 Mbaud switch improved things — `apstate` then held `1` for
40-60 second stretches instead of dropping instantly — but it still flapped.
Moving the S3<->C6 connection from loose dupont jumper wires onto a
**protoboard** eliminated the remaining instability completely: `apstate` held
`1` across 25 consecutive polls over ~3 minutes with zero drops, and tags
resumed checking in.

Both fixes were needed. The 2 Mbaud switch made even good wiring marginal; the
dupont wiring made even 115200 marginal.

### Observed side effects while the link was flapping

- `pending` climbed (1 -> 6) on a single tag: every successful reconnect calls
  `refreshAllPending()`, re-queueing the same payload.
- Those queued items eventually expired (`pending` back to 0) without being
  delivered.
- `lastseen` stretched from ~15 minutes to ~3 hours: tags that repeatedly fail
  to complete a check-in back off to save battery. After the link was fixed the
  tags returned on their own, without needing a manual reset.

### Raspberry Pi

The Pi was found at `192.168.0.35` (MAC `b8:27:eb:76:24:aa`) after connecting
it to the router by Ethernet; its saved Wi-Fi is still the old July hotspot, so
it does not join the home network on its own yet. `/etc/price-proxy.env` still
had `ESP_BASE_URL=http://192.168.31.203:8080` (the stale hotspot address) —
updated to `http://192.168.0.34:8080` and `price-proxy` restarted.

### Still open

- Add the home Wi-Fi to the Pi so it does not need the Ethernet cable.
- Make a DHCP reservation for the S3 (`ac:a7:04:26:a2:ac`) so its address stops
  moving; `PRICE_API.md` still refers to `192.168.0.24` from an earlier session.

## 2026-08-11

The central product database (`tools/central_db.py`, 100 products) was tested
against real hardware for the first time. One tag received and displayed its
price through the full chain — central DB on the laptop -> Pi -> S3 -> C6 ->
radio -> e-ink. Two tags did not, and that is the open item below.

### Network as found this session

The S3 came back on `192.168.0.34` with `apstate: 1` straight after power-on,
so the 2026-08-07 firmware fixes hold across a power cycle. The Pi auto-joined
the home WiFi on `192.168.0.40` with the Ethernet cable unplugged, confirming
the NetworkManager profile added last session works. `PACMS_BASE_URL` on the Pi
was pointed at the laptop (`http://192.168.0.30:9000`) so the Pi exercises a
real network path to the catalog rather than localhost; Windows Firewall did
not block it.

`/sync-now` against the real catalog returned
`{"skus_mapped": 3, "checked": 3, "pushed": 3, "failed": 0}`, and an immediate
re-run returned `pushed: 0, unchanged: 3`, so the SKU-scoped fetch and the
`price_cache` diff both behave correctly against the new database.

### Tag wake-up behaviour

`resources/tagtypes/11.json` lists `"options": [ "button" ]` for hwType 17, but
these physical tags have **no button**. Battery removal is the only manual
wake, and it only helps if the replacement cell is charged — two tags were
simply flat. Note that `batteryMv` in `/get_db` is only refreshed when a tag
checks in, so a stale `3000` on a silent tag says nothing about its current
charge; the last-seen timestamp has to be read alongside it.

Two config values are relevant here and neither was changed yet:

- `maxsleep` is `0`. In `contentmanager.cpp:76-90` that clamps
  `minutesUntilNextUpdate` to zero, the `> 1` guard fails, and
  `prepareIdleReq()` is never called — so the AP never tells a tag when to
  come back and the tag falls back to its own firmware interval. It also makes
  `tag_db.cpp:284` flag a tag as timed out after only 5 minutes. Setting it to
  ~10 was proposed.
- `stopsleep` is already `1`, so while the AP web UI is open in a browser
  `newproto.cpp:166` tells tags not to sleep at all. Worth having the UI open
  during any test session.

### Open: two tags check in but never receive their image

All three tags now check in every ~30 seconds, but two keep `pending = 1`
indefinitely and their screens stay on the tag firmware's own "waiting for
data" message (that string is not in the AP firmware).

Content generation is not the problem — `/current/<MAC>.json`, `.raw` and
`<MAC>_<millis>.pending` all exist on the S3 for the stuck tags, while the tag
that succeeded has no `.pending` file left. The failure is in the radio block
transfer itself.

Leading hypothesis, and it may be self-inflicted: `AP_UART_STAY_115200` (added
2026-08-07 to stop the link flapping) makes each 4096-byte block
(`BLOCK_DATA_SIZE`, `proto.h:147`) take roughly 0.36s over UART instead of
0.02s at 2 Mbaud. If the tag times out waiting for a block after requesting
it, that extra latency would break the transfer. Against the hypothesis: one
tag did complete a transfer on this same firmware, which suggests marginal
timing rather than an outright break.

Next step is to read the AP web UI's log panel while a stuck tag checks in.
These two lines go through `wsLog` and so appear there, unlike the
`Serial.printf` diagnostics which go to the S3's native USB port rather than
the COM connector:

- `... block request <file> block N, len L checksum C` (`newproto.cpp:419`)
- `... reports xfer complete` (`newproto.cpp:429`)

No block-request lines means the failure is before the transfer starts. Block
requests without an xfer complete would confirm the baud hypothesis, in which
case the options are an intermediate baud rate (460800 rather than 2000000) or
a smaller block size.

## 2026-08-12

Session goal: work out why tags are so hard to bring back after they have been
powered off. Answer found, and it is not a bug in anything we wrote.

### Root cause: the tag's own scan backoff

The tags are hwType `0x11` (M2 2.9"), which is a ZBS243 part. That firmware is
not in this repo; it lives in `OpenEPaperLink/Tag_FW_ZBS243`. From
`tag_fw/powermgt.h`:

    #define INTERVAL_1_TIME     3600UL   // Try every hour
    #define INTERVAL_1_ATTEMPTS 24       // for 24 attempts (an entire day)
    #define INTERVAL_2_TIME     7200UL   // Try every 2 hours
    #define INTERVAL_2_ATTEMPTS 12       // for 12 attempts (an additional day)
    #define INTERVAL_3_TIME     86400UL  // Finally, try every day

A tag that boots and does not find an AP sleeps 2 minutes
(`tag_fw/main.c:889`), then enters `TagChanSearch`, which sleeps
`getNextScanSleep()` after every failed scan (`tag_fw/main.c:492`). So the
retry ladder is one hour for a day, two hours for another day, then once a day
forever. Nothing external can shorten it, because the radio is off.

Practical rule: **power the AP up and confirm `apstate: 1` before the tags get
power.** A tag that misses its boot scan costs an hour minimum.

This also explains the older observation that only one of three tags comes
back after a power cycle: whichever tag happens to scan while the AP is
answering associates, and the others fall into the ladder.

### Why "wake the tags on demand" cannot work here

`enableRFWake` in `tagsettings` is real: it leaves the ZBS243 carrier detector
powered during sleep (`tag_fw/powermgt.c:332`, `RADIO_RadioPowerCtl &= 0xFB`)
so RF energy raises `WAKEUP_REASON_RF`. Costs about 0.9µA
(`oepl-proto.h:160`). It is exposed in the AP web UI under Set Tag Config
(`wwwroot/content_cards.json:681`).

But the C6 AP never transmits unless spoken to. Every `radioTx` in
`ARM_Tag_FW/OpenEPaperLink_esp32_C6_AP/main/main.c` sits in a reply path
(`sendPart`, `sendXferCompleteAck`, `sendCancelXfer`, `sendPong`,
`processTagReturnData`), each doing `memcpy(txHeader->dst, rxHeader->src, 8)`,
and the main loop at `main.c:789` is receive-only. There is no beacon.

So RF wake gives a herd effect only: once one tag talks, the AP's replies put
energy on the channel and can wake neighbours that have the flag set. It is
not a remote wake switch. Building one would mean adding deliberate
transmission on the AP side.

For reference, commercial systems dodge the problem rather than solve it:
infrastructure runs 24/7 so tags never enter a backoff, Bluetooth 5.4 PAwR
gives each tag a scheduled slot, and Pricer uses infrared, where an always-on
photodiode is cheap enough to leave listening.

### Two gotchas found while reading the AP code

`/save_cfg` does not persist. The `saveDB` call at `web.cpp:568` is commented
out, so a queued tag config lives in RAM only and is lost if the AP reboots.
Hit this for real today: config was queued, the S3 rebooted, and all three
tags silently reverted to `contentMode 19`.

`lastseen` can move backwards after a config push. `popTagInfo`
(`tag_db.cpp:526`) restores the snapshot that `pushTagInfo` took when the mode
was changed, so post-transfer the record carries the *old* `lastseen`,
`pending` and `updatecount`. Do not read a stale `lastseen` as proof that a
tag never checked in.

### State at end of session

S3 `192.168.0.34` (`apstate: 1`, stable, uptime climbing normally), Pi
`192.168.0.40` with `price-proxy` active, central DB running on the laptop
with 100 products. Addresses unchanged from 2026-08-11.

- `00000181500F3B39` — recovered after a battery reseat. Checks in every ~30s,
  accepted the RF wake config (`contentMode` 18 -> 19), `updatecount` 15.
- `000001811E293B37` — still asleep in the ladder, config queued.
- `0000018152583B39` — still asleep, and `batteryMv` reads 2100, below the
  `BATTERY_VOLTAGE_MINIMUM` of 2450. Flat cell; it was the tag that did all
  the work on 2026-08-11 (`updatecount` 23). Needs a new battery.

Note that the two tags left stuck at `pending = 1` on 2026-08-11 were all at
`pending = 0` when this session opened, so those transfers did complete on
their own afterwards. The block-transfer worry from that session is therefore
weaker than it looked, though not formally closed.

### Next session

1. Reseat the battery on `000001811E293B37` and fit a fresh cell in
   `0000018152583B39`, with the AP already up.
2. Confirm each one picks up the queued RF wake config, then re-queue it if
   the AP has rebooted in the meantime.
3. Run `/sync-now` and confirm prices from the central DB reach all three.
4. Optional and still not applied: `maxsleep` is `0`. Setting it to ~10 bounds
   how long an *associated* tag sleeps. Separate from the scan ladder above.

## 2026-08-12 (later the same day) — the cold-start sequence, confirmed

**All three tags came back on the first try.** This is the first time that has
happened, and no code was changed to achieve it — `git status` was clean and
the last commit was documentation only. What changed was the order of power-up.

### The sequence that worked (follow this every time)

1. Power the **S3** first. Wait.
2. Power the **Pi**. Wait.
3. Power the **C6**. Wait until the AP web UI shows `apstate: 1`.
4. Only then, **pull each tag's battery out and put it back.**

The waiting between steps is not superstition — the tag has a fixed, short
window and everything upstream of it has to already be answering.

### Measured result

    000001811E293B37  mode=19  pending=0  upd=9   bat=3000mV  seen 10s ago  RSSI -38
    00000181500F3B39  mode=19  pending=0  upd=15  bat=3000mV  seen 38s ago  RSSI -39
    0000018152583B39  mode=19  pending=0  upd=24  bat=3000mV  seen 44s ago  RSSI -43

    AP uptime 811s (13.5 min), apstate 1, heap 191992

All three checked in inside a 34-second spread — i.e. each one found the AP on
its **boot scan**, not after an hour in the ladder.

### Why the battery pull is a real reset

These tags have **no button**, despite `resources/tagtypes/11.json` listing
`"options": [ "button" ]`. Removing and reinserting the cell is a genuine cold
boot of the 8051: `scanAttempts` resets to 0 and the tag re-enters
`TagChanSearch` from the top, with the 2-minute first-boot window
(`tag_fw/main.c:889`) rather than the 1h/2h/24h ladder.

So the reset **does** work reliably — but it is only half the mechanism. The
other half is that the AP has to be answering during those 2 minutes. A battery
pull with no AP up does not fail gracefully; it just restarts the hour-long
countdown, which is exactly what made this look random for weeks. Pull the
battery again after 2-3 minutes of silence rather than waiting an hour.

### Battery reading correction

`0000018152583B39` read 2100 mV at the end of the previous session — below
`BATTERY_VOLTAGE_MINIMUM` (2450) — and was written up as needing a new cell.
It now reads 3000 mV on the **same** cell. That 2100 mV was a loaded reading
taken after the tag had done 23 updates that day; coin cells recover their
terminal voltage once the load is removed. Treat a single low `batteryMv` after
heavy activity as suspect, not as proof of a flat cell.

### RF wake config did not survive, as predicted

All three tags read `contentMode 19`, not 18. The config queued for
`000001811E293B37` and `0000018152583B39` was lost when the S3 was powered off
overnight, confirming the `web.cpp:568` non-persistence gotcha above. RF wake
is therefore **not** the reason today worked — the power-up order is.

## 2026-08-13 — scale testing without 400 tags, and three bugs it found

The open question before production was how the system behaves with a few
hundred tags when we only own three. Most of that risk turns out not to be in
the radio at all: the AP holding the records, `/get_db` paging them out, and
the gateway reading them back are all exercisable with tags that do not exist.
`tools/make_synthetic_tagdb.py` generates a tag database and the AP's own
`POST /restore_db` loads it.

Everything below was found on the bench in one session, with no extra hardware.

### The AP already knows 8 tags, not 3

`GET /get_db` lists three `hwType 17` price tags, two `hwType 1`, and three
`hwType 0`. Relevant because the limits below are counted in tags, not shelves.

### Bug 1 — the gateway confirmed deliveries for only the first ~11 tags

`tagDBtoJson` stops filling a response once it passes 5000 bytes
(`tag_db.cpp:80`) and reports where to resume in `continu`. Measured at **444
bytes per tag, so about 11-12 records per page**. `fetch_tag_state()` read one
page and ignored `continu`.

With three tags this is invisible. Loaded with 48, the old code saw **12 of
48**; the other 36 would never confirm, would be retried to exhaustion and
reported `undelivered` while their prices were in fact on the glass — the
shelf-status column would go red across the store for a system that was
working. Fixed: `fetch_tag_state()` now follows `continu`, and reads 48 of 48.

### Bug 2 — the AP cannot page past 255 tags at all

`web.cpp:477`:

    uint8_t startPos = 0;
    startPos = atoi(request->getParam("pos")->value().c_str());

`atoi` returns `int` into a `uint8_t`, so `?pos=256` truncates to 0 and the AP
restarts from the beginning. Any client that keeps following `continu` past
255 loops forever. **This is a hard wall at 255 tags per AP** and needs a
firmware change (`uint16_t`) plus a reflash. The gateway now detects the wrap
and stops with an explicit log line rather than spinning.

### Bug 3 — an interrupted `/restore_db` wedges further restores

`dotagDBUpload` (`web.cpp:1223`) takes `fsMutex` on the first chunk and
releases it only on `final`. Uploading 408 records (227 KB) held the
filesystem locked and the connection was reset after 67s, so `final` never
ran — the mutex was never given back. Two consequences:

* The DB survived intact, because `destroyDB()` also only runs on `final`.
  Failure is at least safe.
* Every later restore silently did nothing. A subsequent 108-record upload
  returned **HTTP 200 in 8.4s and changed nothing** — the tag DB stayed at the
  previous 48 records.

The 200 is meaningless: `request->send(200)` sits in the request handler
(`web.cpp:1010`) and fires regardless of what the upload handler did. **Never
treat a 200 from `/restore_db` as proof it worked — read `/get_db` back.**

Sizes that did work: 48 records in 2.2s, 108 records in 8.4s (before the
wedge). Only a reboot clears **the wedge** — it is a held mutex, i.e. RAM
state. A reboot does *not* clear the loaded tags themselves; see below.

### What this means for provisioning

Restoring a full store's tag database is exactly what happens when a shop is
set up or an AP is replaced, so all three bugs sit on the provisioning path.
Bug 2 in particular caps a single AP at 255 tags regardless of radio capacity,
which is an architecture input, not a tuning detail.

### Cloudflare tunnel and the old gateway.service are gone

Earlier notes above describe a Quick Tunnel exposing the Pi; it no longer
exists. Both `cloudflared-quicktunnel.service` and the stale July 31
`gateway.service` (which was still polling `192.168.31.66:9000` every five
minutes from `/opt/gateway/`) were stopped and `systemctl disable`d on
2026-08-13. `price-proxy` binds to `127.0.0.1` and `sync-now.timer` drives it
from inside the Pi, so **the Pi's only externally reachable port is now SSH
(22)**. Nothing calls into the store, which is the whole point of the polling
architecture. Treat any mention of a tunnel hostname above as historical.

### Measured: what one tag costs the radio

Fleet size is limited by how long the AP is *busy* with a tag, not by how
often tags wake up — sleeping tags are free. Measured by pushing a price and
polling one tag's record at 0.3s, watching `lastseen` move (the tag is talking)
and then `updatecount` increment (it has taken the image):

| tag | push accepted | waited for check-in | **transfer** | total |
|---|---|---|---|---|
| Bosch  `…293B37` | 0.13s | 9.9s  | **3.9s** | 13.8s |
| Makita `…0F3B39` | 0.14s | 22.3s | **3.9s** | 26.2s |
| DeWalt `…583B39` | 0.16s | 4.6s  | **3.9s** | 8.5s  |

**3.9 seconds per tag**, identical across all three to the limit of the
sampling interval — as expected for a fixed 296×128 1-bit image. Check-in wait
varied 4.6-22.3s and is latency, not cost.

Serialised, that gives:

| tags | radio time |
|---|---|
| 100 | ~7 min |
| 255 (the firmware wall) | ~17 min |
| 400 | ~26 min |

So a full push to 400 tags is around **26 minutes** — comfortably inside a
morning window, and this is the worst case that only happens on first install
or after an AP replacement. A normal morning pushes only changed prices, which
is a handful. **Radio capacity is not the constraint; the 255-tag pagination
wall is.**

Treat 3.9s as a floor: it assumes no collisions and no retries, and larger tag
types will take longer.

### The price API rate-limits, and it bites at scale

Restoring the three prices back-to-back after the measurement returned
**HTTP 429 Too Many Requests** on the second one. `gateway.py` already spaces
pushes 1.1s apart so it never sees this, but anything else driving the API
must. At 400 tags that throttle alone is ~7 minutes of enqueueing, which
overlaps the 26 minutes of radio time rather than adding to it.

### Dead tags degrade the whole AP, not just themselves

While the 40 synthetic tags sat in the database, the AP became barely usable:
`/sysinfo` took **0.15-8.4s** to answer, one request in five timed out
entirely, and **33% of pings were lost** with RTT spiking to 1283 ms. Deleting
them restored it immediately — 0.01-0.16s and **0% loss** on the same link,
minutes later, with nothing else changed.

The cause is `contentRunner()` walking the whole tag database and trying to
generate content for records that will never check in. Forty was enough to
starve the web server and the radio task.

This is a production finding, not a test artifact. A store accumulates dead
records — tags that fail, get removed from a shelf, or have their battery run
out — and each one keeps costing the AP. **Prune the tag database when a tag
is retired**; `POST /tag_cmd` with `cmd=del` is the per-tag delete, and
`tools/cleanup_synthetic_tags.py` shows the pattern (read `/get_db`
paginated, delete by MAC, read it back to confirm).

`cmd=purge` deletes everything not seen in 24 hours in one call, which is
convenient but takes any real tag that is merely idle. Prefer targeted
deletes.

### Removing synthetic tags: what does not work

* **A reboot does not clear them.** `main.cpp:39` autosaves the tag database
  to flash every five minutes and `main.cpp:143` loads it back at boot, so
  synthetic records survive a power cycle. An earlier note in this file said
  otherwise; it was wrong.
* **`/restore_db` cannot be used** while the `fsMutex` wedge described above
  is in effect — it answers 200 and does nothing.

Per-tag `cmd=del` needs neither a reboot nor a reflash and does not interrupt
the shelves. All three price tags kept `contentMode 19` and their
`modecfgjson` through the cleanup, and were confirmed showing 8499 / 5000 /
14499 RSD afterwards.

### Flashed, and all three fixes confirmed on hardware

Flashed over USB rather than OTA: `/update_ota` does not accept an uploaded
file, it takes `url`/`md5`/`size` and makes the AP fetch the binary itself,
which needs a web server on the LAN. With the S3 on a cable that is a detour.

Note which port. The board enumerates two USB devices and only one is useful
here:

* `USB-Enhanced-SERIAL CH343 (COM16)`, `VID_1A86&PID_55D3` — the UART bridge,
  **this is the one to flash through**
* `USB Serial Device (COM4)`, `VID_303A&PID_1001` — the S3's native USB. It
  showed up in Windows only as a not-present ghost from an earlier session.

Always confirm what is on the other end before writing, since the C6 is on the
same bench:

```bash
python ~/.platformio/packages/tool-esptoolpy/esptool.py --port COM16 chip_id
# Chip is ESP32-S3 (QFN56) (revision v0.2)
# Features: WiFi, BLE, Embedded PSRAM 8MB (AP_3v3)
# MAC: ac:a7:04:26:a2:ac
```

Then:

```bash
pio run -e ESP32_S3_SIMPLE_AP -t upload --upload-port COM16
```

1985952 bytes, hash verified, 100s. `-t upload` writes the app partition only,
so LittleFS — `tagDB.json`, the web UI, everything under `/current/` —
survives. `sysinfo.buildtime` went 1786104105 → 1786615119, which is the
cheapest proof the new image is actually running.

**The tags came back on their own. No battery reseat was needed**, unlike
every earlier power cycle — because the AP was answering by the time they
next checked in.

Verification of each fix:

| fix | test | result |
|---|---|---|
| `uint16_t startPos` | `/get_db?pos=256` with 8 tags | returns 0 tags. Old firmware truncated 256 to 0 and returned all 8 — a wrap that looked like valid data |
| `/restore_db` reporting | upload the 8-tag backup | **`Ok, restored 8 tags.`** — the count comes from `tagDB.size()`; the old build said `Ok, restored.` even when it had done nothing |
| `fsMutex` per chunk | same upload, 1.8s | completes and takes effect; no wedge |

Afterwards: 8 tags, all three price tags on `contentMode 19` showing 8499 /
5000 / 14499 RSD, AP answering in 0.015-0.029s.
