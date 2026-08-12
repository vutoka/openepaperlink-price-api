#!/usr/bin/env python3
"""Central product database for the ESL system.

This is the store-agnostic catalog that every store's Raspberry Pi pulls
prices from. It replaces the earlier in-memory `mock_pacms.py`: the data now
lives in SQLite and survives a restart, and there is a small web UI a shop
worker can use to change a price or a stock count.

Endpoints:

    GET  /api/Esl/Prices?skus=<sku1>,<sku2>,...
    GET  /api/Esl/Prices?since=<ISO8601>&page=<int>&size=<int>
    POST /api/Esl/Products/<sku>          -- worker edits price/stock
    POST /api/Esl/ShelfStatus             -- a store reports what its shelves show
    GET  /api/Esl/ShelfStatus             -- read those reports back
    GET  /health

A product carries **one** price: the number to print on the shelf. Resolving
promotions is the catalog's job, not the ESL system's, so there is no separate
sale price to choose between.

`ShelfStatus` is what makes an undelivered price visible. The store posts it
after every sync -- outbound, so nothing ever calls into the store -- and the
worker page colours a row red when a price it set never reached the glass.

Machine access authenticates with a shared `X-Api-Key` header, the same way
PACMS API keys work. The worker UI at `/` asks for that key once and keeps it
in sessionStorage; the key is never baked into the served page.

Run it on whatever host holds the catalog -- deliberately *not* on the Pi, so
the Pi exercises a real network path:

    python tools/central_db.py --seed      # first run, creates + fills the DB
    python tools/central_db.py             # afterwards
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sqlite3
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

LISTEN_HOST = os.getenv("CENTRAL_DB_LISTEN", "0.0.0.0")
LISTEN_PORT = int(os.getenv("CENTRAL_DB_PORT", "9000"))
API_KEY = os.getenv("CENTRAL_DB_API_KEY", "dev-mock-key")
DB_PATH = os.getenv("CENTRAL_DB_PATH", os.path.join(os.path.dirname(__file__), "central.db"))
DEFAULT_PAGE_SIZE = 1000

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY,
    sku         TEXT NOT NULL UNIQUE,
    barcode     TEXT NOT NULL,
    title       TEXT NOT NULL,
    price       REAL NOT NULL,
    sale_price  REAL,
    stock       INTEGER NOT NULL DEFAULT 0,
    modified_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_products_modified_at ON products (modified_at);

-- What each store reports back about its shelves. Written by POST
-- /api/Esl/ShelfStatus, read by the worker page so a price that never reached
-- the glass shows up red instead of being assumed good.
CREATE TABLE IF NOT EXISTS shelf_status (
    sku          TEXT NOT NULL,
    tag_mac      TEXT NOT NULL DEFAULT '',
    store        TEXT NOT NULL DEFAULT 'default',
    state        TEXT NOT NULL,
    wanted_price REAL,
    shelf_price  REAL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    detail       TEXT,
    reported_at  TEXT NOT NULL,
    PRIMARY KEY (sku, tag_mac)
);
"""

# `products.sale_price` is vestigial. An earlier version of this mock modelled
# a separate promotional price, but the real catalog resolves promotions itself
# and hands the ESL system one number: the price to print on the shelf. The
# column is left in place so existing seeded databases still open; nothing
# reads it and the API does not expose it.


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_since(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    try:
        conn.execute("ALTER TABLE shelf_status ADD COLUMN store TEXT NOT NULL DEFAULT 'default'")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # already there
    return conn


def ean13(body12: str) -> str:
    """Append the EAN-13 check digit to a 12-digit body."""
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body12))
    return body12 + str((10 - total % 10) % 10)


