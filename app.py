#app_multiple_quiery
import chromadb
from sentence_transformers import SentenceTransformer
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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

    print("🚀 Allar spegilmyndir hlaðnar í RAM!")


def finna_tolur(texti):
    # Fjarlægjum þúsundapunkta svo 17.594 og 17594 teljist sama talan
    texti = re.sub(r"\b(\d{1,3})\.(\d{3})\b", r"\1\2", texti)
    return {t.replace(",", ".") for t in re.findall(r"\d+(?:[.,]\d+)?", texti)}


def naudsynlegar_tolur(texti):
    # Grunnur, gagnabil, kynjahlutföll og stig á bak við verðbólgu mega koma fram en þurfa þess ekki
    for valfrjalst in (r"\s*\(grunnur 1988\)", r"Gögnin ná frá [^.]*\.", r"Karlar voru [^.]*\.", r"\s*\(úr [^)]*\)"):
        texti = re.sub(valfrjalst, "", texti)
    return finna_tolur(texti)


def skrifa_svar_med_ai(spurning, founn_texti):
    system_prompt = (
        "Þú ert reynslumikill hagfræðingur og upplýsingafulltrúi hjá Hagstofunni. "
        "Verkefni þitt er að svara spurningum á skýran, mannlegan og faglegan máta út frá gefnum tölum. "
        "Þó að spurning gæti verið á ensku, SKALT þú ávallt svara á lýsandi og vandaðri íslensku. "
        "BREYTTU alltaf orðalagi og setningagerð milli svara svo þau hljómi eðlilega og fjölbreytt. "
        "Ekki nota alltaf sama sniðmátið. Gerðu svarið læsilegt og aldrei skrifa bara eina tölu. "
        "Taktu fram allar tölurnar úr samhenginu óbreyttar og reiknaðu aldrei nýjar tölur eða hlutföll. "
        "Bættu engu við sem kemur ekki fram í samhenginu, hvorki breytingum, ástæðum né samanburði. "
        "Ef samhengið segir að gögn eða upplýsingar vanti skaltu segja það og ekki giska. "
        "Skrifaðu aðeins svarið sjálft, án athugasemda um svarið eða tungumálið."
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
            if svar and naudsynlegar_tolur(founn_texti) <= tolur <= finna_tolur(founn_texti):
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
    svor = []

    # 1. Athugum hvort spurt sé um vísitölu neysluverðs
    if any(w in spurning_lower for w in ["vísitala", "vísitöl", "neyslu", "cpi", "price index", "index", "verðbólg", "inflation"]):
        svor.append(svara_visitolu(spurning_lower))

    # 2. Búferlaflutningar
    if any(w in spurning_lower for w in ["fluttu", "búferla", "flutning", "karlar", "konur", "male", "woman", "women", "males", "men", "female", "females", "people", "moved", "migration"]):
        valinn_ar = None
        for word in spurning_lower.split():
            clean = word.strip("?.,!")
            if clean.isdigit() and len(clean) == 4:
                valinn_ar = clean

        # Undirsvæði Norðurlands koma fyrst svo "norðausturland" teljist ekki vera Austurland
        svæða_listi = ["norðurland eystra", "norðurland vestra",
                        "suðurland", "suðurnes", "austurland", "vesturland", "vestfirðir",
                        "norðurland", "höfuðborgarsvæði"]

        fundin_svæði = [s for s in svæða_listi if any(heiti in spurning_lower for heiti in [s, SVAEDI_THAGUFALL.get(s, s).lower()] + SVAEDI_ONNUR_HEITI.get(s, []))]
        
        sudur = ["south", "southern"]
        nordur = ["north", "northern"]
        east = ["east", "eastern"]
        west = ["west", "western"]
        reykjavik_orð = ["reykjavík", "reykjavikur", "reykjavik", "reykjavíkk", "reykjavikk", "reykjarvík", "reykjavíkur", "reikjavík", "capital", "reykjavik", "höfuðborg", "hofudborg"]
        
        if any(r in spurning_lower for r in sudur) and not fundin_svæði:
            fundin_svæði = ["suðurland"]
        if any(r in spurning_lower for r in east) and not fundin_svæði:
            fundin_svæði = ["austurland"]
        if any(r in spurning_lower for r in west) and not fundin_svæði:
            fundin_svæði = ["vesturland"]
        if any(r in spurning_lower for r in nordur) and not fundin_svæði:
            fundin_svæði = ["norðurland"]
        if any(r in spurning_lower for r in reykjavik_orð) and not fundin_svæði:
            fundin_svæði = ["höfuðborgarsvæði"]

        # Gögnin ná aðeins yfir flutninga til höfuðborgarsvæðis, ekki frá því
        er_höfuðborg = bool(fundin_svæði) and fundin_svæði[0] == "höfuðborgarsvæði"
        frá_höfuðborg = er_höfuðborg and re.search(r"\b(?:frá|úr|from|out of|leaving|left)\s+(?:the\s+)?(?:höfuðborg|reykjav|reykjarv|reikjav|capital)", spurning_lower)

        if frá_höfuðborg:
            svor.append("Gögnin ná aðeins yfir flutninga til höfuðborgarsvæðisins, ekki flutninga þaðan, svo ekki er hægt að svara þessu út frá þeim.")
        elif valinn_ar and fundin_svæði:
            valin_svæði = fundin_svæði[0]
            uppruna_svæði = [valin_svæði]
            # Norðurland er tvö svæði í gögnunum, svo við leggjum þau saman nema spurt sé um annað þeirra
            if valin_svæði == "norðurland":
                if re.search(r"norðurland\w*\s+(eystra|austur)", spurning_lower):
                    valin_svæði = "norðurland eystra"
                    uppruna_svæði = [valin_svæði]
                elif re.search(r"norðurland\w*\s+(vestra|vestur)", spurning_lower):
                    valin_svæði = "norðurland vestra"
                    uppruna_svæði = [valin_svæði]
                else:
                    uppruna_svæði = ["norðurland eystra", "norðurland vestra"]

            niðurstöður = {"alls": 0.0, "karlar": 0.0, "konur": 0.0}
            frá_útlöndum = 0.0
            documents, metadatas = [], []
            batch_size, offset = 2000, 0
        
            while True:
                results = collection.get(where={"gagnasett": "buferlaflutningar"}, limit=batch_size, offset=offset, include=['documents', 'metadatas'])
                batch_docs, batch_metas = results.get('documents', []), results.get('metadatas', [])
                if not batch_docs: break
                documents.extend(batch_docs)
                metadatas.extend(batch_metas)
                offset += batch_size
                if len(batch_docs) < batch_size: break

            for doc, meta in zip(documents, metadatas):
                doc_lower = doc.lower()
                if f"ár: {valinn_ar}" in doc_lower and (er_höfuðborg or any(f"brottflutningssvæði: {s} - " in doc_lower for s in uppruna_svæði)):
                    try:
                        val = float(str(meta.get('gildi') or meta.get('fjöldi') or '0').replace(',', '.'))
                        if "aldur: alls" in doc_lower or "aldur:alls" in doc_lower:
                            if "alls" in doc_lower and "karl" not in doc_lower and "kon" not in doc_lower:
                                niðurstöður["alls"] += val
                                if "brottflutningssvæði: útlönd - " in doc_lower:
                                    frá_útlöndum += val
                            elif "karl" in doc_lower and "kon" not in doc_lower:
                                niðurstöður["karlar"] += val
                            elif ("konur" in doc_lower or "kona" in doc_lower) and "karl" not in doc_lower:
                                niðurstöður["konur"] += val
                    except ValueError: 
                        pass
        
            if niðurstöður["alls"] == 0: 
                niðurstöður["alls"] = niðurstöður["karlar"] + niðurstöður["konur"]
        
            if er_höfuðborg:
                buferla_texti = f"Heildarfjöldi þeirra sem fluttu til Höfuðborgarsvæðis árið {valinn_ar} var {int(niðurstöður['alls'])} (þar af {int(niðurstöður['karlar'])} karlar og {int(niðurstöður['konur'])} konur). Þar af komu {int(frá_útlöndum)} frá útlöndum."
            else:
                buferla_texti = f"Heildarfjöldi þeirra sem fluttu frá {SVAEDI_THAGUFALL.get(valin_svæði, valin_svæði.capitalize())} árið {valinn_ar} var {int(niðurstöður['alls'])} (þar af {int(niðurstöður['karlar'])} karlar og {int(niðurstöður['konur'])} konur)."
            if niðurstöður["alls"] > 0:
                karla_hlutfall = f"{niðurstöður['karlar'] / niðurstöður['alls'] * 100:.1f}".replace(".", ",")
                kvenna_hlutfall = f"{niðurstöður['konur'] / niðurstöður['alls'] * 100:.1f}".replace(".", ",")
                buferla_texti += f" Karlar voru {karla_hlutfall}% og konur {kvenna_hlutfall}% þeirra sem fluttu."
            svor.append(buferla_texti)

    if svor:
        lokatexti = "\n".join(svor)
        return skrifa_svar_med_ai(spurning, lokatexti)
    else:
        return "Gat ekki túlkað fyrirspurnina eða fundið gögn út frá tiltæku metadata."

class SpurningRequest(BaseModel):
    spurning: str

@app.post("/spyrja")
def spyrja_vefthjon(req: SpurningRequest):
    return {"svar": spyrja_beint(req.spurning)}
