"""
Listi yfir töflur Hagstofunnar sem spjallmennið getur svarað úr.

Til að bæta við töflu: bættu við færslu hér og keyrðu `python ingest.py`.

Reitir í hverri töflu:
    kodi, slod   auðkenni og slóð töflunnar í PX-vefþjónustunni
    heiti        það sem talan mælir, eða dict {merki: heiti} ef það fer eftir mælikvarða
    eining       eining tölunnar, eða dict {merki: eining} ef hún fer eftir mælikvarða (sjá "maelikvardi")
    lysing       texti sem er geymdur sem vigur í ChromaDB svo hægt sé að finna töfluna út frá spurningu
    ord          leitarorð sem beina spurningu í töfluna (byrjun á orði; endar á $ ef allt orðið á að passa)
    sia          {vídd: [merki]} sækir aðeins þessi gildi, svo taflan haldist lítil
    sjalfgefid   {vídd: merki} ef spurningin nefnir ekki víddina (annars fyrsta merkið)
    samheiti     {vídd: {merki: [orð]}} orð sem velja gildi í vídd
    stadur       vídd með stöðum: merki þekkjast sjálfkrafa í spurningunni, þrátt fyrir beygingu
    summur       {vídd: {orð: [merki]}} orð sem leggja saman mörg gildi, t.d. Norðurland eystra og vestra
    maelikvardi  vídd sem segir hvað er mælt, merkið kemur alltaf fram í svarinu
    leggja_saman True ef óhætt er að leggja mánaðartölur saman í árstölu
"""

KYN = {"Karlar": ["karl", "men$", "male"], "Konur": ["kon", "kven", "women", "female"]}

MANUDIR_MERKI = {
    "Janúar": ["janúar", "januar", "january"], "Febrúar": ["febrúar", "februar", "february"],
    "Mars": ["mars$", "march$"], "Apríl": ["apríl", "april"], "Maí": ["maí", "may$"],
    "Júní": ["júní", "juni$", "june$"], "Júlí": ["júlí", "juli$", "july$"], "Ágúst": ["ágúst", "agust", "august"],
    "September": ["september"], "Október": ["október", "oktober", "october"],
    "Nóvember": ["nóvember", "november"], "Desember": ["desember", "december"],
}

# Bæir og beygingar sem þekkjast ekki á byrjun orðsins. Svarið nefnir alltaf sveitarfélagið sjálft.
SVEITARFELOG = {
    "Reykjavíkurborg": ["reykjav", "reikjav"],
    "Kópavogsbær": ["kópavog"],
    "Hafnarfjarðarkaupstaður": ["hafnarfj", "hafnarfirð"],
    "Akureyrarbær": ["akureyr"],
    "Ísafjarðarbær": ["ísafj", "ísafirð"],
    "Reykjanesbær": ["reykjanesb", "keflav", "njarðv"],
    "Sveitarfélagið Árborg": ["árborg", "selfoss"],
    "Sveitarfélagið Hornafjörður": ["hornafj", "hornafirð"],
    "Akraneskaupstaður": ["akranes"],
    "Borgarbyggð": ["borgarbyggð", "borgarnes"],
    "Múlaþing": ["múlaþing", "egilsst", "seyðisfj", "seyðisfirð"],
    "Norðurþing": ["norðurþing", "húsav"],
    "Fjarðabyggð": ["fjarðabyggð", "neskaupst", "eskifj", "eskifirð", "reyðarfj", "reyðarfirð"],
    "Vestmannaeyjabær": ["vestmannaey", "eyjum$"],
    "Mosfellsbær": ["mosfellsb"],
    "Skagafjörður": ["skagafj", "skagafirð", "sauðárkrók"],
}

LANDSHLUTAR_NORDURLAND = {"norðurland": ["Norðurland eystra", "Norðurland vestra"], "nordurland": ["Norðurland eystra", "Norðurland vestra"]}
LANDSHLUTAR = {
    "Höfuðborgarsvæðið": ["höfuðborg", "hofudborg", "capital"],
    "Höfuðborgarsvæði": ["höfuðborg", "hofudborg", "capital"],
    "Suðurnes": ["suðurnes$", "suðurnesjum$", "suðurnesja$", "sudurnes$", "reykjanes$", "reykjanesi$"],
    "Vestfirðir": ["vestfj", "vestfirð", "westfjord", "fjords?$"],
    "Norðurland eystra": ["norðurland eystra", "norðurlandi eystra", "norðurlands eystra", "norðaustur", "northeast"],
    "Norðurland vestra": ["norðurland vestra", "norðurlandi vestra", "norðurlands vestra", "norðvestur", "northwest"],
}

