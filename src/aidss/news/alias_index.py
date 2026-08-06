"""What Indonesian issuers are actually called in print.

The registered name is almost never it. Coverage says "BCA", not "PT Bank
Central Asia Tbk"; it says "Indomie" when the issuer is Indofood CBP, and
"Tolak Angin" when it is Sido Muncul. Derivation from the registered name
cannot reach any of these - the letters simply are not there - and the attempt
to reach them mechanically, by taking initials, produced eight wrong aliases
for every right one (see `derive_aliases`).

So this is a hand-written index, and it is knowledge rather than an algorithm.
Each entry is a claim that a specific string, in Indonesian market coverage,
means a specific issuer.

What is deliberately **not** here:

  * **Single ordinary words.** ARTO is "Bank Jago", never "Jago" - *jago* means
    champion. TINS is "PT Timah", never "Timah" - *timah* is the metal, and the
    commodity is written about constantly without the company being involved.
    GIAA is "Garuda Indonesia", never "Garuda" - the national symbol and the
    football team share it.
  * **Two-letter forms.** "XL" for EXCL matches too much prose to be worth the
    recall.
  * **Anything ambiguous between two issuers.** A name two companies answer to
    identifies neither, and a guessed tag puts another company's news into the
    evidence an analysis reasons from.

Subsidiaries and product brands are included where the story is genuinely about
the listed parent: an article about Telkomsel's tariffs is about TLKM's revenue,
and one about Indomie's pricing is about ICBP's margin.

Validated by `test_alias_index.py` rather than by inspection: every entry must
survive the same usability rules as any other alias, no string may be claimed by
two issuers, and none may collide with a ticker code.
"""

from __future__ import annotations

#: ticker -> the names that mean it. Lower case; matching normalises anyway.
CURATED_ALIASES: dict[str, tuple[str, ...]] = {
    # --- banks, where the initialism is the everyday name -------------------
    "BBCA": ("bca", "bank central asia"),
    "BBRI": ("bri", "bank rakyat indonesia", "bank bri"),
    "BBNI": ("bni", "bank negara indonesia", "bank bni"),
    "BMRI": ("bank mandiri",),
    "BBTN": ("btn", "bank tabungan negara", "bank btn"),
    "BRIS": ("bsi", "bank syariah indonesia"),
    "ARTO": ("bank jago",),
    "AGRO": ("bank raya",),
    "BJBR": ("bjb", "bank bjb", "bank jabar banten"),
    "BJTM": ("bank jatim",),
    "BNGA": ("cimb niaga", "bank cimb"),
    "NISP": ("ocbc nisp", "bank ocbc"),
    "BDMN": ("bank danamon", "danamon"),
    "PNBN": ("bank panin", "panin bank"),
    "MEGA": ("bank mega",),
    "BTPS": ("btpn syariah",),
    "BNII": ("maybank indonesia",),
    "BANK": ("bank aladin", "aladin syariah"),
    # --- telecommunications --------------------------------------------------
    "TLKM": ("telkom", "telkom indonesia", "telkomsel", "indihome"),
    "ISAT": ("indosat", "indosat ooredoo", "im3"),
    "EXCL": ("xl axiata", "axiata"),
    "MTEL": ("mitratel",),
    "TOWR": ("protelindo", "sarana menara"),
    "TBIG": ("tower bersama",),
    # --- consumer, where the product is better known than the issuer ---------
    "ICBP": ("indofood cbp", "indomie"),
    "INDF": ("indofood",),
    "UNVR": ("unilever",),
    "MYOR": ("mayora",),
    "KLBF": ("kalbe", "kalbe farma"),
    "SIDO": ("sido muncul", "tolak angin"),
    "ROTI": ("sari roti", "nippon indosari"),
    "ULTJ": ("ultrajaya", "ultra jaya"),
    "MLBI": ("multi bintang",),
    "DLTA": ("delta djakarta",),
    "CPIN": ("charoen pokphand",),
    "JPFA": ("japfa",),
    "GGRM": ("gudang garam",),
    "HMSP": ("sampoerna", "hm sampoerna"),
    "AMRT": ("alfamart", "sumber alfaria"),
    "MAPI": ("mitra adiperkasa",),
    "ACES": ("ace hardware",),
    "ERAA": ("erajaya",),
    "TSPC": ("tempo scan",),
    "KAEF": ("kimia farma",),
    "INAF": ("indofarma",),
    # --- technology and media ------------------------------------------------
    "GOTO": ("gojek", "tokopedia", "goto gojek tokopedia"),
    "BUKA": ("bukalapak",),
    "EMTK": ("emtek", "elang mahkota"),
    "SCMA": ("surya citra", "sctv", "indosiar"),
    "MNCN": ("media nusantara citra", "rcti"),
    # --- energy, metals and mining -------------------------------------------
    "ADRO": ("adaro", "adaro energy"),
    "AADI": ("adaro andalan",),
    "PTBA": ("bukit asam",),
    "ITMG": ("indo tambangraya", "banpu"),
    "HRUM": ("harum energy",),
    "MEDC": ("medco", "medco energi"),
    "PGAS": ("pgn", "perusahaan gas negara"),
    "ELSA": ("elnusa",),
    "ANTM": ("antam", "aneka tambang"),
    "INCO": ("vale indonesia",),
    "MDKA": ("merdeka copper", "merdeka battery"),
    "TINS": ("pt timah",),
    "AKRA": ("akr corporindo",),
    # --- industrials, materials and infrastructure ---------------------------
    "ASII": ("astra international", "grup astra"),
    "UNTR": ("united tractors",),
    "SMGR": ("semen indonesia", "semen gresik"),
    "INTP": ("indocement", "semen tiga roda"),
    "BRPT": ("barito pacific",),
    "TPIA": ("chandra asri",),
    "INKP": ("indah kiat",),
    "TKIM": ("tjiwi kimia",),
    "JSMR": ("jasa marga",),
    "WIKA": ("wijaya karya",),
    "ADHI": ("adhi karya",),
    "WSKT": ("waskita", "waskita karya"),
    "GIAA": ("garuda indonesia",),
    "BIRD": ("blue bird",),
    # --- plantations ----------------------------------------------------------
    "AALI": ("astra agro",),
    "LSIP": ("london sumatra", "lonsum"),
    "SIMP": ("salim ivomas",),
    # --- property and healthcare ----------------------------------------------
    "BSDE": ("bumi serpong damai", "bsd city"),
    "CTRA": ("ciputra",),
    "PWON": ("pakuwon",),
    "SMRA": ("summarecon",),
    "LPKR": ("lippo karawaci",),
    "KIJA": ("jababeka",),
    "DMAS": ("puradelta",),
    "MIKA": ("mitra keluarga",),
    "SILO": ("siloam",),
    "HEAL": ("hermina",),
    # --- financials other than banks ------------------------------------------
    "SRTG": ("saratoga",),
    "BFIN": ("bfi finance",),
    "ADMF": ("adira finance", "adira dinamika"),
}


def curated_for(ticker: str) -> tuple[str, ...]:
    """The index entry for one issuer, or nothing."""
    return CURATED_ALIASES.get(ticker.upper(), ())