# (sku, title, price, sale_price, stock). Barcodes for the first five are the
# real ones carried over from the previous mock; the rest are generated.
SEED_PRODUCTS: list[tuple[str, str, float, float | None, int]] = [
    ("BOSCH-GSB13RE", "Bosch GSB 13 RE udarna busilica 600W", 8990.0, None, 12),
    ("MAK-9558NB", "Makita 9558NB ugaona brusilica 125mm", 7490.0, 6490.0, 5),
    ("DEWALT-DCD778", "DeWalt DCD778 akumulatorska busilica 18V", 15990.0, None, 3),
    ("STANLEY-FMHT1", "Stanley FatMax metar 5m", 1290.0, None, 40),
    ("BOSCH-PST700", "Bosch PST 700 E ubodna testera", 6290.0, 5490.0, 8),
    # --- elektricni alat ---
    ("BOSCH-GSR120", "Bosch GSR 120-LI akumulatorska busilica 12V", 11990.0, None, 9),
    ("BOSCH-GWS750", "Bosch GWS 750-125 ugaona brusilica 750W", 9490.0, 8490.0, 14),
    ("BOSCH-GBH2400", "Bosch GBH 2-24 D elektropneumatski cekic", 21990.0, None, 4),
    ("BOSCH-GST90", "Bosch GST 90 E ubodna testera 650W", 12490.0, None, 6),
    ("BOSCH-GKS190", "Bosch GKS 190 kruzna testera 1400W", 14990.0, 13490.0, 5),
    ("BOSCH-PMF220", "Bosch PMF 220 CE multifunkcionalni alat", 11990.0, None, 5),
    ("BOSCH-PEX400", "Bosch PEX 400 AE ekscentar brusilica", 10990.0, None, 4),
    ("MAK-HP1631", "Makita HP1631K udarna busilica 710W", 9990.0, None, 11),
    ("MAK-DF333D", "Makita DF333DWAE akumulatorska busilica 12V", 16990.0, None, 7),
    ("MAK-GA5030", "Makita GA5030 ugaona brusilica 125mm 720W", 8290.0, None, 16),
    ("MAK-HR2470", "Makita HR2470 elektropneumatski cekic 780W", 23490.0, 21990.0, 3),
    ("MAK-4329", "Makita 4329 ubodna testera 450W", 8990.0, None, 8),
    ("DEWALT-DWE4157", "DeWalt DWE4157 ugaona brusilica 125mm", 10990.0, None, 6),
    ("DEWALT-DCF887", "DeWalt DCF887 udarni odvijac 18V", 24990.0, None, 2),
    ("DEWALT-D25133", "DeWalt D25133K elektropneumatski cekic", 27990.0, 25990.0, 3),
    ("MILW-M18BLPD2", "Milwaukee M18 BLPD2 udarna busilica 18V", 32990.0, None, 2),
    ("MILW-M12BID", "Milwaukee M12 BID udarni odvijac 12V", 18990.0, None, 4),
    ("METABO-SBE650", "Metabo SBE 650 udarna busilica", 11490.0, None, 5),
    ("METABO-W850", "Metabo W 850-125 ugaona brusilica", 12990.0, 11490.0, 4),
    ("EINHELL-TCID720", "Einhell TC-ID 720/1 E udarna busilica", 4990.0, None, 22),
    ("EINHELL-TEAG18", "Einhell TE-AG 18 aku ugaona brusilica 18V", 13990.0, None, 6),
    ("VILLAGER-VLN1400", "Villager VLN 1400 kruzna testera", 7990.0, 6990.0, 9),
    # --- rucni alat ---
    ("STANLEY-FMHT8", "Stanley FatMax metar 8m", 1890.0, None, 35),
    ("STANLEY-STHT0", "Stanley cekic stolarski 500g", 1490.0, None, 28),
    ("STANLEY-KNIFE", "Stanley FatMax skalpel sa fiksnim secivom", 1190.0, None, 45),
    ("STANLEY-LEVEL60", "Stanley libela aluminijumska 600mm", 1990.0, None, 24),
    ("STANLEY-TOOLBOX", "Stanley kutija za alat 19 inca", 2490.0, 2190.0, 15),
    ("STANLEY-ORGANIZER", "Stanley organizator sa 25 pregrada", 1990.0, None, 20),
    ("UNIOR-KLJUC17", "Unior viljuskasto-okasti kljuc 17mm", 690.0, None, 60),
    ("UNIOR-SET12", "Unior set viljuskasto-okastih kljuceva 12 kom", 6990.0, None, 12),
    ("UNIOR-KLESTA", "Unior kombinovana klesta 180mm", 1290.0, None, 32),
    ("UNIOR-ODVIJAC", "Unior set odvijaca 6 kom", 2290.0, 1990.0, 18),
    ("KNIPEX-COBRA", "Knipex Cobra vodoinstalaterska klesta 250mm", 5490.0, None, 8),
    ("KNIPEX-SEC160", "Knipex bocne secice 160mm", 4290.0, None, 10),
    ("WERA-KRAFT", "Wera Kraftform set odvijaca 7 kom", 6990.0, None, 6),
    ("GEDORE-KLJUC19", "Gedore nasadni kljuc 1/2 inca 19mm", 890.0, None, 40),
    ("FORCE-GEDORA24", "Force gedora set 1/2 inca 24 kom", 8990.0, 7990.0, 7),
    ("TOTAL-CEKIC", "Total cekic gumeni 450g", 890.0, None, 30),
    ("INGCO-LOPATA", "Ingco lopata gradjevinska", 1290.0, None, 25),
    # --- merni alat ---
    ("BOSCH-GLM50", "Bosch GLM 50-27 C laserski daljinomer", 15990.0, None, 4),
    ("BOSCH-GLL2", "Bosch GLL 2-15 G linijski laser zeleni", 24990.0, 22990.0, 2),
    ("STANLEY-STHT77", "Stanley laserski daljinomer 30m", 8990.0, None, 5),
    ("TOTAL-LIBELA", "Total libela 1000mm", 2290.0, None, 14),
    ("INGCO-METAR3", "Ingco metar 3m", 490.0, None, 80),
    ("FLUKE-101", "Fluke 101 digitalni multimetar", 8990.0, None, 6),
    ("INGCO-DETEKTOR", "Ingco detektor napona", 1190.0, None, 26),
    # --- potrosni materijal ---
    ("BOSCH-BURGIJE19", "Bosch set burgija za metal HSS 19 kom", 2990.0, None, 25),
    ("BOSCH-DISK125", "Bosch disk za secenje metala 125mm 10 kom", 1490.0, None, 50),
    ("BOSCH-DISK230", "Bosch disk za secenje metala 230mm 5 kom", 1890.0, None, 30),
    ("BOSCH-SDS8", "Bosch SDS-plus burgija 8x160mm", 690.0, None, 45),
    ("MAK-LISTOVI", "Makita listovi za ubodnu testeru drvo 5 kom", 990.0, None, 38),
    ("DEWALT-BITSET32", "DeWalt set bitova 32 kom", 2490.0, 2190.0, 20),
    ("TOTAL-BRUSPAPIR", "Total brusni papir set 100 kom", 1290.0, None, 42),
    ("INGCO-SAJLA5", "Ingco sajla za odgusivanje 5m", 1990.0, None, 12),
    # --- zastitna oprema ---
    ("3M-FFP2", "3M zastitna maska FFP2 10 kom", 1490.0, None, 60),
    ("3M-NAOCARE", "3M zastitne naocare providne", 890.0, None, 55),
    ("UVEX-RUKAVICE10", "Uvex radne rukavice nitril vel. 10", 690.0, None, 70),
    ("PORTWEST-PRSLUK", "Portwest reflektujuci prsluk zuti", 790.0, None, 48),
    ("PORTWEST-SLEM", "Portwest zastitni slem beli", 1590.0, None, 22),
    ("JORI-CIZME43", "Jori zastitne cipele S3 vel. 43", 6990.0, 5990.0, 9),
    ("GYS-MASKA", "GYS automatska maska za varenje", 5990.0, None, 8),
    # --- basta i spoljasnjost ---
    ("VILLAGER-VBC260", "Villager VBC 260 benzinski trimer", 18990.0, None, 5),
    ("VILLAGER-VLS38", "Villager VLS 38 motorna testera", 24990.0, 22990.0, 3),
    ("BOSCH-ART26", "Bosch ART 26 SL elektricni trimer", 7990.0, None, 8),
    ("EINHELL-GCEM1030", "Einhell GC-EM 1030 elektricna kosilica", 12990.0, None, 4),
    ("GARDENA-CREVO20", "Gardena bastensko crevo 20m", 4990.0, None, 11),
    # --- elektro i vodovod ---
    ("INGCO-KABL20", "Ingco produzni kabl 20m", 3490.0, 2990.0, 13),
    ("SCHNEIDER-PREKIDAC", "Schneider prekidac jednopolni beli", 390.0, None, 90),
    ("SCHNEIDER-UTICNICA", "Schneider uticnica suko bela", 490.0, None, 85),
    ("PVC-CEV32", "PVC kanalizaciona cev 32mm 2m", 590.0, None, 40),
    ("PVC-KOLENO32", "PVC koleno 32mm 90 stepeni", 120.0, None, 120),
    # --- vezni materijal ---
    ("VIJAK-4X40", "Vijak za drvo 4x40mm 200 kom", 890.0, None, 55),
    ("VIJAK-6X80", "Vijak za drvo 6x80mm 100 kom", 1190.0, None, 38),
    ("TIPL-8", "Tipl univerzalni 8mm 100 kom", 590.0, None, 65),
    ("NAVRTKA-M8", "Navrtka M8 pocinkovana 50 kom", 390.0, None, 72),
    ("EKSER-50", "Ekser gradjevinski 50mm 1kg", 490.0, None, 44),
    # --- hemija i lepkovi ---
    ("PATTEX-LEPAK", "Pattex univerzalni lepak 100ml", 690.0, None, 33),
    ("SIKA-SILIKON", "Sika sanitarni silikon beli 300ml", 890.0, None, 40),
    ("WD40-SPREJ", "WD-40 multi sprej 400ml", 990.0, None, 52),
    ("HENKEL-PENA", "Henkel PU pena za montazu 750ml", 1290.0, 1090.0, 28),
    ("JUB-JUPOL15", "JUB Jupol Classic beli 15L", 4990.0, None, 16),
    # --- baterije i punjaci ---
    ("MAK-BL1830", "Makita BL1830B baterija 18V 3.0Ah", 12990.0, None, 7),
    ("MAK-DC18RC", "Makita DC18RC brzi punjac", 8990.0, None, 5),
    ("DEWALT-DCB184", "DeWalt DCB184 baterija 18V 5.0Ah", 16990.0, 14990.0, 4),
    ("BOSCH-GBA18", "Bosch GBA 18V 4.0Ah baterija", 13990.0, None, 6),
    ("MILW-M18B5", "Milwaukee M18 B5 baterija 5.0Ah", 19990.0, None, 3),
    # --- kompresori i varenje ---
    ("EINHELL-TCAC190", "Einhell TC-AC 190/24 kompresor", 15990.0, None, 3),
    ("VILLAGER-VIWM160", "Villager VIWM 160 inverter aparat za varenje", 17990.0, 15990.0, 4),
    ("ELEKTRODE-25", "Elektrode za varenje 2.5mm 5kg", 2490.0, None, 18),
    # --- ostalo ---
    ("TOTAL-KOLICA3", "Total kolica za alat 3 fioke", 24990.0, None, 2),
    ("INGCO-TORBA16", "Ingco torba za alat 16 inca", 2990.0, 2490.0, 14),
    ("MAK-VC2512L", "Makita VC2512L usisivac za suvo i mokro", 22990.0, None, 3),
    ("KARCHER-WD3", "Karcher WD 3 usisivac 17L", 13990.0, None, 6),
    ("KARCHER-K5", "Karcher K5 Power Control perac pod pritiskom", 39990.0, 35990.0, 2),
    ("ALU-MERDEVINE5", "Merdevine aluminijumske 5 stepenika", 6990.0, None, 7),
]

