# Read First

This repository is a modified OpenEPaperLink project. Read this file before
making changes or asking an AI agent to work on the repo.

## Reading Order

1. `AI_CONTEXT.md`
   - Start here.
   - It separates what has already been implemented from what is only planned.

2. `PRICE_API.md`
   - API contract, Postman examples, and security notes.

3. `DEVICE_SESSION_NOTES.md`
   - Detailed hardware/session notes, backup hashes, and operational caveats.

4. Relevant source files:
   - `ESP32_AP-Flasher/src/web.cpp`
   - `ESP32_AP-Flasher/include/tag_db.h`
   - `ESP32_AP-Flasher/src/tag_db.cpp`
   - `ESP32_AP-Flasher/wwwroot/index.html`
   - `ESP32_AP-Flasher/wwwroot/main.js`

## Prompt For An AI Agent

Use this prompt when opening the repo in another AI tool:

```text
Read READ_FIRST.md, AI_CONTEXT.md, PRICE_API.md, and DEVICE_SESSION_NOTES.md
before making changes. Treat AI_CONTEXT.md as the source of truth for what is
already done versus what is planned. Do not expose port 80 publicly. Do not
commit tokens, Wi-Fi passwords, Cloudflare credentials, .venv, .pio, logs, or
device backup binaries. The implemented API runs directly on the ESP32-S3 on
port 8080; Raspberry Pi and Cloudflare Tunnel are planned deployment work, not
yet completed production setup.
```

## Current Status In One Paragraph

The ESP32-S3 firmware has been modified, built, flashed, and verified. It runs
an authenticated price API on port `8080`, separate from the OpenEPaperLink
admin UI on port `80`. A test tag was updated successfully through
`POST /price`. A temporary Cloudflare Quick Tunnel from a Windows computer was
tested. The planned production step is to move the tunnel to a Raspberry Pi
using a named Cloudflare Tunnel and stable hostname.

## Critical Rules

- The S3 API port is `8080`.
- Do not expose S3 port `80` publicly.
- Do not commit real bearer tokens or Cloudflare credentials.
- Use the S3 `COM` connector for this hardware setup.
- If the AP/radio link fails after reset, reset S3 first, then reset C6.
- Raspberry Pi work is planned future work unless a later note says it was
  completed.

## Before Pushing To Git

Run:

```powershell
git status --short
rg -n "token|password|passwd|secret|Authorization|Bearer|ssid|wifi|cloudflare|apiKey|apikey|key"
```

Review matches manually. Placeholder text is fine; real tokens, Wi-Fi
passwords, and Cloudflare credentials are not.
