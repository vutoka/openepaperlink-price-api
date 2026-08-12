# Price API

The preferred API runs directly on the ESP32-S3 on TCP port `8080`. Port 80
remains the local OpenEPaperLink administration interface and must not be
forwarded to the Internet.

For production, expose the Raspberry Pi proxy instead of exposing the ESP
directly:

```text
Home server / Postman
  -> HTTPS Cloudflare hostname
Cloudflare Tunnel
  -> Raspberry Pi http://localhost:8000
Raspberry proxy
  -> ESP32-S3 http://ESP_IP:8080
```

Use separate tokens:

```text
PUBLIC_API_TOKEN = home server -> Raspberry proxy
ESP_API_TOKEN    = Raspberry proxy -> ESP32-S3 API
```

## S3 firmware API

The custom `ESP32_S3_SIMPLE_AP` firmware provides:

- `GET /health`
- `POST /price`

Both endpoints require:

```text
Authorization: Bearer YOUR_TOKEN
```

Set a random token containing 24 to 64 characters. After installing the new
firmware, it can be set from the local web interface under:

```text
Config > Price API token
```

The token is stored on the S3 in `/current/api_token.txt` and is never returned
by `/get_ap_config`.

### Postman

For local testing:

```text
POST http://192.168.0.24:8080/price
```

Headers:

```text
Authorization: Bearer YOUR_TOKEN
Content-Type: application/json
```

Raw JSON body:

```json
{
  "mac": "00000181500F3B39",
  "product": "Mleko 1L",
  "price": "149.99",
  "currency": "RSD",
  "note": "Akcija"
}
```

A successful request returns HTTP `202`. The image transfer happens
asynchronously when the tag checks in.

### Internet access

Do not forward ports in production when using Cloudflare Tunnel. Configure the
Cloudflare public hostname to point to the Raspberry-local proxy:

```text
http://localhost:8000
```

If Cloudflare Tunnel is not used, a less preferred direct-router setup would
forward one chosen external TCP port only to:

```text
192.168.0.24:8080
```

Do not forward S3 port 80. Give the S3 a DHCP reservation so its local address
does not change.

Because this endpoint is HTTP rather than HTTPS:

- anyone who can observe the traffic can steal and replay the bearer token;
- a man-in-the-middle can change the product, price, note, or destination MAC;
- the client cannot cryptographically verify that it reached the real S3;
- Internet scanners can attempt token guessing and denial-of-service requests.

The separate API port prevents access to the S3 administration, OTA, reboot,
and filesystem endpoints, but it cannot provide confidentiality or transport
integrity. Use a long random token, rotate it if exposed, and restrict source
IPs on the router when possible.

## Central product database

`tools/central_db.py` is the store-agnostic catalog every store's Pi pulls
prices from. It is SQLite-backed, so the data survives a restart, and it
replaces the earlier in-memory `mock_pacms.py`.

Run it on the host that holds the catalog -- deliberately not on the Pi, so
the Pi exercises a real network path:

```bash
python tools/central_db.py --seed   # first run: creates and fills the catalog
python tools/central_db.py          # afterwards
```

Environment:

```text
CENTRAL_DB_LISTEN=0.0.0.0
CENTRAL_DB_PORT=9000
CENTRAL_DB_API_KEY=replace-with-central-db-key
CENTRAL_DB_PATH=tools/central.db
```

The `products` table holds `id`, `sku` (unique), `barcode`, `title`, `price`,
`stock` (quantity), and `modified_at`. `modified_at` is set automatically on
every edit. The seed catalog contains 100 hardware-store products.

A product carries **one** price: the number to print on the shelf. Resolving
promotions is the catalog's job, so the ESL system is never handed two figures
and asked to choose. (`products.sale_price` still exists in the schema so
already-seeded databases open, but nothing reads it and the API does not
expose it.)

Endpoints (all except `GET /` require `X-Api-Key`):

```text
GET  /                              worker UI
GET  /health
GET  /api/Esl/Prices?skus=a,b,c     what gateway.py calls
GET  /api/Esl/Prices?since=<ISO8601>&page=<int>&size=<int>
POST /api/Esl/Products/<sku>        {"price":…, "stock":…}
POST /api/Esl/ShelfStatus           a store reports what its shelves show
GET  /api/Esl/ShelfStatus           read those reports back
```

