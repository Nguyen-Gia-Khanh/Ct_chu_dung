import json
import re
from pathlib import Path

import pandas as pd
from tqdm import tqdm


# ============================================================
# CONFIG
# ============================================================

INPUT_FILE = Path(r"C:\path\to\your_model_file.xlsx")
OUTPUT_FILE = INPUT_FILE.with_name(f"{INPUT_FILE.stem}_version.xlsx")


# ============================================================
# MODEL ALIASES
#
# These locate the BASE MODEL inside product_name.
# Version text is deliberately NOT consumed when possible.
# ============================================================

MODEL_ALIASES = {
    # Honda
    "Air Blade": [
        r"\bair\s*blade\b",
        r"\bairblade\b",
        r"(?<![A-Za-z0-9])ab(?=\s*\d|\d|\s|[-,/()]|$)",
        r"\bair\b",
    ],
    "SH Mode": [
        r"\bsh\s*mode\b",
        r"\bshmode\b",
    ],
    "Super Cub": [
        r"\bsuper\s*cub\b",
    ],
    "Blade": [
        r"\bblade\b",
    ],
    "Wave": [
        r"\bwave\b",
    ],
    "Winner": [
        r"\bwinner\b",
    ],
    "Sonic": [
        r"\bsonic\b",
    ],
    "Vision": [
        r"\bvision\b",
        r"\bvison\b",
    ],
    "Lead": [
        r"\blead\b",
    ],
    "Future": [
        r"\bfuture\b",
    ],
    "Dream": [
        r"\bdream\b",
    ],
    "SH": [
        r"(?<![A-Za-z0-9])sh(?=\s*\d|\d|\s|[-,/()]|$)",
    ],
    "Vario": [
        r"\bvario\b",
    ],
    "Click": [
        r"\bclick\b",
    ],
    "Scoopy": [
        r"\bscoopy\b",
    ],
    "PCX": [
        r"\bpcx\b",
    ],
    "ADV": [
        r"\badv\b",
    ],
    "MSX": [
        r"\bmsx\b",
    ],
    "Monkey": [
        r"\bmonkey\b",
    ],
    "Rebel": [
        r"\brebel\b",
    ],
    "CBR": [
        r"\bcbr\b",
    ],
    "CRF": [
        r"\bcrf\b",
    ],
    "Gold Wing": [
        r"\bgold\s*wing\b",
        r"\bgoldwing\b",
    ],

    # Yamaha
    "Exciter": [
        r"\bexciter\b",
        r"(?<![A-Za-z0-9])ex(?=\s*(?:135|150|155)\b)",
    ],
    "Sirius": [
        r"\bsirius\b",
    ],
    "Jupiter": [
        r"\bjupiter\b",
    ],
    "Grande": [
        r"\bgrande\b",
    ],
    "Janus": [
        r"\bjanus\b",
    ],
    "NVX": [
        r"\bnvx\b",
    ],
    "Nouvo": [
        r"\bnouvo\b",
    ],
    "FreeGo": [
        r"\bfree\s*go\b",
        r"\bfreego\b",
    ],
    "Latte": [
        r"\blatte\b",
    ],
    "Mio": [
        r"\bmio\b",
    ],
    "NMAX": [
        r"\bn[\s-]?max\b",
    ],
    "XMAX": [
        r"\bx[\s-]?max\b",
    ],
    "R15": [
        r"\br[\s-]?15\b",
    ],
    "R3": [
        r"\br[\s-]?3\b",
    ],
    "MT-15": [
        r"\bmt[\s-]?15\b",
    ],
    "MT-03": [
        r"\bmt[\s-]?0?3\b",
    ],
    "PG-1": [
        r"\bpg[\s-]?1\b",
    ],
    "Lexi": [
        r"\blexi\b",
    ],
    "Gear": [
        r"\bgear\b",
    ],

    # Suzuki
    "Raider": [r"\braider\b"],
    "Satria": [r"\bsatria\b"],
    "Address": [r"\baddress\b"],
    "Burgman": [r"\bburgman\b"],
    "Hayate": [r"\bhayate\b"],
    "Axelo": [r"\baxelo\b"],
    "Viva": [r"\bviva\b"],
    "GSX": [r"\bgsx\b"],
    "Smash": [r"\bsmash\b"],
    "Impulse": [r"\bimpulse\b"],

    # SYM
    "Attila": [r"\battila\b"],
    "Galaxy": [r"\bgalaxy\b"],
    "Elegant": [r"\belegant\b"],
    "Shark": [r"\bshark\b"],
    "Elizabeth": [r"\belizabeth\b"],
    "Angela": [r"\bangela\b"],
    "Passing": [r"\bpassing\b"],
    "Star SR": [r"\bstar\s*sr\b"],
    "Husky": [r"\bhusky\b"],

    # Piaggio / Vespa
    "Liberty": [r"\bliberty\b"],
    "Medley": [r"\bmedley\b"],
    "Beverly": [r"\bbeverly\b"],
    "Fly": [
        r"\bpiaggio\s*fly\b",
        r"\bfly\b",
    ],
    "Zip": [
        r"\bpiaggio\s*zip\b",
        r"\bzip\b",
    ],
    "Vespa Sprint": [r"\bvespa\s*sprint\b"],
    "Primavera": [r"\bprimavera\b"],
    "Vespa LX": [r"\bvespa\s*lx\b"],
    "Vespa S": [r"\bvespa\s+s\b"],
    "Vespa GTS": [r"\bvespa\s*gts\b"],

    # Kymco
    "Like": [r"\bkymco\s+like\b"],
    "Candy": [r"\bcandy\b"],
    "People": [r"\bkymco\s+people\b"],
    "Jockey": [r"\bjockey\b"],

    # VinFast
    "Klara": [r"\bklara\b"],
    "Feliz": [r"\bfeliz\b"],
    "Evo": [r"\bevo\b"],
    "Vento": [r"\bvento\b"],
    "Theon": [r"\btheon\b"],
    "Motio": [r"\bmotio\b"],

    # Kawasaki
    "Ninja": [r"\bninja\b"],
    "Z800": [r"\bz800\b"],
    "Z900": [r"\bz900\b"],
    "Z1000": [r"\bz1000\b"],
    "Versys": [r"\bversys\b"],

    # Ducati / KTM / Benelli
    "Panigale": [r"\bpanigale\b"],
    "Monster": [r"\bmonster\b"],
    "Scrambler": [r"\bscrambler\b"],
    "Duke": [r"\bduke\b"],
    "RC": [r"\bktm\s+rc\b"],
    "TNT": [r"\btnt\b"],
    "TRK": [r"\btrk\b"],
}


