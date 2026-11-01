"""
Almenn uppfletting í töflum Hagstofunnar.

Vigurleit og leitarorð finna rétta töflu út frá spurningunni. Síðan eru merki töflunnar (ár, staður, kyn...)
pöruð við spurninguna og talan sótt nákvæmlega úr SQLite. Líkanið kemur hvergi nálægt tölunum hér.
"""
import itertools
import os
import re
import sqlite3

import chromadb

from toflur import TOFLUR

GOGN_DIR = "gogn"
DB_PATH = os.path.join(GOGN_DIR, "hagstofa.db")
LEIT_NAFN = "hagstofa_toflur"

# Lágmarkslíkindi fyrir vigurleit ef ekkert leitarorð passar
LAGMARK_LIKINDA = 0.55
VAEGI_ORDS = 0.5
VAEGI_STADAR = 0.5
HAMARK_LINA = 12

TOFLUR_EFTIR_KODA = {t["kodi"]: t for t in TOFLUR}
GOGN = {}  # kodi -> {"titill", "viddir": [(nafn, er_timi, [merki])], "gildi": {(merki...): gildi}}
leit = None

MANADA_HEITI = ["janúar", "febrúar", "mars", "apríl", "maí", "júní", "júlí", "ágúst", "september", "október", "nóvember", "desember"]
ORD_SEM_ERU_EKKI_STADIR = {"íslandi", "ísland", "iceland", "landinu", "ári", "árinu", "árið", "fyrra"}


def hlada_gogn(embed_model):
    """Les allar töflur í minni og byggir töfluleitina. Skilar fjölda taflna, eða 0 ef ingest.py hefur ekki verið keyrt."""
    global leit
    if not os.path.exists(DB_PATH):
        print("⚠️ Fann ekki gogn/hagstofa.db. Keyrðu: python ingest.py")
        return 0

    con = sqlite3.connect(DB_PATH)
    for kodi, titill in con.execute("SELECT kodi, titill FROM toflur").fetchall():
        viddir = [(nafn, bool(er_timi), merki.split("\x1f")) for nafn, er_timi, merki in
                  con.execute("SELECT nafn, er_timi, merki FROM viddir WHERE kodi = ? ORDER BY rod", (kodi,))]
        gildi = {tuple(lykill.split("\x1f")): g for lykill, g in
                 con.execute("SELECT lykill, gildi FROM gildi WHERE kodi = ?", (kodi,))}
        GOGN[kodi] = {"titill": titill, "viddir": viddir, "gildi": gildi}
    con.close()

    # Leitin er aðeins í minni: ChromaDB breytir skránum sínum við ræsingu, svo þær eiga ekki heima í git
    toflur = [t for t in TOFLUR if t["kodi"] in GOGN and not t.get("adeins_serhlutur")]
    lysingar = [t["lysing"] for t in toflur]
    leit = chromadb.EphemeralClient().get_or_create_collection(LEIT_NAFN, metadata={"hnsw:space": "cosine"})
    leit.upsert(ids=[t["kodi"] for t in toflur], documents=lysingar,
                embeddings=embed_model.encode(lysingar, normalize_embeddings=True).tolist())
    return len(GOGN)


def _passar(ord_i_lista, texti):
    # Orð í toflur.py eru byrjun á orði, nema þau endi á $ og þá verður allt orðið að passa
    if ord_i_lista.endswith("$"):
        return re.search(r"\b" + ord_i_lista[:-1] + r"\b", texti) is not None
    return re.search(r"\b" + re.escape(ord_i_lista), texti) is not None


def _hreinsa_merki(merki):
    # "8. Verg landsframleiðsla" -> "Verg landsframleiðsla", "Stjórnendur (1)" -> "Stjórnendur"
    merki = re.sub(r"^\d+(\.\d+)?\.?\s+", "", merki)
    merki = re.sub(r"^Frádráttur:\s*", "", merki)
    return re.sub(r"\s*\(\d+\)$", "", merki)