REAL_BARCODES = {
    "BOSCH-GSB13RE": "3165140617703",
    "MAK-9558NB": "0088381727450",
    "DEWALT-DCD778": "5035048729414",
    "STANLEY-FMHT1": "3253560016114",
    "BOSCH-PST700": "3165140581905",
}


def seed(conn: sqlite3.Connection) -> int:
    """Insert the seed catalog. Existing rows are left untouched."""
    stamp = now_iso()
    inserted = 0
    for index, (sku, title, price, sale_price, stock) in enumerate(SEED_PRODUCTS, start=1):
        barcode = REAL_BARCODES.get(sku) or ean13(f"860{index:09d}")
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO products
                (sku, barcode, title, price, sale_price, stock, modified_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (sku, barcode, title, price, sale_price, stock, stamp),
        )
        inserted += cursor.rowcount
    conn.commit()
    return inserted


def serialize(row: sqlite3.Row) -> dict[str, Any]:
    """One product, exactly as the ESL system is expected to receive it.

    `price` is the number that goes on the shelf, already resolved -- the
    catalog decides whether that is a regular or a promotional price, and the
    ESL system never has to choose between two figures.
    """
    return {
        "id": row["id"],
        "sku": row["sku"],
        "barcode": row["barcode"],
        "title": row["title"],
        "price": row["price"],
        "stock": row["stock"],
        "modifiedAt": row["modified_at"],
    }


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


