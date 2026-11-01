#app_multiple_quiery
from sentence_transformers import SentenceTransformer
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import requests
import json
import re
from threading import Lock
import pandas as pd

import gagnaleit

# Hlöðum Excel skjalinu inn við ræsingu appsins
EXCEL_PATH = "VIS01002_20260810-092754.xlsx"

cpi_df = pd.read_excel(EXCEL_PATH, sheet_name='VIS01002')
OLLAMA_URL = "http://localhost:11434/api/generate"
#MODEL_NAME = "hagstofa-ai:latest"
MODEL_NAME = "llama3"
ollama_lock = Lock()

try:
    embed_model = SentenceTransformer("BAAI/bge-m3", device="mps")
except:
    embed_model = SentenceTransformer("BAAI/bge-m3")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://hingolfur.github.io"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Búum til fljótleitar-orðabók (dict) úr Excel skjalinu
cpi_dict = {}
for idx, row in cpi_df.iterrows():
    t_str = str(row.iloc[0]).strip()
    if 'M' in t_str and len(t_str) == 7:  # T.d. '2010M06'
        try:
            val = float(row.iloc[1])
            cpi_dict[t_str] = val
        except ValueError:
            pass

# (ár, brottflutningssvæði, aðflutningssvæði, kyn) -> fjöldi, aldur: alls
BUFERLA_GOGN = {}


@app.on_event("startup")
def hlada_gogn():
    print("⏳ Hleð gögnum í minni...")
    print(f"✅ Vísitala neysluverðs: {len(cpi_dict)} mánuðir.")
    print(f"✅ Töflur Hagstofunnar: {gagnaleit.hlada_gogn(embed_model)}.")

    if "MAN01002" in gagnaleit.GOGN:
        tafla = gagnaleit.GOGN["MAN01002"]
        nofn = [v[0] for v in tafla["viddir"]]
        for lykill, gildi in tafla["gildi"].items():
            stak = dict(zip(nofn, lykill))
            fra = stak["Brottflutningssvæði"].replace(" - brottfluttir", "")
            til = stak["Aðflutningssvæði"].replace(" - aðfluttir", "")
            BUFERLA_GOGN[(stak["Ár"], fra, til, stak["Kyn"])] = int(gildi or 0)
        print(f"✅ Búferlaflutningar: {len(BUFERLA_GOGN)} færslur.")

    print("🚀 Öll gögn hlaðin í RAM!")


def finna_tolur(texti):
    # Fjarlægjum þúsundapunkta svo 17.594 og 17594 teljist sama talan
    texti = re.sub(r"(?<=\d)\.(?=\d{3}\b)", "", texti)
    return {t.replace(",", ".") for t in re.findall(r"\d+(?:[.,]\d+)?", texti)}


def naudsynlegar_tolur(texti):
    # Grunnur, gagnabil, kynjahlutföll og forsendur verðbólgu mega koma fram en þurfa þess ekki
    for valfrjalst in (r"\s*\(grunnur 1988\)", r"Gögnin ná frá [^.]*\.", r"Karlar voru [^.]*\.", r"\s*\(úr [^)]*\)", r"12 mánaða", r"1\. janúar"):
        texti = re.sub(valfrjalst, "", texti)
    return finna_tolur(texti)


