#app_multiple_quiery
import chromadb
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

# Hlöðum Excel skjalinu inn við ræsingu appsins
EXCEL_PATH = "VIS01002_20260810-092754.xlsx"

cpi_df = pd.read_excel(EXCEL_PATH, sheet_name='VIS01002')
OLLAMA_URL = "http://localhost:11434/api/generate"
#MODEL_NAME = "hagstofa-ai:latest"
MODEL_NAME = "llama3"
ollama_lock = Lock()

CHROMA_DIR = "./chroma_db_master"
chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
collection = chroma_client.get_collection(name="hagstofa_master")

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

# Global breyta sem geymir spegilmyndina í minni
METADATA_MIRROR = {
    "visitala": {"ars_bil": [], "manudir": []},
    "buferla": {"ars_bil": [], "svaedi": set()}
}

# (ár, brottflutningssvæði, kyn) -> fjöldi. Öll gögnin eru flutningar TIL höfuðborgarsvæðisins, aldur: alls.
BUFERLA_GOGN = {}
BUFERLA_LYSING = re.compile(r"Kyn: (\w+), Ár: (\d{4}), Brottflutningssvæði: (.+?) - brottfluttir, Aldur: Alls\.")


@app.on_event("startup")
def load_metadata_mirror():
    print("⏳ Byrja að hlaða metadata spegilmynd í minni...")
    
    # 1. Spegilmynd fyrir Excel (Vísitölur)
    try:
        ars_listi = set()
        for t_str in cpi_dict.keys():
            ar = t_str[:4]
            ars_listi.add(ar)
        METADATA_MIRROR["visitala"]["ars_bil"] = sorted(list(ars_listi))
        print("✅ Vísitölu-spegilmynd tilbúin.")
    except Exception as e:
        print(f"Villa við vísitölu-spegil: {e}")

    # 2. Spegilmynd fyrir ChromaDB (Búferlaflutningar) - Sækja í bútum
    try:
        ars_set = set()
        svaeda_set = set()
        kynja_set = set()
        
        batch_size, offset = 2000, 0
        while True:
            results = collection.get(limit=batch_size, offset=offset, include=['metadatas'])
            batch_metadatas = results.get('metadatas', [])
            if not batch_metadatas:
                break
                
            for meta in batch_metadatas:
                if meta:
                    timabil = meta.get('timabil') or meta.get('svaedi')
                    if timabil:
                        svaeda_set.add(str(timabil).lower())
                    
                    maeling = str(meta.get('maeling', ''))
                    if len(maeling) >= 4 and maeling[:4].isdigit():
                        ars_set.add(maeling[:4])
                        
                    kyn = meta.get('kyn')
                    if kyn:
                        kynja_set.add(str(kyn).lower())
            
            offset += batch_size
            if len(batch_metadatas) < batch_size:
                break

        METADATA_MIRROR["buferla"] = {
            "ars_bil": sorted(list(ars_set)),
            "svaedi": list(svaeda_set),
            "kyn": list(kynja_set)
        }
        
        print(f"✅ ChromaDB spegilmynd tilbúin. Fann {len(svaeda_set)} svæði og {len(ars_set)} ár.")
    except Exception as e:
        print(f"❌ Villa við ChromaDB spegil: {e}")

    # 3. Búferlaflutningar: lesum allar "aldur: alls" línur í RAM einu sinni
    try:
        offset = 0
        while True:
            results = collection.get(where={"gagnasett": "buferlaflutningar"}, limit=2000, offset=offset,
                                     include=['documents', 'metadatas'])
            docs, metas = results.get('documents', []), results.get('metadatas', [])
            if not docs:
                break
            for doc, meta in zip(docs, metas):
                m = BUFERLA_LYSING.search(doc)
                if m:
                    kyn, ar, svaedi = m.group(1), m.group(2), m.group(3)
                    BUFERLA_GOGN[(ar, svaedi, kyn)] = int(float(str(meta.get('gildi', 0)).replace(',', '.')))
            offset += 2000
            if len(docs) < 2000:
                break
        print(f"✅ Búferlaflutningar í RAM: {len(BUFERLA_GOGN)} færslur.")
    except Exception as e:
        print(f"❌ Villa við að lesa búferlaflutninga: {e}")

    print("🚀 Allar spegilmyndir hlaðnar í RAM!")


def finna_tolur(texti):
    # Fjarlægjum þúsundapunkta svo 17.594 og 17594 teljist sama talan
    texti = re.sub(r"\b(\d{1,3})\.(\d{3})\b", r"\1\2", texti)
    return {t.replace(",", ".") for t in re.findall(r"\d+(?:[.,]\d+)?", texti)}


def naudsynlegar_tolur(texti):
    # Grunnur, gagnabil, kynjahlutföll og forsendur verðbólgu mega koma fram en þurfa þess ekki
    for valfrjalst in (r"\s*\(grunnur 1988\)", r"Gögnin ná frá [^.]*\.", r"Karlar voru [^.]*\.", r"\s*\(úr [^)]*\)", r"12 mánaða"):
        texti = re.sub(valfrjalst, "", texti)
    return finna_tolur(texti)


