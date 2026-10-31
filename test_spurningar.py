"""
Prófanir fyrir Hagur-spjallmennið.

Sendir spurningar á /spyrja og athugar hvort svarið innihaldi réttar tölur
(sannreyndar beint úr gagnagrunninum og Excel-skjalinu).

Keyrsla (vefþjónninn þarf að vera í gangi í öðrum glugga):
    python test_spurningar.py

Niðurstöður eru líka vistaðar í nidurstodur_profana.md (sönnunargögn fyrir kynningu).
"""
import re
import time
from datetime import datetime

import requests

URL = "http://127.0.0.1:8000/spyrja"

# (flokkur, spurning, tölur sem VERÐA að koma fram, texti sem á að koma fram)
PROF = [
    # Búferlaflutningar til höfuðborgarsvæðisins (aldur: alls)
    ("Flutningar", "Hvað fluttu margar konur og karlar frá Norðurlandi til höfuðborgarinnar árið 2024?", ["777", "402", "375"], "höfuðborg"),
    ("Flutningar", "Hvað fluttu margir frá Austurlandi 2015?", ["284", "142"], "höfuðborg"),
    ("Flutningar", "Hvað fluttu margir frá Norðurlandi eystra og Vestfjörðum 2020?", ["653", "302"], None),
    ("Flutningar", "Hvað fluttu margir frá Suðurlandi árið 2023?", ["821", "395", "426"], None),
    ("Flutningar", "Hvað fluttu margir frá Suðurnesjum 2025?", ["1188", "721", "467"], None),
    ("Flutningar (enska)", "How many people moved from abroad to the capital area in 2024?", ["12689", "7269", "5420"], None),
    # Vísitala neysluverðs (grunnur 1988 = 100)
    ("Vísitala", "Hver var vísitala neysluverðs í janúar 2020?", ["469.8"], None),
    ("Vísitala", "Hver var vísitala neysluverðs í júní 2024?", ["630.3"], None),
    ("Vísitala (enska)", "What was the consumer price index in July 2026?", ["693.2"], None),
    # Óljósar spurningar / utan gagna: kerfið á að spyrja á móti eða segja satt
    ("Óljós: vantar ár", "Hvað fluttu margir frá Suðurlandi?", [], "hvaða ár"),
    ("Óljós: vantar svæði", "How many people moved from the capital in 2023?", [], "landsvæði"),
    ("Utan tímabils", "Hvað fluttu margir frá Suðurlandi 1990?", [], "engin gögn"),
    ("Utan gagna", "Hvað kostar mjólk?", [], "fann ekki"),
    ("Þekkt takmörkun", "Hver var vísitala neysluverðs árið 2020?", [], None),
]


def tolur(texti):
    # "12.689" -> "12689", "469,8" -> "469.8"
    texti = re.sub(r"(?<=\d)\.(?=\d{3}\b)", "", texti)
    texti = re.sub(r"(?<=\d),(?=\d)", ".", texti)
    return set(re.findall(r"\d+(?:\.\d+)?", texti))


def main():
    linur = []
    stadist = 0
    for flokkur, spurning, rettar, texti in PROF:
        byrjun = time.time()
        try:
            r = requests.post(URL, json={"spurning": spurning}, timeout=180)
            r.raise_for_status()
            gogn = r.json()
            svar = gogn.get("svar", "")
            heimildir = "; ".join(gogn.get("heimildir", []))
        except Exception as e:
            svar, heimildir = f"VILLA: {e}", ""
        sek = time.time() - byrjun

        vantar = [t for t in rettar if t not in tolur(svar)]
        texti_ok = texti is None or texti.lower() in svar.lower()
        if flokkur == "Þekkt takmörkun":
            nidurstada = "ℹ️ takmörkun"
        elif not vantar and texti_ok and not svar.startswith("VILLA"):
            nidurstada = "✅ rétt"
            stadist += 1
        else:
            nidurstada = "❌ rangt"
            if vantar:
                nidurstada += f" (vantar {', '.join(vantar)})"
            if not texti_ok:
                nidurstada += f" (vantar '{texti}')"

        print(f"{nidurstada:<28} {sek:5.1f} s  {spurning}")
        print(f"{'':<36}→ {svar[:150]}")
        linur.append((flokkur, spurning, svar.replace("\n", " "), heimildir, f"{sek:.1f}", nidurstada))

    profanir = sum(1 for p in PROF if p[0] != "Þekkt takmörkun")
    print(f"\n{stadist}/{profanir} prófanir stóðust.")

    with open("nidurstodur_profana.md", "w", encoding="utf-8") as f:
        f.write(f"# Niðurstöður prófana – {datetime.now():%Y-%m-%d %H:%M}\n\n")
        f.write(f"**{stadist}/{profanir} prófanir stóðust.** Réttar tölur sannreyndar beint úr gögnum Hagstofunnar.\n\n")
        f.write("| Flokkur | Spurning | Svar | Heimild | Tími (s) | Niðurstaða |\n|---|---|---|---|---|---|\n")
        for l in linur:
            f.write("| " + " | ".join(x.replace("|", "/") for x in l) + " |\n")
    print("Vistað í nidurstodur_profana.md")


if __name__ == "__main__":
    main()
