import re
from functools import lru_cache
from pathlib import Path

import pandas as pd
from tqdm import tqdm


# ============================================================
# CONFIG
# ============================================================

INPUT_FILE = Path(r"C:\path\to\your_file.xlsx")
OUTPUT_FILE = INPUT_FILE.with_name(f"{INPUT_FILE.stem}_model.xlsx")

USE_LAYA_FOR_AMBIGUOUS_AIR = True
AIR_CONFIDENCE = 0.65


# ============================================================
# MODEL REGISTRY
#
# These are BASE MODELS.
#
# Examples:
#   Wave RSX 110 -> Wave
#   Wave Alpha   -> Wave
#   Winner X     -> Winner
#   Blade 110    -> Blade
#
# Version/trim information is intentionally left in the name
# for the version extractor.
# ============================================================

MODEL_RULES = [
    # --------------------------------------------------------
    # HONDA
    # --------------------------------------------------------

    ("Air Blade", "Honda", [
        r"\bair\s*blade\b",
        r"\bairblade\b",
        r"(?<![A-Za-z0-9])ab(?=\s*\d{2,4}[A-Za-z]*\b|[^A-Za-z0-9]|$)",
    ]),

    ("SH Mode", "Honda", [
        r"\bsh\s*mode\b",
        r"\bshmode\b",
    ]),

    ("Super Cub", "Honda", [
        r"\bsuper\s*cub\b",
    ]),

    ("Blade", "Honda", [
        r"\bblade\b",
    ]),

    ("Wave", "Honda", [
        r"\bwave\b",
    ]),

    ("Winner", "Honda", [
        r"\bwinner\b",
    ]),

    ("Sonic", "Honda", [
        r"\bsonic\b",
    ]),

    ("Vision", "Honda", [
        r"\bvision\b",
        r"\bvison\b",
    ]),

    ("Lead", "Honda", [
        r"\blead\b",
    ]),

    ("Future", "Honda", [
        r"\bfuture\b",
    ]),

    ("Dream", "Honda", [
        r"\bdream\b",
    ]),

    ("SH", "Honda", [
        r"(?<![A-Za-z0-9])sh(?=\s*\d|\d|\s|[-,/()]|$)",
    ]),

    ("Vario", "Honda", [
        r"\bvario\b",
    ]),

    ("Click", "Honda", [
        r"\bclick\b",
    ]),

    ("Scoopy", "Honda", [
        r"\bscoopy\b",
    ]),

    ("PCX", "Honda", [
        r"\bpcx\b",
    ]),

    ("ADV", "Honda", [
        r"(?<![A-Za-z0-9])adv(?=\s*\d|\d|\s|[-,/()]|$)",
    ]),

    ("MSX", "Honda", [
        r"\bmsx\b",
    ]),

    ("Monkey", "Honda", [
        r"\bmonkey\b",
    ]),

    ("Rebel", "Honda", [
        r"\brebel\b",
    ]),

    ("CBR", "Honda", [
        r"(?<![A-Za-z0-9])cbr(?=\s*\d|\d|\s|[-,/()]|$)",
    ]),

    ("CRF", "Honda", [
        r"(?<![A-Za-z0-9])crf(?=\s*\d|\d|\s|[-,/()]|$)",
    ]),

    ("Gold Wing", "Honda", [
        r"\bgold\s*wing\b",
        r"\bgoldwing\b",
    ]),

    # --------------------------------------------------------
    # YAMAHA
    # --------------------------------------------------------

    ("Exciter", "Yamaha", [
        r"\bexciter\b",
        r"(?<![A-Za-z0-9])ex(?=\s*(?:135|150|155)\b)",
    ]),

    ("Sirius", "Yamaha", [
        r"\bsirius\b",
    ]),

    ("Jupiter", "Yamaha", [
        r"\bjupiter\b",
    ]),

    ("Grande", "Yamaha", [
        r"\bgrande\b",
    ]),

    ("Janus", "Yamaha", [
        r"\bjanus\b",
    ]),

    ("NVX", "Yamaha", [
        r"\bnvx\b",
    ]),

    ("Nouvo", "Yamaha", [
        r"\bnouvo\b",
    ]),

    ("FreeGo", "Yamaha", [
        r"\bfree\s*go\b",
        r"\bfreego\b",
    ]),

    ("Latte", "Yamaha", [
        r"\blatte\b",
    ]),

    ("Mio", "Yamaha", [
        r"\bmio\b",
    ]),

    ("NMAX", "Yamaha", [
        r"\bn[\s-]?max\b",
    ]),

    ("XMAX", "Yamaha", [
        r"\bx[\s-]?max\b",
    ]),

    ("R15", "Yamaha", [
        r"\br[\s-]?15\b",
    ]),

    ("R3", "Yamaha", [
        r"\br[\s-]?3\b",
    ]),

    ("MT-15", "Yamaha", [
        r"\bmt[\s-]?15\b",
    ]),

    ("MT-03", "Yamaha", [
        r"\bmt[\s-]?0?3\b",
    ]),

    ("PG-1", "Yamaha", [
        r"\bpg[\s-]?1\b",
    ]),

    ("Lexi", "Yamaha", [
        r"\blexi\b",
    ]),

    ("Gear", "Yamaha", [
        r"\bgear\b",
    ]),

    # --------------------------------------------------------
    # SUZUKI
    # --------------------------------------------------------

    ("Raider", "Suzuki", [
        r"\braider\b",
    ]),

    ("Satria", "Suzuki", [
        r"\bsatria\b",
    ]),

    ("Address", "Suzuki", [
        r"\baddress\b",
    ]),

    ("Burgman", "Suzuki", [
        r"\bburgman\b",
    ]),

    ("Hayate", "Suzuki", [
        r"\bhayate\b",
    ]),

    ("Axelo", "Suzuki", [
        r"\baxelo\b",
    ]),

    ("Viva", "Suzuki", [
        r"\bviva\b",
    ]),

    ("GSX", "Suzuki", [
        r"\bgsx\b",
    ]),

    ("Smash", "Suzuki", [
        r"\bsmash\b",
    ]),

    ("Impulse", "Suzuki", [
        r"\bimpulse\b",
    ]),

    # --------------------------------------------------------
    # SYM
    # --------------------------------------------------------

    ("Attila", "SYM", [
        r"\battila\b",
    ]),

    ("Galaxy", "SYM", [
        r"\bgalaxy\b",
    ]),

    ("Elegant", "SYM", [
        r"\belegant\b",
    ]),

    ("Shark", "SYM", [
        r"\bshark\b",
    ]),

    ("Elizabeth", "SYM", [
        r"\belizabeth\b",
    ]),

    ("Angela", "SYM", [
        r"\bangela\b",
    ]),

    ("Passing", "SYM", [
        r"\bpassing\b",
    ]),

    ("Star SR", "SYM", [
        r"\bstar\s*sr\b",
    ]),

    ("Husky", "SYM", [
        r"\bhusky\b",
    ]),

    # --------------------------------------------------------
    # PIAGGIO
    # --------------------------------------------------------

    ("Liberty", "Piaggio", [
        r"\bliberty\b",
    ]),

    ("Medley", "Piaggio", [
        r"\bmedley\b",
    ]),

    ("Beverly", "Piaggio", [
        r"\bbeverly\b",
    ]),

    ("Fly", "Piaggio", [
        r"\bpiaggio\s*fly\b",
        r"\bfly\s*(?=\d{2,3}\b)",
    ]),

    ("Zip", "Piaggio", [
        r"\bpiaggio\s*zip\b",
        r"\bzip\s*(?=\d{2,3}\b)",
    ]),

    # --------------------------------------------------------
    # VESPA
    # --------------------------------------------------------

    ("Vespa Sprint", "Vespa", [
        r"\bvespa\s*sprint\b",
    ]),

    ("Primavera", "Vespa", [
        r"\bprimavera\b",
    ]),

    ("Vespa LX", "Vespa", [
        r"\bvespa\s*lx\b",
    ]),

    ("Vespa S", "Vespa", [
        r"\bvespa\s+s\b",
    ]),

    ("Vespa GTS", "Vespa", [
        r"\bvespa\s*gts\b",
    ]),

    # --------------------------------------------------------
    # KYMCO
    # --------------------------------------------------------

    ("Like", "Kymco", [
        r"\bkymco\s+like\b",
    ]),

    ("Candy", "Kymco", [
        r"\bcandy\b",
    ]),

    ("People", "Kymco", [
        r"\bkymco\s+people\b",
    ]),

    ("Jockey", "Kymco", [
        r"\bjockey\b",
    ]),

    # --------------------------------------------------------
    # VINFAST
    # --------------------------------------------------------

    ("Klara", "VinFast", [
        r"\bklara\b",
    ]),

    ("Feliz", "VinFast", [
        r"\bfeliz\b",
    ]),

    ("Evo", "VinFast", [
        r"\bevo\s*(?:200)?\b",
    ]),

    ("Vento", "VinFast", [
        r"\bvento\b",
    ]),

    ("Theon", "VinFast", [
        r"\btheon\b",
    ]),

    ("Motio", "VinFast", [
        r"\bmotio\b",
    ]),

    # --------------------------------------------------------
    # KAWASAKI
    # --------------------------------------------------------

    ("Ninja", "Kawasaki", [
        r"\bninja\b",
    ]),

    ("Z800", "Kawasaki", [
        r"\bz800\b",
    ]),

    ("Z900", "Kawasaki", [
        r"\bz900\b",
    ]),

    ("Z1000", "Kawasaki", [
        r"\bz1000\b",
    ]),

    ("Versys", "Kawasaki", [
        r"\bversys\b",
    ]),

    # --------------------------------------------------------
    # DUCATI
    # --------------------------------------------------------

    ("Panigale", "Ducati", [
        r"\bpanigale\b",
    ]),

    ("Monster", "Ducati", [
        r"\bmonster\b",
    ]),

    ("Scrambler", "Ducati", [
        r"\bscrambler\b",
    ]),

    # --------------------------------------------------------
    # KTM
    # --------------------------------------------------------

    ("Duke", "KTM", [
        r"\bduke\b",
    ]),

    ("RC", "KTM", [
        r"\bktm\s+rc\b",
    ]),

    # --------------------------------------------------------
    # BENELLI
    # --------------------------------------------------------

    ("TNT", "Benelli", [
        r"\btnt\s*(?=\d{2,3}\b)",
    ]),

    ("TRK", "Benelli", [
        r"\btrk\s*(?=\d{2,3}\b)",
    ]),
]