def skrifa_svar_med_ai(spurning, founn_texti, skyld_ord=()):
    system_prompt = (
        "Notaðu tölurnar nákvæmlega eins og þær eru gefnar. "
        "Skrifaðu aðeins svarið sjálft, án athugasemda um svarið eða tungumálið. "
        "Svaraðu ávallt á vandaðri íslensku, í 1-3 setningum, EINGÖNGU út frá 'Samhengi úr gögnum'. "
        "Ekki reikna hlutföll, prósentur, meðaltöl eða breytingar og ekki bæta við neinum upplýsingum sem eru ekki í samhenginu. "
        + ("Taktu skýrt fram hvaðan og hvert var flutt og hvaða tímabil á við. " if "fluttu" in founn_texti else "Taktu skýrt fram hvaða tímabil á við. ")
        + "Ef samhengið svara ekki spurningunni, segðu það hreint út. "
    )
    leidretting = ""

    # Ef tölurnar í svarinu passa ekki við gögnin fær líkanið eina tilraun til viðbótar
    for _ in range(2):
        full_prompt = f"{system_prompt}\n\nSamhengi úr gögnum:\n{founn_texti}\n\nSpurning: {spurning}{leidretting}\nSvar:"
        payload = {"model": MODEL_NAME, "prompt": full_prompt, "stream": False, "options": {"temperature": 0.2}}

        try:
            with ollama_lock:
                response = requests.post(OLLAMA_URL, json=payload, timeout=120)

            if response.status_code != 200:
                print(f"⚠️ Líkanið svaraði með stöðu {response.status_code}, nota texta úr gögnum.")
                return founn_texti

            svar = response.json().get("response", "").strip()
            tolur = finna_tolur(svar)
            # Svarið má engu bæta við gögnin og verður að innihalda aðaltölurnar
            afangastadur_ok = "höfuðborgarsvæði" not in founn_texti or "höfuðborg" in svar.lower()
            ord_ok = all(o in svar.lower() for o in skyld_ord)
            if svar and afangastadur_ok and ord_ok and naudsynlegar_tolur(founn_texti) <= tolur <= finna_tolur(founn_texti):
                return svar
            leidretting = f"\n\nFyrra svar þitt var rangt því tölurnar pössuðu ekki við gögnin. Taktu fram þessar tölur og bættu engum öðrum við: {', '.join(sorted(naudsynlegar_tolur(founn_texti)))}."
        except Exception as e:
            print(f"⚠️ Náði ekki í líkanið ({e}), nota texta úr gögnum.")
            return founn_texti

    print("⚠️ Tölur í svari líkansins pössuðu ekki við gögnin, nota texta úr gögnum.")
    return founn_texti


