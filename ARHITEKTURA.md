# ESL sistem — arhitektura

Dogovoreno 2026-08-12. Brojevi o skali dopunjeni i ispravljeni 2026-08-13.

> Ovo je zvanična kopija. Postoji i radna kopija na Desktopu vlasnika
> (`ESL-arhitektura.md`); izmene idu ovde, jer je ovo jedini dokument koji
> kaže koliko se opreme kupuje po radnji.

---

## Produkcija

```
┌─────────────────────────────────────────────────────────────┐
│                    GLAVNA BAZA (vaša)                       │
│         zajednička za online prodaju i za radnje            │
│         artikli, zalihe, cene, akcije, sve                  │
└──────────────────────────┬──────────────────────────────────┘
                           │  vi odlučujete šta ide na police
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              ESL API  (odvojen, samo za police)             │
│                                                             │
│   GET /prices?skus=...    -> cena po SKU-u                  │
│   autentifikacija:  API ključ                               │
│                                                             │
│   Izlaže SAMO ono što treba da se vidi na polici.           │
│   Ne izlaže zalihe, kupce, nabavne cene, ništa drugo.       │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────┴────────────┐   ...i tako za svaku radnju
              │                         │
              ▼                         ▼
     ╔═══════════════════╗     ╔═══════════════════╗
     ║   RADNJA 1        ║     ║   RADNJA 2        ║
     ║                   ║     ║                   ║
     ║  ┌─────────────┐  ║     ║  ┌─────────────┐  ║
     ║  │ Raspberry Pi│  ║     ║  │ Raspberry Pi│  ║
     ║  │             │  ║     ║  │             │  ║
     ║  │ 06:00 ujutru│  ║     ║  │ 06:00 ujutru│  ║
     ║  │ povuce cene │  ║     ║  │ povuce cene │  ║
     ║  │             │  ║     ║  │             │  ║
     ║  │ tag_mapping │  ║     ║  │ tag_mapping │  ║
     ║  │  SKU -> tag │  ║     ║  │  SKU -> tag │  ║
     ║  │ price_cache │  ║     ║  │ price_cache │  ║
     ║  │  sta je vec │  ║     ║  │  sta je vec │  ║
     ║  │  poslato    │  ║     ║  │  poslato    │  ║
     ║  └──────┬──────┘  ║     ║  └──────┬──────┘  ║
     ║         │         ║     ║         │         ║
     ║    ┌────▼────┐    ║     ║    ┌────▼────┐    ║
     ║    │ESP32-S3 │    ║     ║    │ESP32-S3 │    ║
     ║    │ slike   │    ║     ║    │ slike   │    ║
     ║    └────┬────┘    ║     ║    └────┬────┘    ║
     ║    ┌────▼────┐    ║     ║    ┌────▼────┐    ║
     ║    │ESP32-C6 │    ║     ║    │ESP32-C6 │    ║
     ║    │  radio  │    ║     ║    │  radio  │    ║
     ║    └────┬────┘    ║     ║    └────┬────┘    ║
     ║   ~~~~~~▼~~~~~~   ║     ║   ~~~~~~▼~~~~~~   ║
     ║   [tag][tag][tag] ║     ║   [tag][tag][tag] ║
     ╚═══════════════════╝     ╚═══════════════════╝
```

**Strelice idu samo nadole.** Ništa ne ulazi u radnju. Ruter u radnji ne treba
da propušta ništa spolja — nema domena, nema tunela, nema otvorenog porta.

---

## Zašto Pi povlači, a ne da baza gura (polling, ne webhook)

| | Webhook (baza zove Pi) | Polling (Pi zove bazu) |
|---|---|---|
| Ko inicira | baza | **Pi** |
| Pi mora biti dostupan spolja | da | **ne** |
| Treba domen / tunel / otvoren port | da | **ne** |
| Radi iza rutera radnje | samo uz tunel | **uvek** |
| Ako je Pi bio ugašen | izmena se **izgubi** | **sam se pokupi** |

Poslednji red je odlučujući. Kod webhooka, ako je Pi bio ugašen kad je cena
promenjena, taj poziv propada i cena ostaje stara zauvek. Kod pollinga, Pi na
sledećem ciklusu vidi razliku i ispravi se sam.

Isti razlog zbog kog Pi poredi sa `price_cache` (šta je stvarno poslato)
umesto sa `last_date_edited` (kad je nešto menjano).

---

## Danas vs. produkcija

```
DANAS (razvoj)                        PRODUKCIJA
─────────────────────────────────────────────────────────────
central_db.py na laptopu       ──►    vaš pravi ESL API
  100 lažnih proizvoda                 pravi katalog
  X-Api-Key: dev-mock-key              vaš ključ

Pi povlaci svakih 60s          ──►    Pi povlaci 06:00 ujutru

3 taga, 1 radnja               ──►    N tagova, N radnji

sve ostalo                     ──►    NEPROMENJENO
```