# ============================================================
# COMPILE RULES
# ============================================================

COMPILED_RULES = []

for priority, (model, brand, patterns) in enumerate(MODEL_RULES):
    COMPILED_RULES.append(
        {
            "model": model,
            "brand": brand,
            "priority": priority,
            "patterns": [
                re.compile(pattern, re.IGNORECASE)
                for pattern in patterns
            ],
        }
    )


# ============================================================
# LAYA FOR STANDALONE "AIR"
# ============================================================

_laya_agent = None

AIR_QUESTION = {
    "air_blade": {
        "type": "choice",
        "instructions": (
            "Read the complete Vietnamese motorcycle-parts product name. "
            "Determine whether the standalone word AIR refers to the Honda "
            "Air Blade motorcycle model. Use surrounding part names, years, "
            "engine sizes and other motorcycle-model context. Do not assume "
            "every occurrence of AIR means Air Blade."
        ),
        "criteria": {
            "Air Blade": (
                "AIR is being used as an abbreviation or informal reference "
                "to the Honda Air Blade motorcycle model."
            ),
            "Not Air Blade": (
                "AIR means something else, or there is not enough evidence "
                "to reliably identify Honda Air Blade."
            ),
        },
    }
}


def get_laya_agent():
    global _laya_agent

    if _laya_agent is not None:
        return _laya_agent

    import torch
    import laya

    device = "cuda" if torch.cuda.is_available() else "cpu"

    print(f"Loading Laya on {device}...")

    _laya_agent = laya.load(
        "convaiinnovations/laya-multilingual",
        device=device,
    )

    return _laya_agent