`GET /` serves a small page a shop worker can use to change a price or stock
count. The page itself loads without a key; it asks for the key once, keeps it
in `sessionStorage`, and sends it as a header on every data call, so the key is
never baked into the served HTML. Treat this UI the same as the S3 admin port:
keep it on the local network, do not expose it publicly.

`gateway.py` needs no changes to work against this service; the HTTP contract
is the same one it was written for.

### Shelf status

The worker page has a **Polica** column showing what each price actually did:

| Pill | Meaning |
|---|---|
| `na polici` (green) | confirmed -- the glass shows this price |
| `salje se` (yellow) | sent, waiting for the tag to wake and take it |
| `NIJE STIGLO` (red) | retried to exhaustion; the shelf shows the old price |
| `nema taga` (grey) | priced, but nothing is mapped to display it |

Each store posts this after every sync. The post is **outbound** -- the
catalog never calls into a store -- and it carries that store's complete
picture, so shelves the report no longer mentions are deleted rather than left
showing a stale red. Without that, a retired tag would sit red forever and the
colour would stop meaning anything.

## Raspberry Pi proxy

The Pi proxy files are:

```text
tools/raspberry_price_proxy.py
tools/gateway.py
tools/tag_mapping.py
tools/price-proxy.service
tools/price-proxy.env.example
```

Installed target paths:

```text
/opt/price-proxy/app.py
/opt/price-proxy/gateway.py
/opt/price-proxy/tag_mapping.py
/etc/price-proxy.env
/etc/systemd/system/price-proxy.service
```

`gateway.py` and `tag_mapping.py` must sit next to `app.py` on the Pi so
`import gateway` / `import tag_mapping` resolve.

Example environment:

```text
PRICE_PROXY_LISTEN=127.0.0.1
PRICE_PROXY_PORT=8000
ESP_BASE_URL=http://ESP_IP:8080
PUBLIC_API_TOKEN=replace-with-random-public-token
ESP_API_TOKEN=replace-with-esp-token
ESP_FORWARD_TIMEOUT=15
PACMS_BASE_URL=http://PACMS_HOST:PORT
PACMS_API_KEY=replace-with-pacms-key
```

`PROXY_PUBLIC_TOKEN` is only needed if the gateway's internal call back to
this same proxy should use a different token than `PUBLIC_API_TOKEN`; if
unset, it falls back to `PUBLIC_API_TOKEN` automatically.

Do not commit `/etc/price-proxy.env` or real token values.

### `POST /sync-now`

Requires the same bearer token as `/price`. No request body. Reads this
store's SKUs from the local `tag_mapping` table, asks PACMS for just those
(batched), and pushes only the prices that actually changed since the last
sync.

```text
POST http://localhost:8000/sync-now
Authorization: Bearer YOUR_PUBLIC_TOKEN
```

Response:

```json
{
  "ok": true,
  "skus_mapped": 400,
  "checked": 400,
  "pushed": 2,
  "unchanged": 398,
  "failed": 0,
  "confirmed": 1,
  "resent": 0,
  "undelivered": 0,
  "in_flight": 2
}
```

If a sync is already running, a second call returns HTTP `409` with
`{"ok": false, "error": "sync already in progress"}`.

`/sync-now` is called by `sync-now.timer` (see below), not by an internal
loop -- prices only move when something triggers a sync.

### Delivery is confirmed, not assumed

A `202` from the AP means *queued*, not *displayed*. A tag that is out of range
or flat when its price is pushed will never show it, so treating the 202 as
success would cache the new price and never retry: the shelf would be wrong,
silently and permanently.

So the gateway tracks two stages:

| Table | Meaning |
|---|---|
| `delivery` | pushed to the AP, not yet seen on the tag |
| `price_cache` | **confirmed on the tag** -- what the shelf really shows |

Only `price_cache` is compared against PACMS, and only a confirmed price gets
written to it. Confirmation reads the AP's own database
(`GET /get_db` on `AP_WEB_URL`) and requires all three of:

* the tag is no longer marked `pending`
* its `updatecount` has increased since the push
* the content the AP rendered for it carries the price we sent

Anything unconfirmed is re-sent after `DELIVERY_RETRY_AFTER_SECONDS`, up to
`DELIVERY_MAX_ATTEMPTS`, then reported as `undelivered` -- red in the worker
UI -- rather than forgotten. Pushes the AP *refuses* (wrong `hwType`, proxy
down) are recorded the same way, so a price that can never be delivered ends
up visibly red instead of sitting in "sending" forever.

