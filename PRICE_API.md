# Price API

The preferred API runs directly on the ESP32-S3 on TCP port `8080`. Port 80
remains the local OpenEPaperLink administration interface and must not be
forwarded to the Internet.

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

Configure the router to forward one chosen external TCP port only to:

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
