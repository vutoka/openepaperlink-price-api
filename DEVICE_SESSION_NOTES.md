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
