# Hagur – spurðu um hagtölur

A chatbot that answers everyday questions about Icelandic official statistics, built for the
**Statistics Iceland AI Gagnaþon 2026 (Track 1 – Prepared RAG)**.

Ask in Icelandic or English. Hagur finds the exact figures in Statistics Iceland's data, checks them,
and answers in Icelandic with the **numbers, units and source**.

> „Hvað fluttu margar konur og karlar frá Norðurlandi til höfuðborgarinnar árið 2024?“
>
> **Árið 2024 fluttu 777 manns frá Norðurlandi (eystra og vestra samanlagt) til höfuðborgarsvæðisins, þar af 402 karlar og 375 konur.**
> *Heimild: Hagstofa Íslands – Búferlaflutningar milli landsvæða, til höfuðborgarsvæðisins*

---

## What it can answer

| Topic | Coverage | Table | Example |
|---|---|---|---|
| **Migration between regions**, by sex | 1986–2025 | MAN01002 | „Hvað fluttu margir frá höfuðborgarsvæðinu til Suðurlands 2024?“ |
| **Migration to and from Iceland**, by citizenship | 1961–2025 | MAN01400 | „Hversu margir erlendir ríkisborgarar fluttu til landsins 2024?“ |
| **Population** by municipality and region, by sex | 1998–2026 | MAN02005, MAN03250 | „Hvað búa margir á Akureyri?“ |
| **Population of Iceland** | 1703–2026 | MAN00000 | „Hver var mannfjöldi á Íslandi árið 1900?“ |
| **Births** and **deaths** | 1951–2025, 1841–2025 | MAN05100, MAN05210 | „Hvað fæddust mörg börn árið 2024?“ |
| **Unemployment**, by sex, age and area | 2003–2025 | VIN00921 | „Hvert var atvinnuleysi 2024?“ |
| **Wages**, by occupation, sector and sex | 2014–2025 | VIN02002 | „Hver voru meðallaun 2024?“ |
| **GDP**, national income, consumption, trade | 1995–2025 | THJ01102 | „Hver var landsframleiðslan 2023?“ |
| **GDP per capita** | 1980–2024 | THJ01401 | „Hver var landsframleiðsla á mann 2023?“ |
| **Overnight stays and arrivals**, by region and month | 1998–2026 | SAM01601 | „Hvað voru margar gistinætur 2024?“ |
| **Passengers through Keflavík airport** | 2002–2026 | SAM02001 | „Hvað fóru margir farþegar um Keflavíkurflugvöll í júlí 2025?“ |
| **Consumer price index** (base 1988 = 100) and inflation, monthly | Dec 1999 – Jul 2026 | VIS01002 | „Hver var vísitala neysluverðs í júní 2024?“ |

Without a year, the population, unemployment, wage and similar tables answer for the latest year and say which.
Migration questions and the price index ask back if the year, region or month is missing. You can then just answer, e.g. „2014“.
Questions outside the data get an honest „I don't have data on that“.

## How it works

```
Browser (index.html)
   │  POST /spyrja  {"spurning": "..."}
   ▼
FastAPI (app.py)
   ├─ Price index  → cached Excel table (VIS01002) in RAM
   ├─ Migration    → table MAN01002 from SQLite, in RAM
   ├─ Anything else → ChromaDB vector search (BGE-M3) plus keywords find the right table,
   │                  then its labels (year, place, sex...) are matched to the question
   │                  and the exact figure is read from SQLite (gagnaleit.py)
   ├─ Builds a short, exact fact text with the figures
   ▼
Ollama (llama3) words the answer in Icelandic
   ▼
Number check: if the model adds, drops or changes a number, or drops the destination,
its text is rejected and the verified fact text is returned instead.
   ▼
{"svar": "...", "heimildir": ["Hagstofa Íslands – ..."]}
```

The language model **never decides the numbers**: it only rewords figures that were already
looked up and verified.

---

## Setup (Windows)

Requirements: **Python 3.10+**, **Git**, about **10 GB** free disk (models).

### 1. Get the code
```powershell
git clone https://github.com/Auddi04/Gagnathon-2026.git
cd Gagnathon-2026
```

### 2. Python environment
```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements_file.txt
```

### 3. Ollama (local language model)
Install from https://ollama.com (or `irm https://ollama.com/install.ps1 | iex`), then:
```powershell
ollama pull llama3
```
Ollama runs in the background after installing. If it doesn't, run `ollama serve` in a separate terminal.

### 4. Refresh the database (optional)
```powershell
python ingest.py
```
You can skip this: `gogn/hagstofa.db` comes with the code. Running it downloads the latest figures for the tables
in `toflur.py` from Statistics Iceland's PX API.
The Google Drive database from `README Track_1.md` is no longer needed.

### 5. Run
```powershell
uvicorn app:app --reload
```
The first start downloads the BGE-M3 embedding model (~2 GB) and takes a few minutes.
Wait for `Application startup complete.`, then open **http://127.0.0.1:8000**.

*Mac/Linux:* same steps, but activate with `source venv/bin/activate`.

---

## Testing

**In the browser:** open http://127.0.0.1:8000 and click an example question.

**API directly** (interactive docs at http://127.0.0.1:8000/docs):
```powershell
curl.exe -X POST "http://127.0.0.1:8000/spyrja" -H "Content-Type: application/json" -d '{\"spurning\": \"Hvað fluttu margir frá Austurlandi 2015?\"}'
```

**Automatic test set:** questions whose correct answers were checked directly against Statistics Iceland's
PX API and the Excel file. With the server running, in a second terminal:
```powershell
python test_spurningar.py
```
It prints ✅/❌ per question with response time and saves a table to `nidurstodur_profana.md`.

---

## Adding a table

1. Add an entry to `TOFLUR` in `toflur.py` (its table ID, path, description and search words; the fields are explained at the top of the file).
2. Run `python ingest.py <table ID>` and restart the server.
3. Add a question with a verified answer to `test_spurningar.py`.

## Known limitations

- **Each question stands on its own.** Hagur remembers a question only when it has asked back
  (e.g. „Hvaða ár?“). „En 2016?“ after an answer does not work.
- **All ages combined.** Population, migration and death figures are stored for all ages only, to keep the database small.
- **Price index needs a month.** „Vísitalan 2020“ without a month is not answered.
- **Word matching.** Unusual phrasing or misspelled place names may not be understood. A place is only noticed as
  unknown if it starts with a capital letter, so a lowercase unknown place can get the figure for the whole country,
  which the answer labels without a place name.
- **Towns are answered by municipality.** „Selfoss“ gives Sveitarfélagið Árborg, and the answer names the municipality.
- **„Ferðamenn“ means foreign passengers through Keflavík airport**, the closest measure in the data.
- **The language model can word things badly.** The number check catches wrong figures, not poor Icelandic.
- **Speed:** about 5–15 s per answer, almost all of it the local language model.

## Files

| File | Purpose |
|---|---|
| `app.py` | FastAPI backend: routing, price index and migration answers, Ollama call, number check |
| `gagnaleit.py` | Generic lookup: finds the right table and the exact figure |
| `toflur.py` | List of tables and the words that select values in them |
| `ingest.py` | Downloads the tables into `gogn/hagstofa.db` |
| `gogn/hagstofa.db` | The figures. The table search is built from `toflur.py` in memory at startup |
| `index.html` | Web chat interface (served at `/`) |
| `test_spurningar.py` | Test set with verified answers |
| `VIS01002_….xlsx` | Consumer price index data |
| `requirements_file.txt` | Python dependencies |

Data: Statistics Iceland (Hagstofa Íslands), open data.
