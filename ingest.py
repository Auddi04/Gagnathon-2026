"""
Sækir töflurnar í toflur.py úr PX-vefþjónustu Hagstofunnar í gogn/hagstofa.db (SQLite).
Leitin að réttri töflu er byggð úr lýsingunum í toflur.py þegar appið ræsist.

Keyrsla:
    python ingest.py              sækir allar töflur
    python ingest.py MAN02005     sækir aðeins þessa töflu
"""
import itertools
import os
import sqlite3
import sys
import time

import requests

from toflur import TOFLUR

API_URL = "https://px.hagstofa.is/pxis/api/v1/is"
GOGN_DIR = "gogn"
DB_PATH = os.path.join(GOGN_DIR, "hagstofa.db")


def saekja_toflu(tafla):
    """Skilar titli, uppfærsludegi, víddum [(nafn, er_timi, [merki])] og línum [(merki..., gildi)]."""
    url = f"{API_URL}/{tafla['slod']}"
    meta = requests.get(url, timeout=60)
    meta.raise_for_status()
    meta = meta.json()

    fyrirspurn = []
    for vidd in meta["variables"]:
        valin = tafla.get("sia", {}).get(vidd["code"])
        if valin:
            merki_i_kodi = {t.strip(): k for k, t in zip(vidd["values"], vidd["valueTexts"])}
            vantar = [m for m in valin if m not in merki_i_kodi]
            if vantar:
                raise ValueError(f"{tafla['kodi']}: fann ekki {vantar} í víddinni {vidd['code']}")
            val = {"filter": "item", "values": [merki_i_kodi[m] for m in valin]}
        else:
            val = {"filter": "all", "values": ["*"]}
        fyrirspurn.append({"code": vidd["code"], "selection": val})

    svar = requests.post(url, json={"query": fyrirspurn, "response": {"format": "json-stat2"}}, timeout=120)
    svar.raise_for_status()
    gogn = svar.json()

    timavidd = {v["code"] for v in meta["variables"] if v.get("time")}
    viddir = []
    for nafn in gogn["id"]:
        flokkur = gogn["dimension"][nafn]["category"]
        rod = flokkur["index"]
        kodar = sorted(rod, key=rod.get) if isinstance(rod, dict) else rod
        viddir.append((nafn, nafn in timavidd, [flokkur["label"][k].strip() for k in kodar]))

    # json-stat geymir gildin í einum lista, í sömu röð og margfeldi víddanna
    gildi = gogn["value"]
    if isinstance(gildi, dict):
        gildi = [gildi.get(str(i)) for i in range(sum(1 for _ in itertools.product(*(v[2] for v in viddir))))]
    linur = [(*merki, g) for merki, g in zip(itertools.product(*(v[2] for v in viddir)), gildi)]
    return meta.get("title", tafla["heiti"]), gogn.get("updated", ""), viddir, linur


def vista_toflu(con, tafla, titill, uppfaert, viddir, linur):
    kodi = tafla["kodi"]
    con.execute("DELETE FROM toflur WHERE kodi = ?", (kodi,))
    con.execute("DELETE FROM viddir WHERE kodi = ?", (kodi,))
    con.execute("DELETE FROM gildi WHERE kodi = ?", (kodi,))
    con.execute("INSERT INTO toflur VALUES (?, ?, ?, ?)", (kodi, titill, uppfaert, f"{API_URL}/{tafla['slod']}"))
    for rod, (nafn, er_timi, merki) in enumerate(viddir):
        con.execute("INSERT INTO viddir VALUES (?, ?, ?, ?, ?)", (kodi, rod, nafn, int(er_timi), "\x1f".join(merki)))
    con.executemany("INSERT INTO gildi VALUES (?, ?, ?)",
                    ((kodi, "\x1f".join(lina[:-1]), lina[-1]) for lina in linur))


def main(koda=None):
    os.makedirs(GOGN_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS toflur (kodi TEXT PRIMARY KEY, titill TEXT, uppfaert TEXT, url TEXT);
        CREATE TABLE IF NOT EXISTS viddir (kodi TEXT, rod INTEGER, nafn TEXT, er_timi INTEGER, merki TEXT);
        CREATE TABLE IF NOT EXISTS gildi (kodi TEXT, lykill TEXT, gildi REAL);
        CREATE INDEX IF NOT EXISTS gildi_kodi ON gildi (kodi);
    """)

    villur = []
    for tafla in TOFLUR:
        if koda and tafla["kodi"] not in koda:
            continue
        try:
            titill, uppfaert, viddir, linur = saekja_toflu(tafla)
            vista_toflu(con, tafla, titill, uppfaert, viddir, linur)
            con.commit()
            tomar = sum(1 for lina in linur if lina[-1] is None)
            print(f"✅ {tafla['kodi']}: {len(linur)} línur, {tomar} tómar. {titill}")
        except Exception as e:
            villur.append(tafla["kodi"])
            print(f"❌ {tafla['kodi']}: {e}")
        time.sleep(1)  # vefþjónustan takmarkar fjölda fyrirspurna

    con.close()
    if villur:
        print(f"⚠️ Tókst ekki að sækja: {', '.join(villur)}")
        sys.exit(1)


if __name__ == "__main__":
    main(set(sys.argv[1:]) or None)