def skrifa_svar_med_ai(spurning, founn_texti):
    system_prompt = (
        "Notaðu tölurnar nákvæmlega eins og þær eru gefnar. "
        "Skrifaðu aðeins svarið sjálft, án athugasemda um svarið eða tungumálið. "
        "Svaraðu ávallt á vandaðri íslensku, í 1-3 setningum, EINGÖNGU út frá 'Samhengi úr gögnum'. "
        "Ekki reikna hlutföll, prósentur, meðaltöl eða breytingar og ekki bæta við neinum upplýsingum sem eru ekki í samhenginu. "
        "Taktu skýrt fram hvaðan og hvert var flutt og hvaða tímabil á við. "
        "Ef samhengið svara ekki spurningunni, segðu það hreint út. "
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
            if svar and afangastadur_ok and naudsynlegar_tolur(founn_texti) <= tolur <= finna_tolur(founn_texti):
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
    (["útlönd", "erlendis", "abroad", "foreign"], "útlöndum", ["Útlönd"]),
]
HOFUDBORG_ORD = ["höfuðborg", "hofudborg", "reykjav", "reikjav", "reykjarv", "capital"]


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


def spyrja_beint(spurning):
    spurning_lower = spurning.lower()
    svor = []          # staðreyndir úr gögnunum, fara til líkansins
    heimildir = []
    athugasemdir = []  # skilaboð til notanda sem fara EKKI til líkansins
    spyr_a_moti = False

    # 1. Vísitala neysluverðs
    if any(w in spurning_lower for w in ["vísitala", "vísitöl", "neyslu", "cpi", "price index", "index", "verðbólg", "inflation"]):
        texti = svara_visitolu(spurning_lower)
        if texti.startswith("Til að fletta upp"):
            athugasemdir.append(texti)
            spyr_a_moti = True
        elif texti.startswith("Engin gögn"):
            athugasemdir.append(texti)
        else:
            svor.append(texti)
            heimildir.append("Hagstofa Íslands – Vísitala neysluverðs (VIS01002)")

    # 2. Búferlaflutningar (öll gögnin eru flutningar TIL höfuðborgarsvæðisins)
    if any(w in spurning_lower for w in ["flutt", "flyt", "búferla", "flutning", "karlar", "konur", "male", "woman",
                                         "women", "men", "female", "people", "moved", "migration", "move"]):
        oll_ar = sorted({k[0] for k in BUFERLA_GOGN})
        oll_svaedi = sorted({k[1] for k in BUFERLA_GOGN})
        timabil_texti = f"{oll_ar[0]}–{oll_ar[-1]}" if oll_ar else "?"
        arin = sorted(set(re.findall(r"\b(\d{4})\b", spurning_lower)))
        svaedin = finna_svaedi(spurning_lower)
        nefnir_hofudborg = any(h in spurning_lower for h in HOFUDBORG_ORD)
        fra_hofudborg = re.search(r"\b(?:frá|úr|from|out of|leaving|left)\s+(?:the\s+)?(?:höfuðborg|hofudborg|reykjav|reykjarv|reikjav|capital)", spurning_lower)
        daemi = "(t.d. Norðurland, Austurland, Suðurland, Vestfirðir, Suðurnes, útlönd)"

        if fra_hofudborg and not svaedin:
            athugasemdir.append("Gögnin ná aðeins yfir flutninga TIL höfuðborgarsvæðisins, ekki flutninga þaðan. "
                                f"Frá hvaða landsvæði viltu skoða flutninga til höfuðborgarsvæðisins? {daemi}")
            spyr_a_moti = True
        elif not svaedin and not nefnir_hofudborg:
            athugasemdir.append(f"Frá hvaða landsvæði viltu skoða flutninga til höfuðborgarsvæðisins? {daemi}")
            spyr_a_moti = True
        elif not arin:
            athugasemdir.append(f"Hvaða ár viltu skoða? Gögn um búferlaflutninga ná yfir árin {timabil_texti}.")
            spyr_a_moti = True
        else:
            heildin = not svaedin  # spurt um flutninga til höfuðborgarsvæðisins án upprunasvæðis
            if heildin:
                svaedin = [("öðrum landsvæðum og útlöndum", [s for s in oll_svaedi if s != "Höfuðborgarsvæði"])]
            for ar in arin:
                if ar not in oll_ar:
                    athugasemdir.append(f"Engin gögn um búferlaflutninga fyrir árið {ar}. Gögnin ná yfir {timabil_texti}.")
                    continue
                for heiti, svaedi in svaedin:
                    tolur = {kyn: sum(BUFERLA_GOGN.get((ar, sv, kyn), 0) for sv in svaedi)
                             for kyn in ("Alls", "Karlar", "Konur")}
                    texti = (f"Árið {ar} fluttu {tolur['Alls']} manns frá {heiti} til höfuðborgarsvæðisins, "
                             f"þar af {tolur['Karlar']} karlar og {tolur['Konur']} konur.")
                    if heildin:
                        texti += f" Þar af komu {BUFERLA_GOGN.get((ar, 'Útlönd', 'Alls'), 0)} frá útlöndum."
                    if tolur["Alls"] > 0:
                        texti += (f" Karlar voru {tolur['Karlar'] / tolur['Alls'] * 100:.1f}% og konur "
                                  f"{tolur['Konur'] / tolur['Alls'] * 100:.1f}% þeirra sem fluttu.").replace(".", ",", 2)
                    svor.append(texti)
            if svor:
                heimildir.append("Hagstofa Íslands – Búferlaflutningar milli landsvæða, til höfuðborgarsvæðisins")

    if svor:
        svar = skrifa_svar_med_ai(spurning, "\n".join(svor))
        if athugasemdir:
            svar += "\n\n" + "\n".join(athugasemdir)
        return {"svar": svar, "heimildir": heimildir, "spyr_a_moti": False}
    if athugasemdir:
        return {"svar": "\n".join(athugasemdir), "heimildir": [], "spyr_a_moti": spyr_a_moti}
    return {"svar": "Ég fann ekki gögn sem svara þessu. Ég get svarað spurningum um vísitölu neysluverðs og verðbólgu "
                    "(mánuður og ár) og búferlaflutninga til höfuðborgarsvæðisins (landsvæði og ár).",
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