TOFLUR = [
    {
        "kodi": "MAN02005",
        "slod": "Ibuar/mannfjoldi/2_byggdir/sveitarfelog/MAN02005.px",
        "heiti": "Mannfjöldi 1. janúar",
        "eining": "manns",
        "lysing": "Mannfjöldi og íbúafjöldi eftir sveitarfélögum og kyni. Hvað búa margir í Reykjavík, á Akureyri, í Kópavogi? "
                  "Population of Icelandic municipalities and towns, number of inhabitants by sex.",
        "ord": ["búa$", "býr$", "íbúa", "íbúar", "mannfjöld", "population", "inhabitant", "live in", "lives in"],
        "sia": {"Aldur": ["Alls"]},
        "stadur": "Sveitarfélag",
        "samheiti": {"Sveitarfélag": SVEITARFELOG, "Kyn": {**KYN, "Kynsegin/annað": ["kynseg", "non-binary"]}},
    },
    {
        "kodi": "MAN03250",
        "slod": "Ibuar/mannfjoldi/2_byggdir/Byggdakjarnarhverfi/MAN03250.px",
        "heiti": "Mannfjöldi 1. janúar",
        "eining": "manns",
        "lysing": "Mannfjöldi eftir landshlutum: höfuðborgarsvæði, Suðurnes, Vesturland, Vestfirðir, Norðurland, Austurland, Suðurland. "
                  "Population of Icelandic regions by sex.",
        "ord": ["búa$", "býr$", "íbúa", "íbúar", "mannfjöld", "population", "inhabitant", "live in", "lives in"],
        "sia": {"Aldur": ["Alls"]},
        "stadur": "Landshlutar",
        "samheiti": {"Landshlutar": LANDSHLUTAR, "Kyn": KYN},
        "summur": {"Landshlutar": LANDSHLUTAR_NORDURLAND},
    },
    {
        "kodi": "MAN00000",
        "slod": "Ibuar/mannfjoldi/1_yfirlit/Yfirlit_mannfjolda/MAN00000.px",
        "heiti": {"Mannfjöldi 1. janúar": "Mannfjöldi á Íslandi 1. janúar", "Fjölgun": "Fjölgun mannfjölda á Íslandi",
                  "Fæddir umfram dána": "Fæddir umfram dána á Íslandi", "Aðfluttir umfram brottflutta": "Aðfluttir umfram brottflutta á Íslandi"},
        "eining": "manns",
        "lysing": "Lykiltölur mannfjöldans á Íslandi frá 1703: mannfjöldi 1. janúar, árleg fjölgun, aðfluttir umfram brottflutta og "
                  "fæddir umfram dána. Population of Iceland through history and population growth.",
        "ord": ["mannfjöld", "population", "íbúa", "íbúar", "fólksfjölg", "fjölgun", "fjölgaði", "growth"],
        "maelikvardi": "Eining",
        "sjalfgefid": {"Eining": "Mannfjöldi 1. janúar"},
        "samheiti": {"Eining": {"Fjölgun": ["fólksfjölg", "fjölgun", "fjölgaði", "growth"],
                                "Fæddir umfram dána": ["fæddir umfram"],
                                "Aðfluttir umfram brottflutta": ["aðfluttir umfram"]}},
    },
    {
        "kodi": "MAN01400",
        "slod": "Ibuar/buferlaflutningar/buferlaflmillilanda/MAN01400.px",
        "heiti": {"Aðfluttir": "Aðfluttir til Íslands", "Brottfluttir": "Brottfluttir frá Íslandi", "Aðfluttir umfram brottflutta": "Aðfluttir umfram brottflutta"},
        "eining": "manns",
        "lysing": "Búferlaflutningar milli landa eftir kyni og ríkisfangi. Aðfluttir og brottfluttir, íslenskir og erlendir ríkisborgarar. "
                  "Immigration and emigration to and from Iceland by citizenship.",
        "ord": ["ríkisborgar", "ríkisfang", "citizen", "til landsins", "frá landinu", "immigra", "emigra", "innflytj", "aðfluttir", "brottfluttir"],
        "maelikvardi": "Tegund flutnings",
        "sjalfgefid": {"Tegund flutnings": "Aðfluttir"},
        "samheiti": {"Kyn": KYN,
                     "Ríkisfang": {"Íslenskir ríkisborgarar": ["íslensk", "icelandic"], "Erlendir ríkisborgarar": ["erlend", "foreign"]},
                     "Tegund flutnings": {"Brottfluttir": ["brottflutt", "frá landinu", "emigra"],
                                          "Aðfluttir umfram brottflutta": ["umfram", "net migration"]}},
    },
    {
        "kodi": "MAN05100",
        "slod": "Ibuar/Faeddirdanir/Faeddir/faedingar/MAN05100.px",
        "heiti": {"Lifandi fæddir": "Lifandi fædd börn", "Andvana fæddir": "Andvana fædd börn"},
        "eining": "börn",
        "lysing": "Fædd börn á Íslandi á hverju ári eftir kyni, lifandi og andvana fæddir, einburar og tvíburar. "
                  "Number of children born in Iceland, births by sex.",
        "ord": ["fædd", "fæðing", "börn$", "barna$", "birth", "born$", "tvíbur", "twins", "andvana"],
        "maelikvardi": "Skipting",
        "samheiti": {"Kyn": {"Drengir": ["dreng", "strák", "boy"], "Stúlkur": ["stúlk", "stelp", "girl"]},
                     "Skipting": {"Andvana fæddir": ["andvana", "stillb"]},
                     "Fjöldi barna": {"Einburar": ["einbur"], "Tvíburar": ["tvíbur", "twins"], "Þríburar": ["þríbur", "triplets"], "Fjórburar": ["fjórbur"]}},
    },
    {
        "kodi": "MAN05210",
        "slod": "Ibuar/Faeddirdanir/danir/danir/MAN05210.px",
        "heiti": {"Fjöldi": "Dánir á Íslandi", "Á 1.000 íbúa": "Dánartíðni á Íslandi"},
        "eining": {"Fjöldi": "manns", "Á 1.000 íbúa": "á hverja þúsund íbúa"},
        "lysing": "Dánir á Íslandi á hverju ári eftir kyni og dánartíðni á 1.000 íbúa. Number of deaths in Iceland and death rate.",
        "ord": ["dán", "dauðsföll", "dauðsfall", "létust", "dóu$", "dó$", "deyja$", "deaths?$", "died$", "mortality"],
        "sia": {"Aldur": ["Alls"]},
        "maelikvardi": "Eining",
        "samheiti": {"Kyn": KYN, "Eining": {"Á 1.000 íbúa": ["dánartíðni", "death rate", "mortality"]}},
    },
    {
        "kodi": "VIN00921",
        "slod": "Samfelag/vinnumarkadur/vinnumarkadsrannsokn/3_arstolur/VIN00921.px",
        "heiti": {"Atvinnuleysi, % (Hlutfall af vinnuafli)": "Atvinnuleysi", "Atvinnulausir (Áætlaður fjöldi)": "Áætlaður fjöldi atvinnulausra"},
        "eining": {"Atvinnuleysi, % (Hlutfall af vinnuafli)": "% af vinnuafli", "Atvinnulausir (Áætlaður fjöldi)": "manns"},
        "lysing": "Atvinnuleysi á Íslandi eftir árum, hlutfall af vinnuafli og fjöldi atvinnulausra eftir kyni, aldri og landsvæði. "
                  "Unemployment rate and number of unemployed people in Iceland.",
        "ord": ["atvinnuleysi", "atvinnulaus", "unemploy", "jobless"],
        "maelikvardi": "Eining",
        "samheiti": {"Landsvæði": {"Utan höfuðborgarsvæðis": ["utan höfuðborg", "landsbyggð", "outside the capital"],
                                   "Höfuðborgarsvæði": ["höfuðborg", "capital"]},
                     "Kyn": KYN,
                     "Aldur": {"16-24 ára": ["16-24", "ungt fólk", "ungmenn", "young"], "25-54 ára": ["25-54"], "55-74 ára": ["55-74"],
                               "16-64 ára": ["16-64"], "25-64 ára": ["25-64"]},
                     "Eining": {"Atvinnulausir (Áætlaður fjöldi)": ["margir", "fjöldi", "how many", "number of"]}},
    },
    {
        "kodi": "VIN02002",
        "slod": "Samfelag/launogtekjur/1_laun/1_laun/VIN02002.px",
        "heiti": {"Heildarlaun - fullvinnandi": "Heildarlaun fullvinnandi launafólks", "Regluleg laun - fullvinnandi": "Regluleg laun fullvinnandi launafólks",
                  "Grunnlaun - fullvinnandi": "Grunnlaun fullvinnandi launafólks"},
        "eining": "þúsund krónur á mánuði",
        "lysing": "Mánaðarlaun á Íslandi eftir launþegahópi, starfsstétt og kyni: heildarlaun, regluleg laun og grunnlaun, meðaltal og miðgildi. "
                  "Monthly wages and salaries in Iceland by occupation and sex, average and median pay.",
        "ord": ["laun", "meðallaun", "mánaðarlaun", "heildarlaun", "grunnlaun", "miðgildi launa", "salary", "salaries", "wage", "earn"],
        "sia": {"Laun og vinnutími": ["Heildarlaun - fullvinnandi", "Regluleg laun - fullvinnandi", "Grunnlaun - fullvinnandi"],
                "Eining": ["Meðaltal", "Miðgildi"]},
        "maelikvardi": "Laun og vinnutími",
        "sjalfgefid": {"Laun og vinnutími": "Heildarlaun - fullvinnandi"},
        "syna_alltaf": ["Eining"],
        "samheiti": {"Kyn": KYN,
                     "Launþegahópur": {"Starfsmenn á almennum vinnumarkaði": ["almenn"],
                                       "Opinberir starfsmenn - ríkisstarfsmenn": ["ríkisstarf"],
                                       "Opinberir starfsmenn - starfsmenn sveitarfélaga": ["sveitarfélag"],
                                       "Opinberir starfsmenn - alls": ["opinber"]},
                     "Starfsstétt": {"Stjórnendur (1)": ["stjórnend", "manager"], "Sérfræðingar (2)": ["sérfræðing", "professional"],
                                     "Tæknar og sérmenntað starfsfólk (3)": ["tækn", "technician"], "Skrifstofufólk (4)": ["skrifstof", "clerical"],
                                     "Þjónustu-, sölu- og afgreiðslufólk (5)": ["þjónustu", "afgreiðslu", "sölufólk"],
                                     "Iðnaðarmenn": ["iðnaðarm", "craft"], "Verkafólk": ["verkafólk", "verkamen", "labourer", "laborer"]},
                     "Laun og vinnutími": {"Regluleg laun - fullvinnandi": ["regluleg"], "Grunnlaun - fullvinnandi": ["grunnlaun", "base pay"]},
                     "Eining": {"Miðgildi": ["miðgildi", "median"]}},
    },
    {
        "kodi": "THJ01102",
        "slod": "Efnahagur/thjodhagsreikningar/landsframl/1_landsframleidsla/THJ01102.px",
        "heiti": {"1. Einkaneysla": "Einkaneysla", "2. Samneysla": "Samneysla", "3. Fjármunamyndun": "Fjármunamyndun", "5. Þjóðarútgjöld": "Þjóðarútgjöld",
                  "6. Útflutningur alls": "Útflutningur", "7. Frádráttur: Innflutningur alls": "Innflutningur",
                  "8. Verg landsframleiðsla": "Verg landsframleiðsla", "10. Vergar þjóðartekjur": "Vergar þjóðartekjur"},
        "eining": "milljónir króna á verðlagi hvers árs",
        "lysing": "Verg landsframleiðsla og þjóðartekjur Íslands á verðlagi hvers árs, einkaneysla, samneysla, fjármunamyndun, útflutningur "
                  "og innflutningur. Gross domestic product GDP of Iceland, national income, consumption, exports and imports.",
        "ord": ["landsframleið", "gdp$", "gross domestic", "þjóðartekj", "national income", "einkaneysl", "samneysl", "fjármunamynd", "þjóðarútgjöld"],
        "sia": {"Skipting": ["1. Einkaneysla", "2. Samneysla", "3. Fjármunamyndun", "5. Þjóðarútgjöld", "6. Útflutningur alls",
                             "7. Frádráttur: Innflutningur alls", "8. Verg landsframleiðsla", "10. Vergar þjóðartekjur"]},
        "maelikvardi": "Skipting",
        "sjalfgefid": {"Skipting": "8. Verg landsframleiðsla"},
        "samheiti": {"Skipting": {"1. Einkaneysla": ["einkaneysl", "household consumption"], "2. Samneysla": ["samneysl"],
                                  "3. Fjármunamyndun": ["fjármunamynd"], "5. Þjóðarútgjöld": ["þjóðarútgjöld"],
                                  "6. Útflutningur alls": ["útflutning", "exports"], "7. Frádráttur: Innflutningur alls": ["innflutning", "imports"],
                                  "10. Vergar þjóðartekjur": ["þjóðartekj", "national income"]}},
    },
    {
        "kodi": "THJ01401",
        "slod": "Efnahagur/thjodhagsreikningar/landsframl/1_landsframleidsla/THJ01401.px",
        "heiti": {"Þúsundir króna": "Landsframleiðsla á mann", "USD, skráð gengi": "Landsframleiðsla á mann", "USD, jafnvirðisgildi": "Landsframleiðsla á mann",
                  "Evra, skráð gengi": "Landsframleiðsla á mann", "Evra, jafnvirðisgildi": "Landsframleiðsla á mann"},
        "eining": {"Þúsundir króna": "þúsund krónur", "USD, skráð gengi": "bandaríkjadalir á skráðu gengi", "USD, jafnvirðisgildi": "bandaríkjadalir á jafnvirðisgildi",
                   "Evra, skráð gengi": "evrur á skráðu gengi", "Evra, jafnvirðisgildi": "evrur á jafnvirðisgildi"},
        "lysing": "Landsframleiðsla á mann á Íslandi í krónum, dollurum og evrum. GDP per capita of Iceland.",
        "ord": ["á mann", "per capita", "landsframleiðsl", "gdp$"],
        "maelikvardi": "Mælikvarði",
        "samheiti": {"Mælikvarði": {"USD, skráð gengi": ["dollar", "usd"], "Evra, skráð gengi": ["evr", "euro"]}},
        "aukavaegi": ["á mann", "per capita"],
    },
    {
        "kodi": "SAM01601",
        "slod": "Atvinnuvegir/ferdathjonusta/Gisting/3_allartegundirgististada/SAM01601.px",
        "heiti": {"Gistinætur": "Gistinætur á skráðum gististöðum", "Gestakomur": "Gestakomur á skráðum gististöðum"},
        "eining": {"Gistinætur": "gistinætur", "Gestakomur": "gestakomur"},
        "lysing": "Gistinætur og gestakomur á öllum tegundum skráðra gististaða eftir landshlutum, mánuðum og hvort gestir eru Íslendingar eða útlendingar. "
                  "Overnight stays and guest arrivals at registered accommodation in Iceland by region.",
        "ord": ["gistin", "gestakom", "overnight", "guest", "gisting"],
        "sia": {"Þjóðerni": ["Alls", "Ísland", "Útlendingar"]},
        "stadur": "Landshluti",
        "maelikvardi": "Eining",
        "samheiti": {"Landshluti": LANDSHLUTAR, "Þjóðerni": {"Útlendingar": ["útlending", "erlend", "foreign"], "Ísland": ["íslending", "icelander"]},
                     "Eining": {"Gestakomur": ["gestakom", "guest", "arrivals"]}, "Mánuður": MANUDIR_MERKI},
        "summur": {"Landshluti": LANDSHLUTAR_NORDURLAND},
    },
    {
        "kodi": "SAM02001",
        "slod": "Atvinnuvegir/ferdathjonusta/farthegar/1_farthegar/SAM02001.px",
        "heiti": "Farþegar um Keflavíkurflugvöll",
        "eining": "farþegar",
        "lysing": "Farþegar um Keflavíkurflugvöll eftir ríkisfangi og mánuðum, Íslendingar og útlendingar, fjöldi ferðamanna. "
                  "Passengers through Keflavík airport, number of foreign tourists visiting Iceland.",
        "ord": ["farþeg", "keflavíkurflugv", "ferðam", "passenger", "tourist", "keflavik airport"],
        "sia": {"Ríkisfang": ["Farþegar alls", "Ísland", "Útlendingar alls"]},
        "samheiti": {"Ríkisfang": {"Útlendingar alls": ["ferðam", "tourist", "útlending", "erlend", "foreign"], "Ísland": ["íslending", "icelander"]}},
        "leggja_saman": True,
    },
    {
        # Notað af búferlaflutningahlutanum í app.py, en ekki af almennu leitinni
        "kodi": "MAN01002",
        "slod": "Ibuar/buferlaflutningar/buferlaflinnanlands/buferlaflinnanlands/MAN01002.px",
        "heiti": "Búferlaflutningar milli landsvæða",
        "eining": "manns",
        "lysing": "Búferlaflutningar milli landsvæða á Íslandi eftir kyni. Domestic migration between regions of Iceland.",
        "ord": [],
        "sia": {"Aldur": ["Alls"]},
        "adeins_serhlutur": True,
    },
]