# ============================================================
# MODELS WHERE THEIR DIGITS BELONG TO THE MODEL ITSELF
# ============================================================

PROTECTED_MODELS = {
    "R15",
    "R3",
    "MT-15",
    "MT-03",
    "PG-1",
    "Z800",
    "Z900",
    "Z1000",
}


# ============================================================
# VERSION TOKENS
# ============================================================

VERSION_WORDS = {
    "x": "X",
    "s": "S",
    "r": "R",
    "rs": "RS",
    "rsx": "RSX",
    "alpha": "Alpha",
    "neo": "Neo",
    "revo": "Revo",
    "fi": "FI",
    "fi1": "FI1",
    "fi2": "FI2",
    "esp": "eSP",
    "esp+": "eSP+",
    "abs": "ABS",
    "cbs": "CBS",
    "vva": "VVA",
    "vtec": "VTEC",
    "sport": "Sport",
    "special": "Special",
    "standard": "Standard",
    "premium": "Premium",
    "deluxe": "Deluxe",
}


TRAILING_FEATURES = {
    "fi",
    "esp",
    "esp+",
    "abs",
    "cbs",
    "vva",
    "vtec",
}


STOP_WORDS = {
    "đen",
    "trắng",
    "đỏ",
    "xanh",
    "vàng",
    "bạc",
    "xám",
    "ghi",
    "nâu",
    "cam",
    "hồng",
    "tím",
    "màu",
    "trái",
    "phải",
    "trước",
    "sau",
    "trên",
    "dưới",
    "đời",
    "năm",
    "dùng",
    "cho",
    "của",
    "và",
}


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_text(text):
    text = str(text)

    text = (
        text
        .replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
        .replace("\xa0", " ")
    )

    return re.sub(r"\s+", " ", text).strip()


def parse_models(model_string):
    if not model_string:
        return []

    return [
        model.strip()
        for model in str(model_string).split("|")
        if model.strip()
    ]


# ============================================================
# NUMERIC VERSION VALIDATION
# ============================================================

def is_year(token):
    token = re.sub(r"\D", "", str(token))

    if len(token) != 4:
        return False

    number = int(token)

    return 1900 <= number <= 2099


def is_plausible_number(token):
    token = str(token).lower().strip()

    match = re.fullmatch(
        r"(\d{2,4})(?:cc)?",
        token,
    )

    if not match:
        return False

    number = int(match.group(1))

    if 1900 <= number <= 2099:
        return False

    return 49 <= number <= 1800


# ============================================================
# TOKEN NORMALIZATION
# ============================================================