MANUDIR = {
    "janúar": "01", "januar": "01", "jan": "01", "january": "01",
    "febrúar": "02", "februar": "02", "feb": "02", "february": "02",
    "mars": "03", "mar": "03", "march": "03",
    "apríl": "04", "april": "04", "apr": "04",
    "maí": "05", "mai": "05", "may": "05",
    "júní": "06", "juni": "06", "jun": "06", "june": "06",
    "júlí": "07", "juli": "07", "jul": "07", "july": "07",
    "ágúst": "08", "agust": "08", "aug": "08", "august": "08",
    "september": "09", "sep": "09",
    "október": "10", "oktober": "10", "oct": "10", "october": "10",
    "nóvember": "11", "nov": "11", "november": "11",
    "desember": "12", "dec": "12", "december": "12"
}
SVAEDI_THAGUFALL = {
    "suðurland": "Suðurlandi", "suðurnes": "Suðurnesjum", "austurland": "Austurlandi", "vesturland": "Vesturlandi",
    "vestfirðir": "Vestfjörðum", "norðurland": "Norðurlandi", "norðurland eystra": "Norðurlandi eystra", "norðurland vestra": "Norðurlandi vestra"
}
SVAEDI_ONNUR_HEITI = {
    "suðurland": ["sudurland"],
    "suðurnes": ["sudurnes", "reykjanes", "southern peninsula"],
    "austurland": ["austfj", "austfirð", "austfird", "eastfjord"],
    "vestfirðir": ["vestfj", "vestfirð", "vestfird", "fjord"],
    "norðurland": ["nordurland"],
    "norðurland eystra": ["nordurland eystra", "nordurlandi eystra", "norðaustur", "nordaustur", "northeast", "north east", "north-east"],
    "norðurland vestra": ["nordurland vestra", "nordurlandi vestra", "norðvestur", "nordvestur", "northwest", "north west", "north-west"]
}
# Leitarorð -> (texti í svari, brottflutningssvæði í gögnunum). Röðin skiptir máli: sértækast fyrst.
SVAEDI_ORD = [
    (["norðurland eystra", "norðurlandi eystra", "norðurlands eystra", "nordurland eystra", "nordurlandi eystra",
      "norðaustur", "nordaustur", "northeast", "north east", "north-east"], "Norðurlandi eystra", ["Norðurland eystra"]),
    (["norðurland vestra", "norðurlandi vestra", "norðurlands vestra", "nordurland vestra", "nordurlandi vestra",
      "norðvestur", "nordvestur", "northwest", "north west", "north-west"], "Norðurlandi vestra", ["Norðurland vestra"]),
    (["norðurland", "nordurland", "north"], "Norðurlandi (eystra og vestra samanlagt)", ["Norðurland eystra", "Norðurland vestra"]),
    (["austurland", "austfj", "austfirð", "austfird", "eastfjord", "east"], "Austurlandi", ["Austurland"]),
    (["vestfj", "vestfirð", "vestfird", "westfjord", "fjord"], "Vestfjörðum", ["Vestfirðir"]),
    (["vesturland", "west"], "Vesturlandi", ["Vesturland"]),
    (["suðurnes", "sudurnes", "reykjanes", "southern peninsula"], "Suðurnesjum", ["Suðurnes"]),
    (["suðurland", "sudurland", "south"], "Suðurlandi", ["Suðurland"]),
    (["útlönd", "útland", "erlendis", "abroad", "foreign"], "útlöndum", ["Útlönd"]),
]
HOFUDBORG_ORD = ["höfuðborg", "hofudborg", "reykjav", "reikjav", "reykjarv", "capital"]
HOFUDBORG = ("höfuðborgarsvæðinu", ["Höfuðborgarsvæði"])
# Eignarfall á eftir "til"
TIL_HEITI = {
    "Norðurlandi eystra": "Norðurlands eystra", "Norðurlandi vestra": "Norðurlands vestra",
    "Norðurlandi (eystra og vestra samanlagt)": "Norðurlands (eystra og vestra samanlagt)",
    "Austurlandi": "Austurlands", "Vestfjörðum": "Vestfjarða", "Vesturlandi": "Vesturlands", "Suðurnesjum": "Suðurnesja",
    "Suðurlandi": "Suðurlands", "útlöndum": "útlanda", "höfuðborgarsvæðinu": "höfuðborgarsvæðisins",
}
BUFERLA_ORD = re.compile(r"\b(flutt|flyt|búferla|flutning|moved?\b|migrat)")
MILLILANDA_ORD = re.compile(r"ríkisborgar|ríkisfang|citizen|til landsins|frá landinu|immigra|emigra|innflytj")
TIL_MYNSTUR = re.compile(r"\b(?:til|to)\s+(?:the\s+)?(.+?)(?=\s+(?:frá|from|árið|ári|árin|year|in|á|í)\b|\s*\d{4}|[?.!,]|$)")


def finna_svaedi(texti):
    fundid = []
    for ord_listi, heiti, svaedi in SVAEDI_ORD:
        mynstur = r"\b(" + "|".join(re.escape(o) for o in ord_listi) + ")"
        if re.search(mynstur, texti):
            fundid.append((heiti, svaedi))
            texti = re.sub(mynstur + r"\w*", " ", texti)  # svo "norðurland eystra" teljist ekki líka sem "norðurland"
    return fundid


MANADA_HEITI = ["janúar", "febrúar", "mars", "apríl", "maí", "júní", "júlí", "ágúst", "september", "október", "nóvember", "desember"]


def heiti_timabils(lykill):
    return f"{MANADA_HEITI[int(lykill[5:]) - 1]} {lykill[:4]}"


def med_kommu(tala):
    return f"{tala:.1f}".replace(".", ",")


