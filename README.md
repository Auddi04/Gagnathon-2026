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

| Topic | Coverage | You need to give |
|---|---|---|
| **Domestic migration** to the capital area (from other regions and from abroad), by sex | 2001–2025 | region + year |
| **Consumer price index** (base 1988 = 100), monthly | Dec 1999 – Jul 2026 | month + year |

If the region or year is missing, Hagur asks back. You can then just answer, e.g. „2014“.
Questions outside the data get an honest „I don't have data on that“.

## How it works

```
Browser (index.html)
   │  POST /spyrja  {"spurning": "..."}
   ▼
FastAPI (app.py)
   ├─ Keyword routing: price index or migration?
   ├─ Price index  → cached Excel table (VIS01002) in RAM
   ├─ Migration    → ChromaDB (hagstofa_master), loaded into RAM at startup
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

Requirements: **Python 3.10+**, **Git**, about **10 GB** free disk (models + database).

### 1. Get the code
```powershell
git clone https://github.com/Auddi04/Gagnathon-2026.git
cd Gagnathon-2026
```

### 2. Get the database
Download the pre-built database archive linked in `README Track_1.md` (Google Drive) and unzip it.
`app.py` expects the ChromaDB folder at **`./chroma_db_master`** next to `app.py`.

If the unzipped folder is called `chroma_db`, either rename it to `chroma_db_master`, or, if you keep it
somewhere else, create a link instead of copying 190 MB:
```powershell
New-Item -ItemType Junction -Path ".\chroma_db_master" -Target "C:\path\to\chroma_db"
```
Check it works (should print `[('hagstofa_master', 62267)]` after step 3):
```powershell
python -c "import chromadb; c=chromadb.PersistentClient(path='chroma_db_master'); print([(x.name, x.count()) for x in c.list_collections()])"
```

### 3. Python environment
```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements_file.txt
```

### 4. Ollama (local language model)
Install from https://ollama.com (or `irm https://ollama.com/install.ps1 | iex`), then:
```powershell
ollama pull llama3
```
Ollama runs in the background after installing. If it doesn't, run `ollama serve` in a separate terminal.

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

**Automatic test set:** 14 questions whose correct answers were checked directly against the database
and the Excel file. With the server running, in a second terminal:
```powershell
python test_spurningar.py
```
It prints ✅/❌ per question with response time and saves a table to `nidurstodur_profana.md`.

---

## Known limitations

- **Each question stands on its own.** Hagur remembers a question only when it has asked back
  (e.g. „Hvaða ár?“). „En 2016?“ after an answer does not work.
- **Migration data covers moves *to* the capital area only**, all ages combined. Moves from the capital
  area to other regions are not in the data.
- **Price index needs a month.** „Vísitalan 2020“ without a month is not answered.
- **Keyword routing.** Unusual phrasing or misspelled place names may not be understood.
- **Speed:** about 5–15 s per answer, almost all of it the local language model.
- `ingest.py` (from the starter kit) uses a different embedding model and collection than `app.py`,
  so tables added with it are not used by the chatbot without changes.

## Files

| File | Purpose |
|---|---|
| `app.py` | FastAPI backend: routing, data lookup, Ollama call, number check |
| `index.html` | Web chat interface (served at `/`) |
| `test_spurningar.py` | Test set with verified answers |
| `VIS01002_….xlsx` | Consumer price index data |
| `requirements_file.txt` | Python dependencies |
| `ingest.py` | Starter script for adding PX-API tables (see limitations) |

Data: Statistics Iceland (Hagstofa Íslands), open data.