WORKER_PAGE = """<!doctype html>
<html lang="sr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Centralna baza proizvoda</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; margin: 0; padding: 1.5rem; }
  h1 { font-size: 1.25rem; margin: 0 0 1rem; }
  #bar { display: flex; gap: .5rem; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; }
  input, button { font: inherit; padding: .4rem .6rem; }
  #search { flex: 1; min-width: 12rem; }
  .wrap { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; min-width: 46rem; }
  th, td { text-align: left; padding: .45rem .6rem; border-bottom: 1px solid #8883; white-space: nowrap; }
  th { position: sticky; top: 0; background: Canvas; }
  td.num input { width: 7rem; text-align: right; }
  td.title { white-space: normal; min-width: 18rem; }
  tr.saved { background: #22c55e22; }
  tr.failed { background: #ef444422; }
  #msg { margin-left: auto; opacity: .75; }

  /* Shelf state, as reported by the store. The point of this column is that a
     price which never reached the glass is visible, not assumed. */
  .pill { display: inline-block; padding: .1rem .5rem; border-radius: 999px;
          font-size: .8rem; white-space: nowrap; }
  .pill.on_shelf    { background: #22c55e33; color: #15803d; }
  .pill.in_flight   { background: #eab30833; color: #a16207; }
  .pill.undelivered { background: #ef444433; color: #b91c1c; font-weight: 600; }
  .pill.no_tag      { background: #8881; opacity: .8; }
  .pill.unknown     { background: #8881; opacity: .6; }
  tr.alert { background: #ef44441a; }
  @media (prefers-color-scheme: dark) {
    .pill.on_shelf    { color: #4ade80; }
    .pill.in_flight   { color: #fcd34d; }
    .pill.undelivered { color: #fca5a5; }
  }
</style>
</head>
<body>
<h1>Centralna baza proizvoda</h1>
<div id="bar">
  <input id="search" placeholder="Pretraga po SKU, nazivu ili barkodu">
  <button id="reload">Osvezi</button>
  <span id="msg"></span>
</div>
<div class="wrap">
  <table>
    <thead>
      <tr><th>ID</th><th>SKU</th><th>Naziv</th><th>Cena</th><th>Polica</th><th>Kolicina</th><th>Izmenjeno</th><th></th></tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>
</div>
<script>
const $ = (s) => document.querySelector(s);
let products = [];
let shelves = {};   // sku -> latest status reported by the store

const LABEL = {
  on_shelf:    "na polici",
  in_flight:   "salje se",
  undelivered: "NIJE STIGLO",
  no_tag:      "nema taga",
  unknown:     "-",
};

function ago(seconds) {
  if (seconds == null) return "";
  if (seconds < 90) return seconds + "s";
  if (seconds < 5400) return Math.round(seconds / 60) + " min";
  return Math.round(seconds / 3600) + " h";
}

function shelfCell(sku) {
  const s = shelves[sku];
  if (!s) return '<span class="pill unknown">-</span>';
  const state = s.state || "unknown";
  let note = "";
  if (state === "undelivered") {
    const d = s.detail || {};
    const bits = [];
    if (s.attempts) bits.push(s.attempts + " pokusaja");
    if (d.last_error) bits.push(d.last_error);
    else if (d.tag_last_seen_seconds != null) bits.push("tag " + ago(d.tag_last_seen_seconds) + " nije javio");
    if (d.tag_battery_mv != null && d.tag_battery_mv < 2450) bits.push("baterija " + d.tag_battery_mv + "mV");
    if (s.shelfPrice != null) bits.push("na staklu " + s.shelfPrice);
    note = bits.length ? ' <small>' + bits.join(", ") + '</small>' : "";
  } else if (state === "in_flight") {
    const d = s.detail || {};
    if (d.waiting_seconds) note = ' <small>' + ago(d.waiting_seconds) + '</small>';
  }
  return '<span class="pill ' + state + '">' + (LABEL[state] || state) + "</span>" + note;
}

function apiKey() {
  let k = sessionStorage.getItem("apiKey");
  if (!k) {
    k = prompt("X-Api-Key za centralnu bazu:") || "";
    sessionStorage.setItem("apiKey", k);
  }
  return k;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { ...(options.headers || {}), "X-Api-Key": apiKey() },
  });
  if (res.status === 401) {
    sessionStorage.removeItem("apiKey");
    throw new Error("Pogresan API kljuc - osvezi stranicu");
  }
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

function render() {
  const q = $("#search").value.trim().toLowerCase();
  const shown = q
    ? products.filter((p) =>
        (p.sku + " " + p.title + " " + p.barcode).toLowerCase().includes(q))
    : products;
  $("#rows").innerHTML = shown.map((p) => {
    const s = shelves[p.sku];
    const alert = s && s.state === "undelivered" ? " class=\\"alert\\"" : "";
    return `
    <tr data-sku="${p.sku}"${alert}>
      <td>${p.id}</td>
      <td>${p.sku}</td>
      <td class="title">${p.title}</td>
      <td class="num"><input type="number" step="0.01" class="price" value="${p.price}"></td>
      <td>${shelfCell(p.sku)}</td>
      <td class="num"><input type="number" step="1" class="stock" value="${p.stock}"></td>
      <td>${p.modifiedAt.replace("T", " ").replace("Z", "")}</td>
      <td><button class="save">Sacuvaj</button></td>
    </tr>`;
  }).join("");

  const bad = Object.values(shelves).filter((s) => s.state === "undelivered").length;
  $("#msg").textContent = shown.length + " / " + products.length + " proizvoda"
    + (bad ? "  -  " + bad + " cena NIJE stigla na policu" : "");
  $("#msg").style.color = bad ? "#ef4444" : "";
}

async function loadShelves() {
  try {
    const rows = await api("/api/Esl/ShelfStatus");
    shelves = {};
    for (const r of rows) shelves[r.sku] = r;
  } catch (e) {
    // Status is advisory; never let it stop the catalog from being editable.
  }
}

async function load() {
  try {
    products = await api("/api/Esl/Prices");
    await loadShelves();
    render();
  } catch (e) {
    $("#msg").textContent = e.message;
  }
}

// The store reports after every sync, so refresh the colours on their own
// without making the worker press anything.
setInterval(async () => {
  if (document.hidden) return;
  await loadShelves();
  render();
}, 20000);

$("#rows").addEventListener("click", async (ev) => {
  if (!ev.target.classList.contains("save")) return;
  const tr = ev.target.closest("tr");
  const body = {
    price: Number(tr.querySelector(".price").value),
    stock: Number(tr.querySelector(".stock").value),
  };
  tr.className = "";
  try {
    const res = await api("/api/Esl/Products/" + encodeURIComponent(tr.dataset.sku), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const i = products.findIndex((p) => p.sku === res.updated.sku);
    if (i >= 0) products[i] = res.updated;
    tr.className = "saved";
    tr.querySelector("td:nth-child(7)").textContent =
      res.updated.modifiedAt.replace("T", " ").replace("Z", "");
  } catch (e) {
    tr.className = "failed";
    $("#msg").textContent = e.message;
  }
});

$("#search").addEventListener("input", render);
$("#reload").addEventListener("click", load);
load();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "CentralDB/1.0"

    def authenticate(self) -> None:
        supplied = self.headers.get("X-Api-Key", "")
        if not secrets.compare_digest(supplied, API_KEY):
            raise ApiError(401, "missing or invalid X-Api-Key")

    def send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, status: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ApiError(400, "invalid Content-Length") from exc
        if length <= 0:
            raise ApiError(400, "request body is required")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(400, "request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ApiError(400, "request body must be a JSON object")
        return payload

    def handle_list_prices(self, query: dict[str, list[str]]) -> None:
        conn = connect()
        try:
            rows = conn.execute("SELECT * FROM products ORDER BY modified_at, id").fetchall()
        finally:
            conn.close()

        records = [serialize(row) for row in rows]

        if "skus" in query:
            wanted = {s.strip() for s in query["skus"][0].split(",") if s.strip()}
            records = [r for r in records if r["sku"] in wanted]

        if "since" in query:
            try:
                since = parse_since(query["since"][0])
            except ValueError as exc:
                raise ApiError(400, "since must be ISO8601") from exc
            records = [r for r in records if parse_since(r["modifiedAt"]) > since]

        try:
            page = int(query.get("page", ["0"])[0])
            size = int(query.get("size", [str(DEFAULT_PAGE_SIZE)])[0])
        except ValueError as exc:
            raise ApiError(400, "page and size must be integers") from exc
        start = page * size

        self.send_json(200, records[start : start + size])

    def handle_update_product(self, sku: str) -> None:
        payload = self.read_json_body()
        conn = connect()
        try:
            row = conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
            if row is None:
                raise ApiError(404, f"unknown sku: {sku!r}")

            price = row["price"]
            stock = row["stock"]
            try:
                if "price" in payload:
                    price = float(payload["price"])
                if "stock" in payload:
                    stock = int(payload["stock"])
            except (TypeError, ValueError) as exc:
                raise ApiError(400, "price must be a number and stock an integer") from exc

            if price <= 0:
                raise ApiError(400, "price must be greater than zero")
            if stock < 0:
                raise ApiError(400, "stock cannot be negative")

            conn.execute(
                """
                UPDATE products
                   SET price = ?, stock = ?, modified_at = ?
                 WHERE sku = ?
                """,
                (price, stock, now_iso(), sku),
            )
            conn.commit()
            updated = serialize(conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone())
        finally:
            conn.close()

        self.send_json(200, {"ok": True, "updated": updated})

    def handle_report_shelf_status(self) -> None:
        """A store reporting what its shelves actually show.

        The store calls us; we never call the store. Rows are keyed by
        (sku, tag_mac) and simply overwritten, so the latest report wins and
        the table never grows beyond the number of tags in the field.
        """
        payload = self.read_json_body()
        shelves = payload.get("shelves")
        if not isinstance(shelves, list):
            raise ApiError(400, "shelves must be a list")
        stamp = payload.get("reported_at") or now_iso()
        store = str(payload.get("store") or "default")

        conn = connect()
        try:
            # The report is this store's complete picture, so anything it no
            # longer mentions is gone -- a retired tag must not keep showing a
            # stale red, or the colour stops meaning anything.
            keep = {
                (str(e["sku"]), str(e.get("tag_mac") or ""))
                for e in shelves
                if isinstance(e, dict) and e.get("sku")
            }
            for sku, mac in conn.execute(
                "SELECT sku, tag_mac FROM shelf_status WHERE store = ?", (store,)
            ).fetchall():
                if (sku, mac) not in keep:
                    conn.execute(
                        "DELETE FROM shelf_status WHERE store = ? AND sku = ? AND tag_mac = ?",
                        (store, sku, mac),
                    )

            for entry in shelves:
                if not isinstance(entry, dict) or not entry.get("sku"):
                    continue
                conn.execute(
                    """
                    INSERT INTO shelf_status (sku, tag_mac, store, state, wanted_price,
                                              shelf_price, attempts, detail, reported_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(sku, tag_mac) DO UPDATE SET
                        store        = excluded.store,
                        state        = excluded.state,
                        wanted_price = excluded.wanted_price,
                        shelf_price  = excluded.shelf_price,
                        attempts     = excluded.attempts,
                        detail       = excluded.detail,
                        reported_at  = excluded.reported_at
                    """,
                    (
                        str(entry["sku"]),
                        str(entry.get("tag_mac") or ""),
                        store,
                        str(entry.get("state") or "unknown"),
                        entry.get("wanted_price"),
                        entry.get("shelf_price"),
                        int(entry.get("attempts") or 0),
                        json.dumps(
                            {
                                "waiting_seconds": entry.get("waiting_seconds"),
                                "tag_last_seen_seconds": entry.get("tag_last_seen_seconds"),
                                "tag_battery_mv": entry.get("tag_battery_mv"),
                                "last_error": entry.get("last_error"),
                            }
                        ),
                        stamp,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

        self.send_json(200, {"ok": True, "received": len(shelves)})

    def handle_list_shelf_status(self) -> None:
        conn = connect()
        try:
            rows = conn.execute("SELECT * FROM shelf_status").fetchall()
        finally:
            conn.close()
        self.send_json(
            200,
            [
                {
                    "sku": r["sku"],
                    "tagMac": r["tag_mac"],
                    "state": r["state"],
                    "wantedPrice": r["wanted_price"],
                    "shelfPrice": r["shelf_price"],
                    "attempts": r["attempts"],
                    "detail": json.loads(r["detail"]) if r["detail"] else {},
                    "reportedAt": r["reported_at"],
                }
                for r in rows
            ],
        )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/":
                # The shell loads without a key; every data call from it is authenticated.
                self.send_html(200, WORKER_PAGE)
                return
            self.authenticate()
            if parsed.path == "/health":
                conn = connect()
                try:
                    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
                finally:
                    conn.close()
                self.send_json(200, {"ok": True, "service": "central-db", "products": count})
            elif parsed.path == "/api/Esl/Prices":
                self.handle_list_prices(query)
            elif parsed.path == "/api/Esl/ShelfStatus":
                self.handle_list_shelf_status()
            else:
                raise ApiError(404, "endpoint not found")
        except ApiError as exc:
            self.send_json(exc.status, {"ok": False, "error": exc.message})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            self.authenticate()
            if parsed.path.startswith("/api/Esl/Products/"):
                sku = unquote(parsed.path[len("/api/Esl/Products/") :])
                if not sku:
                    raise ApiError(400, "sku is required in the path")
                self.handle_update_product(sku)
            elif parsed.path == "/api/Esl/ShelfStatus":
                self.handle_report_shelf_status()
            elif parsed.path == "/api/Esl/_mock/set-price":
                # Kept so older notes and scripts that used the mock still work.
                payload = self.read_json_body()
                sku = payload.get("sku")
                if not sku:
                    raise ApiError(400, "sku is required")
                self.handle_update_product(sku)
            else:
                raise ApiError(404, "endpoint not found")
        except ApiError as exc:
            self.send_json(exc.status, {"ok": False, "error": exc.message})

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(f"{self.client_address[0]} - {format % args}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="store_true", help="fill the catalog before serving")
    parser.add_argument("--seed-only", action="store_true", help="fill the catalog and exit")
    args = parser.parse_args()

    if args.seed or args.seed_only:
        conn = connect()
        try:
            inserted = seed(conn)
            total = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        finally:
            conn.close()
        print(f"seeded {inserted} new product(s); catalog now holds {total}")
        if args.seed_only:
            return

    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(f"central DB listening on http://{LISTEN_HOST}:{LISTEN_PORT}")
    print(f"database: {DB_PATH}")
    print(f"X-Api-Key: {API_KEY}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
