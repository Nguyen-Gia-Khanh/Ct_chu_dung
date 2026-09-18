"""Landscape A4 labels: a large location and one short line per product.

Used by warehouse_label_printer.py. ReportLab is imported only when creating a
PDF. Change the constants below to revise the printed design.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import math
import os
from pathlib import Path
import tempfile
import unicodedata
from xml.sax.saxutils import escape


MARGIN_MM = 5
GAP_MM = 0
LEFT_WIDTH_MM = 80
PADDING_MM = 4
LOCATION_PADDING_MM = 4
LOCATION_FONT_SIZE = 140
MIN_LOCATION_FONT_SIZE = 20
PRODUCT_FONT_SIZE = 28
MIN_PRODUCT_FONT_SIZE = 7
LABEL_HEIGHTS_MM = {7: 70, 15: 150}
LABELS_PER_PAGE = {7: 3, 15: 1}
# Normally discovered automatically. Set BOTH to override the system fonts.
FONT_REGULAR_PATH = ""
FONT_BOLD_PATH = ""


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str


@dataclass(frozen=True)
class Cell:
    shelf_id: int
    slot_id: int
    row_number: int
    slot_number: int
    location_id: str
    products: tuple[Product, ...] = ()


@dataclass(frozen=True)
class PrintResult:
    path: Path
    cells: int
    labels: int
    pages: int


def label_count(cells: list[Cell] | tuple[Cell, ...]) -> int:
    # One warehouse cell always produces one physical label.
    return len(cells)


def _font_files() -> tuple[Path, Path]:
    if FONT_REGULAR_PATH and FONT_BOLD_PATH:
        candidates = [(Path(FONT_REGULAR_PATH), Path(FONT_BOLD_PATH))]
    else:
        windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        bundled = Path(__file__).resolve().parent / "fonts"
        candidates = [
            (windows_fonts / "arial.ttf", windows_fonts / "arialbd.ttf"),
            (bundled / "DejaVuSans.ttf", bundled / "DejaVuSans-Bold.ttf"),
            (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
             Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
            (Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
             Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")),
        ]
    for regular, bold in candidates:
        if regular.is_file() and bold.is_file():
            return regular, bold
    raise RuntimeError(
        "No suitable Unicode font pair found. Set FONT_REGULAR_PATH and "
        "FONT_BOLD_PATH in warehouse_label_pdf.py to Arial or DejaVu Sans TTF files."
    )


def render_labels_pdf(
    cells: list[Cell] | tuple[Cell, ...],
    output_path: Path,
    *, label_height_cm: int = 7,
    sample: bool = False,
    progress=lambda _text: None,
) -> PrintResult:
    """Render one label per warehouse cell using product IDs and shortened names.