@lru_cache(maxsize=5000)
def classify_air(product_name):
    if not USE_LAYA_FOR_AMBIGUOUS_AIR:
        return False

    agent = get_laya_agent()

    result = agent.predict(
        {"product_name": product_name},
        AIR_QUESTION,
    )

    answer = result["answers"]["air_blade"]

    if answer["choice"] != "Air Blade":
        return False

    confidence = answer.get("confidence")

    if confidence is None:
        return True

    return confidence >= AIR_CONFIDENCE


# ============================================================
# HELPERS
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


def overlaps(a_start, a_end, b_start, b_end):
    return not (
        a_end <= b_start
        or a_start >= b_end
    )


# ============================================================
# FIND MODEL MENTIONS
# ============================================================

def find_model_mentions(product_name):
    text = normalize_text(product_name)

    candidates = []

    for rule in COMPILED_RULES:
        for pattern in rule["patterns"]:
            for match in pattern.finditer(text):
                candidates.append(
                    {
                        "model": rule["model"],
                        "brand": rule["brand"],
                        "start": match.start(),
                        "end": match.end(),
                        "matched": match.group(0),
                        "priority": rule["priority"],
                    }
                )

    # Longer matches win when positions overlap.
    # Example:
    # Air Blade beats Blade.
    # SH Mode beats SH.
    candidates.sort(
        key=lambda x: (
            x["start"],
            -(x["end"] - x["start"]),
            x["priority"],
        )
    )

    accepted = []

    for candidate in candidates:
        if any(
            overlaps(
                candidate["start"],
                candidate["end"],
                current["start"],
                current["end"],
            )
            for current in accepted
        ):
            continue

        accepted.append(candidate)

    accepted.sort(key=lambda x: x["start"])

    # --------------------------------------------------------
    # STANDALONE AIR
    # --------------------------------------------------------

    has_explicit_air_blade = any(
        item["model"] == "Air Blade"
        for item in accepted
    )

    if not has_explicit_air_blade:
        for match in re.finditer(
            r"\bair\b",
            text,
            flags=re.IGNORECASE,
        ):
            try:
                if classify_air(text):
                    accepted.append(
                        {
                            "model": "Air Blade",
                            "brand": "Honda",
                            "start": match.start(),
                            "end": match.end(),
                            "matched": match.group(0),
                            "priority": -1,
                        }
                    )
                    break

            except Exception as exc:
                print(
                    f"\nAIR classification error:\n"
                    f"{text}\n{exc}\n"
                )
                break

    accepted.sort(key=lambda x: x["start"])

    return accepted


# ============================================================
# EXTRACT MODEL FIELD
# ============================================================

def extract_models(product_name):
    mentions = find_model_mentions(product_name)

    models = []

    for mention in mentions:
        model = mention["model"]

        if model not in models:
            models.append(model)

    return "|".join(models)


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

if "product_name" not in df.columns:
    raise ValueError("Missing required column: product_name")


# ============================================================
# PROCESS
# ============================================================

models = []

for product_name in tqdm(
    df["product_name"],
    total=len(df),
    desc="Extracting models",
):
    models.append(
        extract_models(product_name)
    )

df["model"] = models


# ============================================================
# SAVE
# ============================================================

df.to_excel(
    OUTPUT_FILE,
    index=False,
)

print(f"Saved: {OUTPUT_FILE}")