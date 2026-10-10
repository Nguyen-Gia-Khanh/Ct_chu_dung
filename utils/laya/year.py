from utils.runtime import ensure_repo_venv

if __name__ == "__main__":
    ensure_repo_venv()

from .io import parse_paths
import re
from pathlib import Path

import pandas as pd
from tqdm import tqdm


# ============================================================
# CONFIG
# ============================================================




# ============================================================
# YEAR EXTRACTION
#
# Handles:
#
# 1998-2002
# 1998 – 2002
# 1998/2002
# 1998~2002
# 1998 đến 2002
# 1998 tới 2002
# 1998 -> 2002
#
# 2020-23  -> 2020-2023
# 1998-02  -> 1998-2002
#
# Single:
# 1998
# 2005
#
# Valid range:
# 1900-2099
# ============================================================

def valid_year(year):
    return 1900 <= year <= 2099


def resolve_short_year(first_year, short_year):
    """
    Examples:

        2020-23 -> 2023
        1998-02 -> 2002
        1995-99 -> 1999
        2008-12 -> 2012
    """

    century = (first_year // 100) * 100
    second_year = century + short_year

    # Handle century rollover:
    # 1998-02 -> 2002
    if second_year < first_year:
        second_year += 100

    return second_year


def extract_year_range(text):
    text = str(text)

    # Normalize common dash characters
    text = (
        text
        .replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
        .replace("\xa0", " ")
    )

    text = re.sub(r"\s+", " ", text).strip()


    # ========================================================
    # 1. FULL YEAR RANGE
    #
    # 1998-2002
    # 2005 / 2008
    # 2019 đến 2022
    # ========================================================

    full_range_pattern = r"""
        (?<!\d)
        ((?:19|20)\d{2})
        \s*
        (?:
            [-~_/]
            |
            ->
            |
            =>
            |
            \b(?:đến|den|tới|toi|to|đến\s+năm|từ)\b
        )
        \s*
        ((?:19|20)\d{2})
        (?!\d)
    """

    match = re.search(
        full_range_pattern,
        text,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    if match:
        year1 = int(match.group(1))
        year2 = int(match.group(2))

        if valid_year(year1) and valid_year(year2):
            if year1 <= year2:
                return f"{year1}-{year2}"

            # If someone typed reverse order,
            # normalize it.
            return f"{year2}-{year1}"


    # ========================================================
    # 2. FULL YEAR + SHORT SECOND YEAR
    #
    # 2020-23
    # 1998-02
    # 1995/99
    # ========================================================

    short_range_pattern = r"""
        (?<!\d)
        ((?:19|20)\d{2})
        \s*
        [-~_/]
        \s*
        (\d{2})
        (?!\d)
    """

    match = re.search(
        short_range_pattern,
        text,
        flags=re.VERBOSE,
    )

    if match:
        year1 = int(match.group(1))
        short_year = int(match.group(2))

        year2 = resolve_short_year(
            year1,
            short_year,
        )

        if valid_year(year1) and valid_year(year2):
            return f"{year1}-{year2}"


    # ========================================================
    # 3. "FROM ... TO ..."
    #
    # từ 1998 đến 2001
    # từ năm 2005 tới năm 2008
    # ========================================================

    vietnamese_range = r"""
        \b(?:từ|tu)
        (?:\s+năm)?
        \s*
        ((?:19|20)\d{2})
        \s*
        \b(?:đến|den|tới|toi|đến\s+năm)
        (?:\s+năm)?
        \s*
        ((?:19|20)\d{2})
        \b
    """

    match = re.search(
        vietnamese_range,
        text,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    if match:
        year1 = int(match.group(1))
        year2 = int(match.group(2))

        if valid_year(year1) and valid_year(year2):
            if year1 <= year2:
                return f"{year1}-{year2}"

            return f"{year2}-{year1}"


    # ========================================================
    # 4. SINGLE YEAR
    #
    # 1996
    # 2004
    # 2023
    # ========================================================

    match = re.search(
        r"(?<!\d)((?:19|20)\d{2})(?!\d)",
        text,
    )

    if match:
        year = int(match.group(1))

        if valid_year(year):
            return str(year)


    return ""


# ============================================================
# LOAD FIRST SHEET
# ============================================================


def main(argv: list[str] | None = None) -> None:
    input_file, output_file = parse_paths("year", argv)
    if not input_file.exists():
        raise FileNotFoundError(
            f"File not found:\n{input_file}"
        )

    df = pd.read_excel(
        input_file,
        sheet_name=0,
        dtype=str,
    ).fillna("")

    if "product_name" not in df.columns:
        raise ValueError(
            "Missing required column: product_name"
        )


    # ============================================================
    # EXTRACT
    #
    # If year_range doesn't exist:
    #     creates it
    #
    # If it already exists:
    #     overwrites it
    # ============================================================

    df["year_range"] = [
        extract_year_range(product_name)
        for product_name in tqdm(
            df["product_name"],
            total=len(df),
            desc="Extracting year ranges",
        )
    ]


    # ============================================================
    # SAVE
    # ============================================================

    df.to_excel(
        output_file,
        index=False,
    )

    print(f"Saved: {output_file}")

if __name__ == "__main__":
    main()