def finna_timabil(spurning_lower):
    """Skilar tímabilum í röð (t.d. '2024M03') og hvort mánuður eða ár hafi fundist í spurningunni."""
    timabil, bidandi = [], []
    sidasti_manudur, sidasta_ar = None, None
    manudur_fannst, ar_fannst = False, False

    for ord in re.findall(r"\d{1,2}\.\s*mán[ua]ð\w*|\w+", spurning_lower):
        kodi = re.fullmatch(r"(\d{4})m(\d{2})", ord)
        numer = re.match(r"(\d{1,2})\.", ord)
        manudur = MANUDIR.get(re.sub(r"(mánuð|mánað)\w*$", "", ord)) or MANUDIR.get(ord)
        if numer and 1 <= int(numer.group(1)) <= 12:
            manudur = numer.group(1).zfill(2)

        if kodi:
            sidasta_ar, sidasti_manudur = kodi.group(1), kodi.group(2)
            manudur_fannst, ar_fannst = True, True
            timabil.append(f"{sidasta_ar}M{sidasti_manudur}")
        elif manudur:
            manudur_fannst = True
            sidasti_manudur = manudur
            bidandi.append(manudur)
        elif ord.isdigit() and len(ord) == 4:
            ar_fannst = True
            sidasta_ar = ord
            # Ártal án nýs mánaðar á við síðasta mánuð, t.d. "mars 2023 og 2024"
            for m in bidandi or ([sidasti_manudur] if sidasti_manudur else []):
                timabil.append(f"{ord}M{m}")
            bidandi = []

    if sidasta_ar:
        timabil.extend(f"{sidasta_ar}M{m}" for m in bidandi)
    return list(dict.fromkeys(timabil)), manudur_fannst, ar_fannst


def svara_visitolu(spurning_lower):
    fyrsta, sidasta = min(cpi_dict), max(cpi_dict)
    gagnabil = f"Gögnin ná frá {heiti_timabils(fyrsta)} til {heiti_timabils(sidasta)}."
    timabil, manudur_fannst, ar_fannst = finna_timabil(spurning_lower)

    if not timabil:
        vantar = "ár" if manudur_fannst else "mánuð" if ar_fannst else "mánuð og ár"
        return f"Til að fletta upp vísitölu neysluverðs vantar {vantar} í spurninguna, til dæmis mars 2024. {gagnabil}"

    vantar_gogn = [t for t in timabil if t not in cpi_dict]
    if vantar_gogn:
        return f"Engin gögn eru um vísitölu neysluverðs fyrir {', '.join(heiti_timabils(t) if 1 <= int(t[5:]) <= 12 else t for t in vantar_gogn)}. {gagnabil}"

    if "verðbólg" in spurning_lower or "inflation" in spurning_lower:
        linur = []
        for t in timabil:
            fyrra = f"{int(t[:4]) - 1}{t[4:]}"
            if fyrra not in cpi_dict:
                linur.append(f"Ekki er hægt að reikna 12 mánaða verðbólgu fyrir {heiti_timabils(t)} því gögn vantar fyrir {heiti_timabils(fyrra)}. {gagnabil}")
                continue
            breyting = (cpi_dict[t] / cpi_dict[fyrra] - 1) * 100
            linur.append(f"Verðbólga í {heiti_timabils(t)}, mæld sem 12 mánaða breyting á vísitölu neysluverðs, var {med_kommu(breyting)}% (úr {med_kommu(cpi_dict[fyrra])} stigum í {heiti_timabils(fyrra)} í {med_kommu(cpi_dict[t])} stig).")
        return "\n".join(linur)

    if len(timabil) == 2:
        fra, til = timabil
        munur = cpi_dict[til] - cpi_dict[fra]
        prosent = abs(munur / cpi_dict[fra] * 100)
        if round(munur, 1) == 0:
            lysing = "sem er engin breyting"
        else:
            ord = "hækkun" if munur > 0 else "lækkun"
            lysing = f"sem er {ord} um {med_kommu(abs(munur))} stig eða {med_kommu(prosent)}%"
        return f"Vísitala neysluverðs (grunnur 1988) var {med_kommu(cpi_dict[fra])} stig í {heiti_timabils(fra)} og {med_kommu(cpi_dict[til])} stig í {heiti_timabils(til)}, {lysing}."

    if len(timabil) == 1:
        return f"Vísitala neysluverðs í {heiti_timabils(timabil[0])} var {med_kommu(cpi_dict[timabil[0]])} stig (grunnur 1988)."

    gildi = ", ".join(f"{heiti_timabils(t)}: {med_kommu(cpi_dict[t])} stig" for t in timabil)
    return f"Vísitala neysluverðs (grunnur 1988) — {gildi}."