Extra environment for this:

```text
AP_WEB_URL=http://192.168.0.34            # AP's plain web port, where /get_db lives
STATUS_REPORT_URL=http://192.168.0.30:9000  # catalog to report shelf status to
STORE_ID=default                          # which store this Pi is
DELIVERY_RETRY_AFTER_SECONDS=900
DELIVERY_MAX_ATTEMPTS=5
```

`python3 gateway.py status` prints the current per-shelf state without
syncing.

### `sync-now.timer`

`tools/sync-now.service` and `tools/sync-now.timer` make the Pi trigger its own
sync, so nothing has to call into the store: no domain, no tunnel, no open
port. A sync missed while the Pi was down is picked up on the next run instead
of being lost -- which is exactly why this is a pull and not a webhook.

```bash
sudo install -m 644 tools/sync-now.service tools/sync-now.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sync-now.timer
systemctl list-timers sync-now
journalctl -u sync-now -f      # one JSON summary per run
```

Development cadence is `OnUnitActiveSec=60`. For production, swap it for a
single morning pull:

```ini
OnCalendar=*-*-* 06:00:00
Persistent=true
```

`Persistent=true` matters -- a store that lost power overnight then syncs on
boot instead of opening with yesterday's prices.

For a bulk price update touching many tags at once, prefer calling
`/sync-now` from an SSH session directly against `http://127.0.0.1:8000`
rather than through the Cloudflare Quick Tunnel. The ESP32 API accepts at
most one price push per second, so a large batch can take several minutes;
the tunnel's own request timeout may be shorter than that even though the
sync keeps running correctly in the background.

## Cloudflare Quick Tunnel on the Raspberry Pi

Until a named tunnel with a stable hostname is set up (requires a domain in
the Cloudflare account), the Pi runs a Cloudflare Quick Tunnel pointed at the
local proxy. The unit file is:

```text
tools/cloudflared-quicktunnel.service
```

Installed target path:

```text
/etc/systemd/system/cloudflared-quicktunnel.service
```

It depends on and starts after `price-proxy.service`, and forwards
`https://<random>.trycloudflare.com` to `http://localhost:8000` (the proxy,
not the ESP directly).

The quick tunnel has no uptime guarantee and gets a new random hostname every
time the service restarts. After the Pi boots or the service restarts, read
the current URL from the journal:

```bash
sudo journalctl -u cloudflared-quicktunnel --no-pager \
  | grep -o 'https://[a-zA-Z0-9.-]*trycloudflare.com' | tail -1
```

## Optional computer-side proxy

The older helper below remains available when HTTPS termination or a more
capable public API is needed. It converts a simple product/price request into
an OpenEPaperLink JSON template and sends it to the access point.

## Start

```powershell
$env:OEPL_AP_URL = "http://192.168.0.24"
$env:PRICE_API_TOKEN = "change-this-token"
.\.venv\Scripts\python.exe .\tools\price_api.py
```

The default API address is `http://127.0.0.1:8080`.

To accept requests from another computer on the same LAN, start it with:

```powershell
.\.venv\Scripts\python.exe .\tools\price_api.py --listen 0.0.0.0
```

Keep `PRICE_API_TOKEN` configured when listening outside localhost.

## Check status and tags

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health `
  -Headers @{ Authorization = "Bearer change-this-token" }

Invoke-RestMethod http://127.0.0.1:8080/tags `
  -Headers @{ Authorization = "Bearer change-this-token" }
```

## Send a price

```powershell
$body = @{
  mac = "00000181500F3B39"
  product = "Mleko 1L"
  price = "149.99"
  currency = "RSD"
  note = "Akcija"
} | ConvertTo-Json

Invoke-RestMethod http://127.0.0.1:8080/price `
  -Method Post `
  -ContentType "application/json" `
  -Headers @{ Authorization = "Bearer change-this-token" } `
  -Body $body
```

The current layout supports the detected 296x128 `hwType 17` tag.

## AP restart order

The S3 switches the C6 UART from 115200 baud to 2 Mbaud after connecting.
Restarting or unplugging only the S3 can leave the powered C6 at 2 Mbaud,
causing the S3 web interface to report `failed`.

After restarting the S3:

1. Reset or power-cycle the C6.
2. Wait several seconds for AP state to become `online`.
3. Send API requests.

Resetting both boards together also avoids the baud-rate mismatch.