The product font and row spacing shrink automatically until every assigned product
fits on the cell's label. The caller determines shelf/cell order and should pass the
shortened product name in ``Product.name``. An empty cell receives a location label.
Output is replaced only after every label has been laid out successfully.
"""
    if not cells:
        raise ValueError("There are no cells to print.")
    if label_height_cm not in LABEL_HEIGHTS_MM:
        raise ValueError("Choose a 7 cm or 15 cm label height.")
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen.canvas import Canvas
        from reportlab.platypus import Paragraph, Table, TableStyle
    except ImportError as error:
        raise RuntimeError(
            "Install ReportLab in the same venv used to run this app:\n\n"
            "python -m pip install reportlab"
        ) from error

    regular_path, bold_path = _font_files()
    regular, bold = "WarehouseLabelRegular", "WarehouseLabelBold"
    if regular not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(regular, str(regular_path)))
        pdfmetrics.registerFont(TTFont(bold, str(bold_path)))
        pdfmetrics.registerFontFamily(regular, normal=regular, bold=bold, italic=regular, boldItalic=bold)

    def clean(value: str) -> str:
        # Canonical combining marks and XML escaping preserve Vietnamese and &/<.
        return escape(unicodedata.normalize("NFC", " ".join(str(value).split())))

    page_size = landscape(A4)
    page_w, page_h = page_size
    margin, gap, padding = MARGIN_MM * mm, GAP_MM * mm, PADDING_MM * mm
    location_padding = LOCATION_PADDING_MM * mm
    label_w, left_w = page_w - 2 * margin, LEFT_WIDTH_MM * mm
    label_h = LABEL_HEIGHTS_MM[label_height_cm] * mm
    labels_per_page = LABELS_PER_PAGE[label_height_cm]
    stack_h = labels_per_page * label_h + (labels_per_page - 1) * gap
    top_margin = (page_h - stack_h) / 2
    right_w = label_w - left_w - 2 * padding
    body_h = label_h - 2 * padding
    # No fixed products-per-label limit: every cell stays on exactly one label.
    labels = [(cell, cell.products) for cell in cells]
    total_pages = math.ceil(len(labels) / labels_per_page)
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=page_size, pageCompression=1)
    canvas.setTitle("Warehouse location labels" + (" - draft sample" if sample else ""))
    canvas.setAuthor("Warehouse Label Printer")

    def product_table(products, location):
        """Build a borderless two-column table that fits on one label.

        The ID column is sized from the widest product ID at each candidate font
        size. The shortened-name column receives the remaining width. Both
        columns shrink together until every product stays on one line and the
        complete table fits vertically.
        """
        for step in range(round((PRODUCT_FONT_SIZE - MIN_PRODUCT_FONT_SIZE) * 2) + 1):
            size = PRODUCT_FONT_SIZE - step / 2
            leading = size * 1.10
            column_gap = max(4, size * 0.65)
            row_padding = max(0.4, size * 0.06)

            # Measure IDs with the actual bold font used in the table. The first
            # column therefore adapts to each cell rather than using a fixed width.
            raw_ids = [
                unicodedata.normalize("NFC", " ".join(str(product.product_id).split()))
                for product in products
            ]
            id_text_w = max(pdfmetrics.stringWidth(value, bold, size) for value in raw_ids)
            id_col_w = id_text_w + column_gap
            name_col_w = right_w - id_col_w
            if name_col_w <= size:
                continue

            id_style = ParagraphStyle(
                "ProductID",
                fontName=bold,
                fontSize=size,
                leading=leading,
                spaceBefore=0,
                spaceAfter=0,
            )
            name_style = ParagraphStyle(
                "ProductName",
                fontName=regular,
                fontSize=size,
                leading=leading,
                spaceBefore=0,
                spaceAfter=0,
            )

            rows = []
            one_line = True
            for product in products:
                id_para = Paragraph(clean(product.product_id), id_style)
                name_para = Paragraph(clean(product.name), name_style)
                id_h = id_para.wrap(id_col_w - column_gap, 10000)[1]
                name_h = name_para.wrap(name_col_w, 10000)[1]
                if id_h > leading + 0.1 or name_h > leading + 0.1:
                    one_line = False
                    break
                rows.append([id_para, name_para])

            if not one_line:
                continue

            table = Table(
                rows,
                colWidths=[id_col_w, name_col_w],
                hAlign="LEFT",
            )
            style_commands = [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, -1), column_gap),
                ("RIGHTPADDING", (1, 0), (1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), row_padding),
                ("BOTTOMPADDING", (0, 0), (-1, -1), row_padding),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
            if len(rows) > 1:
                style_commands.append(
                    ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#DDDDDD"))
                )
            table.setStyle(TableStyle(style_commands))
            table_w, table_h = table.wrap(right_w, body_h)
            if table_w <= right_w + 0.1 and table_h <= body_h:
                return table, table_h

        next_step = (
            "Choose the 15 cm size or shorten the product names further."
            if label_height_cm == 7
            else "Shorten the product names further."
        )
        raise ValueError(
            f"The product list in {location} does not fit the {label_height_cm} cm label "
            f"even at {MIN_PRODUCT_FONT_SIZE} pt. {next_step} Nothing was truncated or saved."
        )

    for index, (cell, products) in enumerate(labels):
        row = index % labels_per_page
        page = index // labels_per_page + 1
        if row == 0:
            if index:
                canvas.showPage()
            progress(f"Creating A4 page {page} of {total_pages}...")

        x = margin
        y = page_h - top_margin - (row + 1) * label_h - row * gap
        canvas.setStrokeColor(colors.HexColor("#777777"))
        canvas.setLineWidth(0.55)
        canvas.rect(x, y, label_w, label_h)
        canvas.setStrokeColor(colors.HexColor("#BBBBBB"))
        canvas.line(x + left_w, y, x + left_w, y + label_h)
        raw_location = unicodedata.normalize("NFC", " ".join(str(cell.location_id).split()))
        location_lines = (raw_location[:4], raw_location[4:]) if len(raw_location) > 4 else (raw_location,)
        widest_location_line = max(location_lines, key=lambda line: pdfmetrics.stringWidth(line, bold, LOCATION_FONT_SIZE))
        loc_size = LOCATION_FONT_SIZE
        location_body_h = label_h - 2 * location_padding
        ascent, descent = pdfmetrics.getAscentDescent(bold, loc_size)
        loc_h = (len(location_lines) - 1) * loc_size + ascent - descent
        while loc_size > MIN_LOCATION_FONT_SIZE and (
            pdfmetrics.stringWidth(widest_location_line, bold, loc_size)
            > left_w - 2 * location_padding
            or loc_h > location_body_h
        ):
            loc_size -= 0.5
            ascent, descent = pdfmetrics.getAscentDescent(bold, loc_size)
            loc_h = (len(location_lines) - 1) * loc_size + ascent - descent
        if loc_h > location_body_h:
            raise ValueError(f"Location ID {cell.location_id!r} is too long for this label layout.")
        first_baseline = y + (label_h + loc_h) / 2 - ascent
        canvas.setFillColor(colors.black)
        canvas.setFont(bold, loc_size)
        for line_number, line in enumerate(location_lines):
            canvas.drawCentredString(
                x + left_w / 2,
                first_baseline - line_number * loc_size,
                line,
            )
        if not products:
            canvas.setFillColor(colors.HexColor("#777777"))
            canvas.setFont(regular, 24)
            canvas.drawString(
                x + left_w + padding,
                y + label_h / 2 - 8,
                "No products assigned",
            )
        else:
            table, products_h = product_table(products, cell.location_id)
            table.drawOn(
                canvas,
                x + left_w + padding,
                y + (label_h - products_h) / 2,
            )

    canvas.save()
    output_path = Path(output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output_path.parent, prefix=".label_", suffix=".pdf", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(buffer.getvalue())
        os.replace(temporary, output_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return PrintResult(output_path, len(cells), len(labels), total_pages)