def _flutningar(ar, fra_listi, til_listi):
    return {kyn: sum(BUFERLA_GOGN.get((ar, f, t, kyn), 0) for f in fra_listi for t in til_listi if f != t)
            for kyn in ("Alls", "Karlar", "Konur")}


def _flutningar_setning(ar, fra_texti, til_texti, tolur):
    texti = (f"Árið {ar} fluttu {tolur['Alls']} manns {fra_texti} {til_texti}, "
             f"þar af {tolur['Karlar']} karlar og {tolur['Konur']} konur.")
    if tolur["Alls"] > 0:
        texti += (f" Karlar voru {tolur['Karlar'] / tolur['Alls'] * 100:.1f}% og konur "
                  f"{tolur['Konur'] / tolur['Alls'] * 100:.1f}% þeirra sem fluttu.").replace(".", ",", 2)
    return texti


def svara_buferla(spurning_lower):
    """Skilar (staðreyndir, athugasemdir, spyr_a_moti) um flutninga milli landsvæða."""
    oll_ar = sorted({k[0] for k in BUFERLA_GOGN})
    innanlands = sorted({k[1] for k in BUFERLA_GOGN} - {"Útlönd"})
    timabil_texti = f"{oll_ar[0]}–{oll_ar[-1]}" if oll_ar else "?"
    daemi = "(t.d. Norðurland, Austurland, Suðurland, Vestfirðir, Suðurnes, höfuðborgarsvæðið, útlönd)"

    spurning_lower = re.sub(r"\bmoved? abroad\b", "moved to abroad", spurning_lower)
    arin = sorted(set(re.findall(r"\b(\d{4})\b", spurning_lower)))
    til_m = TIL_MYNSTUR.search(spurning_lower)
    til_hluti = til_m.group(1) if til_m else ""
    fra_hluti = spurning_lower[:til_m.start()] + " " + spurning_lower[til_m.end():] if til_m else spurning_lower

    til_svaedi = finna_svaedi(til_hluti)
    if any(h in til_hluti for h in HOFUDBORG_ORD):
        til_svaedi.append(HOFUDBORG)
    fra_svaedi = finna_svaedi(fra_hluti)
    if any(h in fra_hluti for h in HOFUDBORG_ORD):
        if re.search(r"\b(?:frá|úr|from|out of|leaving|left)\s+(?:the\s+)?(?:höfuðborg|hofudborg|reykjav|reykjarv|reikjav|capital)", fra_hluti):
            fra_svaedi.append(HOFUDBORG)
        elif not til_svaedi:
            til_svaedi.append(HOFUDBORG)

    if not fra_svaedi and not til_svaedi:
        return [], [f"Frá hvaða eða til hvaða landsvæðis viltu skoða flutninga? {daemi}"], True
    if not arin:
        return [], [f"Hvaða ár viltu skoða? Gögn um búferlaflutninga ná yfir árin {timabil_texti}."], True

    svor, athugasemdir = [], []
    for ar in arin:
        if ar not in oll_ar:
            athugasemdir.append(f"Engin gögn um búferlaflutninga fyrir árið {ar}. Gögnin ná yfir {timabil_texti}.")
            continue
        if fra_svaedi and til_svaedi:
            for fra_heiti, fra in fra_svaedi:
                for til_heiti, til in til_svaedi:
                    svor.append(_flutningar_setning(ar, f"frá {fra_heiti}", f"til {TIL_HEITI[til_heiti]}", _flutningar(ar, fra, til)))
        elif fra_svaedi:
            for fra_heiti, fra in fra_svaedi:
                adrir = [s for s in innanlands if s not in fra]
                til_texti = "til Íslands" if fra == ["Útlönd"] else "til annarra landsvæða innanlands"
                texti = _flutningar_setning(ar, f"frá {fra_heiti}", til_texti, _flutningar(ar, fra, adrir))
                if "Höfuðborgarsvæði" not in fra:
                    borg = _flutningar(ar, fra, ["Höfuðborgarsvæði"])
                    texti += f" Þar af fluttu {borg['Alls']} til höfuðborgarsvæðisins ({borg['Karlar']} karlar og {borg['Konur']} konur)."
                svor.append(texti)
        else:
            for til_heiti, til in til_svaedi:
                adrir = [s for s in innanlands + ["Útlönd"] if s not in til]
                fra_texti = "frá landsvæðum innanlands" if til == ["Útlönd"] else "frá öðrum landsvæðum og útlöndum"
                texti = _flutningar_setning(ar, fra_texti, f"til {TIL_HEITI[til_heiti]}", _flutningar(ar, adrir, til))
                if til != ["Útlönd"]:
                    texti += f" Þar af komu {_flutningar(ar, ['Útlönd'], til)['Alls']} frá útlöndum."
                svor.append(texti)
    return svor, athugasemdir, False


