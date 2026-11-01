"""
Prófanir fyrir Hagur-spjallmennið.

Sendir spurningar á /spyrja og athugar hvort svarið innihaldi réttar tölur
(sannreyndar beint úr vefþjónustu Hagstofunnar og Excel-skjalinu).

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
    # Búferlaflutningar milli landsvæða (aldur: alls)
    ("Flutningar", "Hvað fluttu margar konur og karlar frá Norðurlandi til höfuðborgarinnar árið 2024?", ["777", "402", "375"], "höfuðborg"),
    ("Flutningar", "Hvað fluttu margir frá Austurlandi 2015?", ["284", "142"], "höfuðborg"),
    ("Flutningar", "Hvað fluttu margir frá Norðurlandi eystra og Vestfjörðum 2020?", ["653", "302"], None),
    ("Flutningar", "Hvað fluttu margir frá Suðurlandi árið 2023?", ["821", "395", "426"], None),
    ("Flutningar", "Hvað fluttu margir frá Suðurnesjum 2025?", ["1188", "721", "467"], None),
    ("Flutningar (enska)", "How many people moved from abroad to the capital area in 2024?", ["12689", "7269", "5420"], None),
    ("Flutningar", "Hvað fluttu margir frá höfuðborgarsvæðinu til Suðurlands 2024?", ["1283", "671", "612"], None),
    ("Flutningar", "Hvað fluttu margir frá höfuðborgarsvæðinu 2024?", ["3973"], None),
    ("Flutningar", "Hvað fluttu margir til Austurlands 2022?", ["945"], None),
    ("Flutningar", "Hvað fluttu margir til útlanda 2023?", ["14771"], None),
    ("Flutningar", "Hversu margir erlendir ríkisborgarar fluttu til landsins 2024?", ["14796"], None),
    # Mannfjöldi
    ("Mannfjöldi", "Hvað búa margir á Akureyri?", ["20284", "2026"], None),
    ("Mannfjöldi", "Hvað búa margar konur í Reykjavík árið 2024?", ["67156"], None),
    ("Mannfjöldi (enska)", "How many people live in Kópavogur in 2020?", ["37036"], None),
    ("Mannfjöldi", "Hvað búa margir í Rangárþingi ytra 2026?", ["1966"], None),
    ("Mannfjöldi", "Hvað búa margir í Stykkishólmi 2026?", ["1300"], None),
    ("Mannfjöldi", "Hvað búa margir á höfuðborgarsvæðinu 2025?", ["249054"], None),
    ("Mannfjöldi", "Hvað búa margir á Norðurlandi 2025?", ["39381"], None),
    # Fæddir og dánir
    ("Fæddir", "Hvað fæddust mörg börn árið 2024?", ["4311"], None),
    ("Fæddir", "Hvað fæddust margir drengir 2020?", ["2381"], None),
    ("Dánir", "Hvað dóu margir 2024?", ["2607"], None),
    # Vinnumarkaður og laun
    ("Atvinnuleysi", "Hvert var atvinnuleysi 2024?", ["3.3"], None),
    ("Atvinnuleysi", "Hvert var atvinnuleysi kvenna á höfuðborgarsvæðinu 2023?", ["3.3"], None),
    ("Atvinnuleysi", "Hversu margir voru atvinnulausir 2020?", ["12700"], None),
    ("Laun", "Hver voru meðallaun 2024?", ["987"], None),
    ("Laun", "Hver voru heildarlaun kvenna 2023?", ["857"], None),
    ("Laun", "Hver voru miðgildi launa stjórnenda 2024?", ["1352"], None),
    # Landsframleiðsla
    ("Landsframleiðsla", "Hver var landsframleiðslan 2023?", ["4367200"], None),
    # Ferðaþjónusta
    ("Ferðaþjónusta", "Hvað voru margar gistinætur 2024?", ["9312648"], None),
    ("Ferðaþjónusta", "Hvað voru margar gistinætur útlendinga á Norðurlandi í júlí 2024?", ["190828"], None),
    ("Ferðaþjónusta", "Hvað fóru margir farþegar um Keflavíkurflugvöll í júlí 2025?", ["368339"], None),
    ("Ferðaþjónusta", "Hversu margir ferðamenn komu 2024?", ["2261391"], None),
    # Vísitala neysluverðs (grunnur 1988 = 100)
    ("Vísitala", "Hver var vísitala neysluverðs í janúar 2020?", ["469.8"], None),
    ("Vísitala", "Hver var vísitala neysluverðs í júní 2024?", ["630.3"], None),
    ("Vísitala (enska)", "What was the consumer price index in July 2026?", ["693.2"], None),
    # Óljósar spurningar / utan gagna: kerfið á að spyrja á móti eða segja satt
    ("Óljós: vantar ár", "Hvað fluttu margir frá Suðurlandi?", [], "hvaða ár"),
    ("Óljós: vantar svæði", "Hvað fluttu margir árið 2023?", [], "landsvæði"),
    ("Utan tímabils", "Hvað fluttu margir frá Suðurlandi 1980?", [], "engin gögn"),
    ("Utan tímabils", "Hvert var atvinnuleysi 1950?", [], "engin gögn"),
    ("Óþekktur staður", "Hvað búa margir í Vík?", [], "fann ekki"),
    ("Gögn ekki eftir stað", "Hvað fæddust mörg börn á Akureyri 2024?", ["4311"], "allt landið"),
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