def normalize_version_token(token):
    token = token.strip()

    low = token.lower()

    if low in VERSION_WORDS:
        return VERSION_WORDS[low]

    # 150cc -> 150
    match = re.fullmatch(
        r"(\d{2,4})cc",
        low,
    )

    if match:
        return match.group(1)

    # 150i / 110s / 125fi
    match = re.fullmatch(
        r"(\d{2,4})([a-z]{1,4})",
        low,
    )

    if match:
        number = match.group(1)
        suffix = match.group(2)

        if suffix in VERSION_WORDS:
            suffix = VERSION_WORDS[suffix]
        elif suffix == "i":
            suffix = "i"
        else:
            suffix = suffix.upper()

        return f"{number}{suffix}"

    # S110 / RS110 / RSX110 / C125 / V2
    match = re.fullmatch(
        r"([a-z]{1,8})(\d{1,4})([a-z]{0,3})",
        low,
    )

    if match:
        prefix = match.group(1)
        number = match.group(2)
        suffix = match.group(3)

        prefix = VERSION_WORDS.get(
            prefix,
            prefix.upper(),
        )

        if suffix:
            suffix = VERSION_WORDS.get(
                suffix,
                suffix.upper(),
            )

        return f"{prefix}{number}{suffix}"

    return token


# ============================================================
# TOKENIZER
# ============================================================

TOKEN_RE = re.compile(
    r"""
    [A-Za-z]+\d{1,4}[A-Za-z+]*
    |
    \d{2,4}[A-Za-z+]*
    |
    [A-Za-z+]+
    """,
    re.VERBOSE,
)


def tokenize_version_text(text):
    return TOKEN_RE.findall(text)


# ============================================================
# PARSE ONE VERSION CHUNK
# ============================================================

def parse_single_chunk(chunk):
    chunk = normalize_text(chunk)

    chunk = re.sub(
        r"^[\s,:;()\[\]\-]+",
        "",
        chunk,
    )

    if not chunk:
        return None

    tokens = tokenize_version_text(
        chunk[:45]
    )

    if not tokens:
        return None

    first = tokens[0]
    first_low = first.lower()

    if first_low in STOP_WORDS:
        return None

    if is_year(first):
        return None


    # --------------------------------------------------------
    # S110 / RS110 / RSX110 / C125 / V2
    # --------------------------------------------------------

    if re.fullmatch(
        r"[A-Za-z]{1,8}\d{1,4}[A-Za-z+]*",
        first,
    ):
        version = normalize_version_token(first)

        if (
            len(tokens) > 1
            and tokens[1].lower() in TRAILING_FEATURES
        ):
            version += " " + normalize_version_token(tokens[1])

        return version


    # --------------------------------------------------------
    # 150 / 150i / 125FI / 160ABS
    # --------------------------------------------------------

    numeric_match = re.match(
        r"(\d{2,4})",
        first,
    )

    if numeric_match:
        number = int(
            numeric_match.group(1)
        )

        if 1900 <= number <= 2099:
            return None

        if not 49 <= number <= 1800:
            return None

        version = normalize_version_token(first)

        if (
            len(tokens) > 1
            and tokens[1].lower() in TRAILING_FEATURES
        ):
            version += " " + normalize_version_token(tokens[1])

        return version


    # --------------------------------------------------------
    # X
    # RS
    # RSX
    # Alpha
    # Neo
    # Revo
    # --------------------------------------------------------

    if first_low in VERSION_WORDS:
        version = normalize_version_token(first)

        index = 1

        # RSX 110
        # Alpha 110
        # X 150
        if (
            index < len(tokens)
            and is_plausible_number(tokens[index])
        ):
            version += " " + normalize_version_token(
                tokens[index]
            )
            index += 1

        # RSX 110 FI
        # X 150 ABS
        if (
            index < len(tokens)
            and tokens[index].lower() in TRAILING_FEATURES
        ):
            version += " " + normalize_version_token(
                tokens[index]
            )

        return version

    return None


# ============================================================
# PARSE VERSION SEGMENT
# ============================================================