def spyrja_beint(spurning):
    spurning_lower = spurning.lower()
    svor = []          # staðreyndir úr gögnunum, fara til líkansins
    heimildir = []
    athugasemdir = []  # skilaboð til notanda sem fara EKKI til líkansins
    skyld_ord = []     # orð sem verða að koma fram í svari líkansins
    spyr_a_moti = False

    # 1. Vísitala neysluverðs
    if any(w in spurning_lower for w in ["vísitala", "vísitöl", "neysluverð", "cpi", "price index", "index", "verðbólg", "inflation"]):
        texti = svara_visitolu(spurning_lower)
        if texti.startswith("Til að fletta upp"):
            athugasemdir.append(texti)
            spyr_a_moti = True
        elif texti.startswith("Engin gögn"):
            athugasemdir.append(texti)
        else:
            svor.append(texti)
            heimildir.append("Hagstofa Íslands – Vísitala neysluverðs (VIS01002)")

    # 2. Búferlaflutningar milli landsvæða
    if BUFERLA_ORD.search(spurning_lower) and not MILLILANDA_ORD.search(spurning_lower):
        buferla_svor, buferla_athugasemdir, buferla_spyr = svara_buferla(spurning_lower)
        svor.extend(buferla_svor)
        athugasemdir.extend(buferla_athugasemdir)
        spyr_a_moti = spyr_a_moti or buferla_spyr
        if buferla_svor:
            heimildir.append("Hagstofa Íslands – Búferlaflutningar milli landsvæða (MAN01002)")

    # 3. Aðrar töflur: vigurleit finnur töfluna og talan er sótt nákvæmlega úr henni
    if not svor and not athugasemdir:
        nidurstada = gagnaleit.svara(spurning, embed_model, finna_timabil)
        if nidurstada:
            svor = nidurstada["svor"]
            heimildir = nidurstada["heimildir"]
            athugasemdir = nidurstada["athugasemdir"]
            skyld_ord = nidurstada["skyld_ord"]
            spyr_a_moti = nidurstada["spyr_a_moti"]

    if svor:
        svar = skrifa_svar_med_ai(spurning, "\n".join(svor), skyld_ord)
        if athugasemdir:
            svar += "\n\n" + "\n".join(athugasemdir)
        return {"svar": svar, "heimildir": heimildir, "spyr_a_moti": False}
    if athugasemdir:
        return {"svar": "\n".join(athugasemdir), "heimildir": [], "spyr_a_moti": spyr_a_moti}
    return {"svar": "Ég fann ekki gögn sem svara þessu. Ég get svarað spurningum um mannfjölda, búferlaflutninga, fædda og dána, "
                    "atvinnuleysi, laun, landsframleiðslu, ferðaþjónustu, vísitölu neysluverðs og verðbólgu.",
            "heimildir": [], "spyr_a_moti": False}

class SpurningRequest(BaseModel):
    spurning: str

@app.post("/spyrja")
def spyrja_vefthjon(req: SpurningRequest):
    return spyrja_beint(req.spurning)


# Vefviðmót: opnaðu http://127.0.0.1:8000 í vafra
@app.get("/")
def forsida():
    return FileResponse("index.html")