def _sameiginleg_byrjun(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _finna_stadi(tafla, vidd, merki_listi, texti):
    """Skilar völdum stöðum [(heiti, [merki], nákvæmni 0-1)] úr spurningunni: fyrst samheiti og summur, svo beygð orð."""
    fundid = []
    samheiti = tafla.get("samheiti", {}).get(vidd, {})
    for merki in sorted(merki_listi, key=len, reverse=True):
        for s in samheiti.get(merki, []):
            if _passar(s, texti):
                fundid.append((merki, [merki], 1.0))
                texti = re.sub(r"\b" + re.escape(s.rstrip("$")) + r"\w*", " ", texti)
                break
    for ord_i_lista, summa in tafla.get("summur", {}).get(vidd, {}).items():
        summa = [m for m in summa if m in merki_listi]
        if summa and _passar(ord_i_lista, texti):
            fundid.append((" og ".join(summa), summa, 1.0))
            texti = re.sub(r"\b" + re.escape(ord_i_lista) + r"\w*", " ", texti)

    # Öll orð í merkinu verða að finnast, svo "Rangárþing ytra" teljist ekki vera "Rangárþing eystra"
    ord_i_texta = re.findall(r"\w{4,}", texti)
    for merki in merki_listi:
        if merki.lower() in ("alls", "allt landið"):
            continue
        ord_merkis = [o for o in re.findall(r"\w+", merki.lower()) if o not in ("sveitarfélagið", "og")]
        nakvaemni = []
        for o in ord_merkis:
            bestu = [_sameiginleg_byrjun(t, o) / max(len(t), len(o)) for t in ord_i_texta
                     if _sameiginleg_byrjun(t, o) / min(len(t), len(o)) >= 0.8]
            nakvaemni.append(max(bestu, default=None))
        if ord_merkis and None not in nakvaemni:
            fundid.append((merki, [merki], min(nakvaemni)))
    # Sami staður getur fundist tvisvar, t.d. með samheiti og beygðu orði
    return list({s[0]: s for s in reversed(fundid)}.values())


def _ord_til_stadfestingar(merki):
    # Upphaf nafnsins á staðnum, svo beygð mynd standist líka, t.d. "akure" í "Akureyri" og "Akureyrarbær"
    return merki.lower().replace("sveitarfélagið ", "").split()[0][:5]


def _nefndir_stadir(spurning):
    """Orð með stórum staf á eftir í/á/in, til að taka eftir stöðum sem taflan þekkir ekki."""
    ord_listi = re.findall(r"(?:\bí|\bá|\bin|\bat)\s+([A-ZÁÐÉÍÓÚÝÞÆÖ][\wáðéíóúýþæö-]+)", spurning)
    return [o for o in ord_listi if o.lower() not in ORD_SEM_ERU_EKKI_STADIR and not o.isdigit()]


def _velja_vidd(tafla, nafn, merki_listi, texti):
    """Skilar völdum merkjum víddar í spurningunni, eða sjálfgefnu merki. Skilar líka hvort þau voru valin."""
    valin = []
    samheiti = tafla.get("samheiti", {}).get(nafn, {})
    for merki in sorted(merki_listi, key=len, reverse=True):
        if merki in samheiti and any(_passar(s, texti) for s in samheiti[merki]):
            valin.append(merki)
            for s in samheiti[merki]:
                texti = re.sub(r"\b" + re.escape(s.rstrip("$")) + r"\w*", " ", texti)
    if valin:
        return [m for m in merki_listi if m in valin], True
    sjalfgefid = tafla.get("sjalfgefid", {}).get(nafn, merki_listi[0])
    return [sjalfgefid], False


def _snid(gildi):
    return str(int(gildi)) if float(gildi).is_integer() else str(gildi).replace(".", ",")


def _finna_timabil(gogn, tafla, spurning_lower, finna_timabil):
    """Skilar ([(heiti, [gildi á tímavídd])], ártöl sem vantar). Tekur nýjasta ár með gögn ef ekkert er nefnt."""
    timi_i = next(i for i, v in enumerate(gogn["viddir"]) if v[1])
    allir = gogn["viddir"][timi_i][2]
    er_manadartafla = "M" in allir[0]
    timabil, _, _ = finna_timabil(spurning_lower)
    arin = list(dict.fromkeys(re.findall(r"\b(1[5-9]\d\d|20\d\d)\b", spurning_lower)))
    til = [a for a in allir if any(g is not None for k, g in gogn["gildi"].items() if k[timi_i] == a)]

    if er_manadartafla:
        ar_med_gogn = sorted({a[:4] for a in til})
        vantar = [a for a in arin if a not in ar_med_gogn]
        if timabil:
            return [(a, [a]) for a in timabil if a in til], [t[:4] for t in timabil if t not in til]
        if not arin:
            heil_ar = [a for a in ar_med_gogn if sum(t[:4] == a for t in til) == 12]
            arin = [heil_ar[-1]] if heil_ar else ar_med_gogn[-1:]
        return [(a, [t for t in til if t[:4] == a]) for a in arin if a in ar_med_gogn], vantar

    vantar = [a for a in arin if a not in til]
    if not arin:
        arin = til[-1:]
    return [(a, [a]) for a in arin if a in til], vantar


def _heiti_timabils(timi):
    if "M" in timi:
        return f"í {MANADA_HEITI[int(timi[5:]) - 1]} {timi[:4]}"
    return f"árið {timi}"


def finna_toflur(spurning_lower, embed_model):
    """Raðar töflum eftir vigurleit og leitarorðum. Skilar [(stig, kodi)], bestu fyrst."""
    likindi = {}
    if leit is not None:
        vigur = embed_model.encode([spurning_lower], normalize_embeddings=True).tolist()
        svar = leit.query(query_embeddings=vigur, n_results=leit.count())
        likindi = {k: 1 - f for k, f in zip(svar["ids"][0], svar["distances"][0])}

    rod = []
    for tafla in TOFLUR:
        if tafla.get("adeins_serhlutur") or tafla["kodi"] not in GOGN:
            continue
        ord_passa = sum(_passar(o, spurning_lower) for o in tafla["ord"])
        likur = likindi.get(tafla["kodi"], 0)
        if not ord_passa and likur < LAGMARK_LIKINDA:
            continue
        stig = likur + VAEGI_ORDS * ord_passa + VAEGI_ORDS * sum(_passar(o, spurning_lower) for o in tafla.get("aukavaegi", []))
        if tafla.get("stadur"):
            stadir = _finna_stadi(tafla, tafla["stadur"], GOGN[tafla["kodi"]]["viddir"][_vidd_nr(tafla)][2], spurning_lower)
            stig += VAEGI_STADAR * max((s[2] for s in stadir), default=0)
        rod.append((stig, tafla["kodi"]))
    return sorted(rod, reverse=True)


def _vidd_nr(tafla):
    return next(i for i, v in enumerate(GOGN[tafla["kodi"]]["viddir"]) if v[0] == tafla["stadur"])


def svara(spurning, embed_model, finna_timabil):
    """Skilar dict með svor, heimildir, athugasemdir, spyr_a_moti og skyld_ord, eða None ef engin tafla á við."""
    spurning_lower = spurning.lower()
    rodun = finna_toflur(spurning_lower, embed_model)
    if not rodun:
        return None

    ekki_til = None
    for _, kodi in rodun:
        tafla, gogn = TOFLUR_EFTIR_KODA[kodi], GOGN[kodi]
        timabil, vantar = _finna_timabil(gogn, tafla, spurning_lower, finna_timabil)
        if vantar or not timabil:
            ar_listi = sorted({m[:4] for m in next(v[2] for v in gogn["viddir"] if v[1])})
            ekki_til = ekki_til or f"Engin gögn um þetta fyrir {', '.join(vantar) or 'þetta tímabil'} í töflunni „{gogn['titill']}“. Gögnin ná yfir {ar_listi[0]}–{ar_listi[-1]}."
            continue
        return _svara_ur_toflu(spurning, spurning_lower, tafla, gogn, timabil)
    return {"svor": [], "heimildir": [], "athugasemdir": [ekki_til], "spyr_a_moti": False, "skyld_ord": []}


def _svara_ur_toflu(spurning, spurning_lower, tafla, gogn, timabil):
    val = []
    skyld_ord = []
    stadur_fannst = False
    syna_alltaf = set(tafla.get("syna_alltaf", []))
    if tafla.get("maelikvardi"):
        syna_alltaf.add(tafla["maelikvardi"])

    for nafn, er_timi, merki_listi in gogn["viddir"]:
        if er_timi:
            val.append([("", None)])
        elif nafn == tafla.get("stadur"):
            stadir = _finna_stadi(tafla, nafn, merki_listi, spurning_lower)
            if stadir:
                stadur_fannst = True
                skyld_ord.extend(_ord_til_stadfestingar(s[0]) for s in stadir)
                val.append(stadir)
            else:
                val.append([("", [merki_listi[0]])])
        else:
            valin, nefnt = _velja_vidd(tafla, nafn, merki_listi, spurning_lower)
            synilegt = nefnt or nafn in syna_alltaf
            if nafn == tafla.get("maelikvardi") and isinstance(tafla["heiti"], dict):
                synilegt = False
            val.append([(_hreinsa_merki(m) if synilegt else "", [m]) for m in valin])

    athugasemdir = []
    ekki_thekkt = [] if stadur_fannst else _nefndir_stadir(spurning)
    if ekki_thekkt and tafla.get("stadur"):
        daemi = next(v[2] for v in gogn["viddir"] if v[0] == tafla["stadur"])[1:4]
        return {"svor": [], "heimildir": [], "spyr_a_moti": True, "skyld_ord": [],
                "athugasemdir": [f"Ég fann ekki „{ekki_thekkt[0]}“ í töflunni „{gogn['titill']}“. Hvaða stað áttu við? (t.d. {', '.join(daemi)})"]}
    if ekki_thekkt:
        athugasemdir.append(f"Athugaðu: þessi tala gildir um allt landið, því gögnin ná ekki niður á „{ekki_thekkt[0]}“.")

    timi_i = next(i for i, v in enumerate(gogn["viddir"]) if v[1])
    maelikvardi_i = next((i for i, v in enumerate(gogn["viddir"]) if v[0] == tafla.get("maelikvardi")), None)
    svor = []
    for timi_heiti, timar in timabil:
        for samsetning in itertools.product(*val):
            maelikvardi_merki = samsetning[maelikvardi_i][1][0] if maelikvardi_i is not None else None
            eining = tafla["eining"].get(maelikvardi_merki, "") if isinstance(tafla["eining"], dict) else tafla["eining"]
            samtals, vantar_gildi = 0.0, False
            for lyklar in itertools.product(*(timar if i == timi_i else s[1] for i, s in enumerate(samsetning))):
                g = gogn["gildi"].get(tuple(lyklar))
                if g is None:
                    vantar_gildi = True
                else:
                    samtals += g
            merki_texti = ", ".join(s[0] for s in samsetning if s[0])
            heiti = tafla["heiti"].get(maelikvardi_merki, "") if isinstance(tafla["heiti"], dict) else tafla["heiti"]
            lysing = f"{heiti} {_heiti_timabils(timi_heiti)}" + (f" ({merki_texti})" if merki_texti else "")
            if vantar_gildi:
                svor.append(f"{lysing}: engin tala er birt fyrir þetta.")
            elif tafla.get("leggja_saman") and len(timar) > 1:
                svor.append(f"{lysing}: {_snid(samtals)} {eining} samtals yfir {len(timar)} mánuði.")
            else:
                svor.append(f"{lysing}: {_snid(samtals)} {eining}.")

    if len(svor) > HAMARK_LINA:
        athugasemdir.append(f"Sýni fyrstu {HAMARK_LINA} af {len(svor)} niðurstöðum.")
        svor = svor[:HAMARK_LINA]
    return {"svor": svor, "heimildir": [f"Hagstofa Íslands – {gogn['titill']} ({tafla['kodi']})"],
            "athugasemdir": athugasemdir, "spyr_a_moti": False, "skyld_ord": list(dict.fromkeys(skyld_ord))}