def parse_version_segment(segment):
    segment = normalize_text(segment)

    segment = re.sub(
        r"^[\s,:;()\[\]\-]+",
        "",
        segment,
    )

    if not segment:
        return []

    # Stop before obvious unrelated continuation.
    segment = re.split(
        r"[,;|]"
        r"|\b(?:và|va|and|hoặc|hoac|or)\b",
        segment,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()

    if not segment:
        return []

    segment = segment[:60]

    versions = []


    # --------------------------------------------------------
    # 125/150
    # RSX110/RS110
    # --------------------------------------------------------

    chunks = re.split(
        r"\s*/\s*|\s*&\s*",
        segment,
    )


    # --------------------------------------------------------
    # 110-125
    #
    # Only treat "-" as alternative separator when both sides
    # look like plausible version numbers and NOT years.
    # --------------------------------------------------------

    expanded_chunks = []

    for chunk in chunks:
        numeric_range = re.fullmatch(
            r"\s*(\d{2,4}[A-Za-z]*)"
            r"\s*-\s*"
            r"(\d{2,4}[A-Za-z]*)\s*",
            chunk,
        )

        if numeric_range:
            left = numeric_range.group(1)
            right = numeric_range.group(2)

            if (
                not is_year(left)
                and not is_year(right)
            ):
                expanded_chunks.extend(
                    [left, right]
                )
                continue

        expanded_chunks.append(chunk)


    for chunk in expanded_chunks:
        version = parse_single_chunk(chunk)

        if (
            version
            and version not in versions
        ):
            versions.append(version)

    return versions


# ============================================================
# FIND MODEL MENTIONS
# ============================================================

def find_model_mentions(
    product_name,
    models,
):
    text = normalize_text(product_name)

    candidates = []

    for model in models:
        patterns = MODEL_ALIASES.get(
            model,
            [rf"\b{re.escape(model)}\b"],
        )

        for pattern in patterns:
            for match in re.finditer(
                pattern,
                text,
                flags=re.IGNORECASE,
            ):
                candidates.append(
                    {
                        "model": model,
                        "start": match.start(),
                        "end": match.end(),
                        "length": (
                            match.end()
                            - match.start()
                        ),
                    }
                )

    # Longer match wins on overlap.
    candidates.sort(
        key=lambda x: (
            x["start"],
            -x["length"],
        )
    )

    accepted = []

    for candidate in candidates:
        overlap = any(
            not (
                candidate["end"] <= current["start"]
                or candidate["start"] >= current["end"]
            )
            for current in accepted
        )

        if not overlap:
            accepted.append(candidate)

    accepted.sort(
        key=lambda x: x["start"]
    )

    return text, accepted


# ============================================================
# VERSION BEFORE MODEL
#
# Handles:
#   150 Winner
#   160 Air Blade
#
# Conservative: only immediate preceding token.
# ============================================================

def version_before_model(
    text,
    model_start,
):
    prefix = text[
        max(0, model_start - 18):
        model_start
    ]

    match = re.search(
        r"([A-Za-z]{1,6}\d{1,4}[A-Za-z]*"
        r"|\d{2,4}[A-Za-z]*)"
        r"\s*$",
        prefix,
    )

    if not match:
        return None

    candidate = match.group(1)

    if is_year(candidate):
        return None

    return parse_single_chunk(candidate)


# ============================================================
# EXTRACT VERSIONS
# ============================================================

def extract_versions(
    product_name,
    model_string,
):
    models = parse_models(
        model_string
    )

    if not models:
        return {}

    result = {
        model: []
        for model in models
    }

    text, mentions = find_model_mentions(
        product_name,
        models,
    )


    # --------------------------------------------------------
    # No occurrence found for some canonical model:
    # still leave it as null.
    # --------------------------------------------------------

    for index, mention in enumerate(mentions):
        model = mention["model"]

        if model in PROTECTED_MODELS:
            continue

        next_start = (
            mentions[index + 1]["start"]
            if index + 1 < len(mentions)
            else len(text)
        )

        segment = text[
            mention["end"]:
            next_start
        ]


        # ----------------------------------------------------
        # AFTER MODEL
        # ----------------------------------------------------

        for version in parse_version_segment(
            segment
        ):
            if version not in result[model]:
                result[model].append(
                    version
                )


        # ----------------------------------------------------
        # BEFORE MODEL
        # ----------------------------------------------------

        before = version_before_model(
            text,
            mention["start"],
        )

        if (
            before
            and before not in result[model]
        ):
            result[model].append(
                before
            )


    return {
        model: (
            versions
            if versions
            else None
        )
        for model, versions in result.items()
    }


# ============================================================
# LOAD
# ============================================================

if not INPUT_FILE.exists():
    raise FileNotFoundError(INPUT_FILE)

df = pd.read_excel(
    INPUT_FILE,
    sheet_name=0,
    dtype=str,
).fillna("")

required = {
    "product_name",
    "model",
}

missing = required - set(df.columns)

if missing:
    raise ValueError(
        f"Missing columns: {sorted(missing)}"
    )


# ============================================================
# PROCESS
# ============================================================

version_values = []

for row in tqdm(
    df.itertuples(index=False),
    total=len(df),
    desc="Extracting versions",
):
    result = extract_versions(
        row.product_name,
        row.model,
    )

    version_values.append(
        json.dumps(
            result,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )

df["version"] = version_values


# ============================================================
# SAVE
# ============================================================

df.to_excel(
    OUTPUT_FILE,
    index=False,
)

print(f"Saved: {OUTPUT_FILE}")