`central_db.py` nije prototip koji se baca — **on je maketa ugovora.** Namerno
govori isti HTTP jezik koji će govoriti pravi ESL API. Kad taj API postoji, na
Pi-ju se menjaju dve linije u `/etc/price-proxy.env`:

```
PACMS_BASE_URL=http://192.168.0.30:9000     ->   https://vas-esl-api...
PACMS_API_KEY=dev-mock-key                  ->   vas pravi kljuc
```

Gateway, mapiranje, keš, S3, C6, tagovi — ništa se ne dira.

---

## Dogovorene pretpostavke

1. **ESL API vraća cene po SKU-u**, na upit sa listom SKU-ova. Ne šalje nam
   sve — mi pitamo za ono što nam treba (~400 po radnji).

2. **Mapiranje SKU → tag živi na Pi-ju**, ne u glavnoj bazi. Glavna baza ne
   mora da zna da tagovi uopšte postoje; ona zna samo cene. Ko je zalepio koji
   tag na koju policu je lokalna stvar radnje.

3. **`price_cache` ostaje na Pi-ju.** Pi pamti šta je poslednji put stvarno
   poslao, pa jedno povlačenje ujutru šalje samo ono što se promenilo, a ne
   prepisuje svih 400 tagova svaki dan.

4. **Jedan Pi po radnji, i jedan S3.** Radnje su nezavisne, ne znaju jedna za
   drugu. *(ispravka 2026-08-13, kasnije istog dana)* Ranije je ovde pisalo da
   jedan S3 nosi najviše 255 tagova i da za 400 trebaju dva para — **to više
   ne važi.** Plafon je bio bug u firmveru, popravljen je i flešovan, i 408
   tagova je testirano na jednom S3. **Jedan par je dovoljan za radnju od 400
   tagova.**

5. **Cena je ista u svim radnjama.** *(odlučeno 2026-08-12)* ESL API zato
   **ne** treba parametar radnje — `GET /prices?skus=...` je dovoljno, bez
   `?store=`. Online cene se razlikuju od cena u radnjama, ali se povlače po
   drugoj logici iz glavne baze i nisu deo ovog sistema.

---

## Šta je od ovoga već potvrđeno na pravom hardveru

Testirano 2026-08-12, ceo lanac od baze do stakla:

- Promena cene kroz web stranicu → `pushed: 1, unchanged: 2, failed: 0`
- Cena na ekranu taga za ~20 sekundi
- Ponovljeni sync → `pushed: 0` (ne prepisuje bez potrebe)
- Automatski timer na 60s pokupio izmenu bez ijedne ručne komande

Potvrđene police: 1 (Bosch, 8499 RSD) i 2 (Makita, 5000 RSD).

---

## Izmereno na skali *(2026-08-13)*

Testirano sa sintetičkom bazom tagova, bez kupovine hardvera.

| šta | koliko |
|---|---|
| radio vreme po tagu | **3,9 s** |
| pun push na 400 tagova | **~26 min** |
| čekanje da se tag javi | 5–22 s |
| **tagova na jednom S3** | **408, testirano i stabilno** |
| memorija po tagu | 168 B iz PSRAM-a (408 tagova = 67 KB od 8 MB) |
| učitavanje baze cele radnje | 14,4 s |
| boot sa punom bazom | 6,8 s |

**Ništa ne blokira 400 tagova na jednom S3.** Ranije je izgledalo da je plafon
255, pa da radnji trebaju dva para — to je bio bug u firmveru, ne granica
hardvera. Popravljen je i flešovan istog dana.

**Radio nije usko grlo.** 26 minuta za svih 400 staje u jutarnji prozor bez
problema, a to je najgori slučaj koji se dešava samo pri prvoj postavci radnje
ili zameni AP-a. Normalno jutro šalje samo promenjene cene — desetak artikala,
minut posla.

**Šta i dalje nije izmereno:** kolizije. Kad se stotine pravih tagova probude
u istoj sekundi, dele isti radio kanal i ponavljaju slanje. Sintetički zapisi
ništa ne emituju, pa se to ne može simulirati — to je jedini preostali razlog
da se kupe tagovi pre nego što se fiksira raspored radnje.

Pokušali smo i obrnuto: poslati 400 ažuriranja u krug na tri prava taga.
**To ne daje odgovor o vremenu**, jer e-ink osvežavanje traje sekundama i tag
za to vreme ne prima novu sliku — u tom testu usko grlo su ta tri taga, ne
sistem. U radnji svaki tag radi jedno osvežavanje, a ne sto trideset. Broj od
26 minuta dolazi iz merenja jednog prenosa (3,9 s), pomnoženog sa 400.
