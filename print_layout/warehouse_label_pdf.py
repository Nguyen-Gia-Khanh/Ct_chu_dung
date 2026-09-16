"""A4 warehouse labels: a large location on the left, products on the right.

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


MARGIN_MM = 10
GAP_MM = 3
LEFT_WIDTH_MM = 60
PADDING_MM = 4
LOCATION_FONT_SIZE = 25
MIN_LOCATION_FONT_SIZE = 12
PRODUCT_FONT_SIZE = 10
MIN_PRODUCT_FONT_SIZE = 8
PRODUCTS_PER_LABEL = 4
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
    # Extra labels preserve every product if a cell ever exceeds four products.
    return sum(max(1, math.ceil(len(cell.products) / PRODUCTS_PER_LABEL)) for cell in cells)


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
    *, labels_per_page: int = 4,
    sample: bool = False,
    progress=lambda _text: None,
) -> PrintResult:
    """Render full product names. Refuse overflow instead of clipping or truncating.

The caller determines shelf/cell order. An empty cell receives a location label.
Output is replaced only after every label has been laid out successfully.
"""
    if not cells:
        raise ValueError("There are no cells to print.")
    if labels_per_page not in (2, 3, 4):
        raise ValueError("Choose 2, 3, or 4 labels per A4 page.")
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen.canvas import Canvas
        from reportlab.platypus import Paragraph
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

    page_w, page_h = A4
    margin, gap, padding = MARGIN_MM * mm, GAP_MM * mm, PADDING_MM * mm
    header, footer = 6 * mm, 4 * mm
    label_w, left_w = page_w - 2 * margin, LEFT_WIDTH_MM * mm
    label_h = (page_h - 2 * margin - header - footer - (labels_per_page - 1) * gap) / labels_per_page
    right_w = label_w - left_w - 2 * padding
    body_h = label_h - 2 * padding
    labels = []
    for cell in cells:
        chunks = [cell.products[i:i + PRODUCTS_PER_LABEL] for i in range(0, len(cell.products), PRODUCTS_PER_LABEL)] or [()]
        labels.extend((cell, products, index + 1, len(chunks)) for index, products in enumerate(chunks))
    total_pages = math.ceil(len(labels) / labels_per_page)
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4, pageCompression=1)
    canvas.setTitle("Warehouse location labels" + (" - draft sample" if sample else ""))
    canvas.setAuthor("Warehouse Label Printer")

    def product_blocks(products, location):
        for step in range(round((PRODUCT_FONT_SIZE - MIN_PRODUCT_FONT_SIZE) * 2) + 1):
            size = PRODUCT_FONT_SIZE - step / 2
            name_style = ParagraphStyle("ProductName", fontName=regular, fontSize=size, leading=size * 1.2)
            id_style = ParagraphStyle("ProductID", fontName=bold, fontSize=size, leading=size * 1.2)
            blocks = []
            for product in products:
                id_para = Paragraph(clean(product.product_id), id_style)
                name_para = Paragraph(clean(product.name), name_style)
                id_h = id_para.wrap(right_w, 10000)[1]
                name_h = name_para.wrap(right_w, 10000)[1]
                blocks.append((id_para, id_h, name_para, name_h))
            total_h = sum(a + b + 2 for _, a, _, b in blocks) + max(0, len(blocks) - 1) * 8
            if total_h <= body_h:
                return blocks
        raise ValueError(
            f"The full text in {location} does not fit. Choose fewer labels per page "
            "(2 gives the most space). Nothing was truncated or saved."
        )

    for index, (cell, products, part, parts) in enumerate(labels):
        row = index % labels_per_page
        page = index // labels_per_page + 1
        if row == 0:
            if index:
                canvas.showPage()
            progress(f"Creating A4 page {page} of {total_pages}...")
            canvas.setFillColor(colors.HexColor("#555555"))
            canvas.setFont(bold, 7)
            canvas.drawString(margin, page_h - margin - 2, "WAREHOUSE LABELS" + (" / DRAFT SAMPLE" if sample else ""))
            canvas.setFont(regular, 6.5)
            canvas.drawRightString(page_w - margin, margin - 2, f"A4 / 100% scale / {page} of {total_pages}")
            if sample:
                canvas.drawString(margin, margin - 2, "Sample data - product names and IDs are illustrative.")

        x = margin
        y = page_h - margin - header - (row + 1) * label_h - row * gap
        canvas.setStrokeColor(colors.HexColor("#777777"))
        canvas.setLineWidth(0.55)
        canvas.rect(x, y, label_w, label_h)
        canvas.setStrokeColor(colors.HexColor("#BBBBBB"))
        canvas.line(x + left_w, y, x + left_w, y + label_h)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.setFont(bold, 7)
        canvas.drawString(x + padding, y + label_h - padding - 7, "LOCATION")

        loc_size = LOCATION_FONT_SIZE
        while loc_size > MIN_LOCATION_FONT_SIZE and pdfmetrics.stringWidth(cell.location_id, bold, loc_size) > left_w - 2 * padding:
            loc_size -= 0.5
        location_para = Paragraph(clean(cell.location_id), ParagraphStyle(
            "Location", fontName=bold, fontSize=loc_size, leading=loc_size * 1.15, alignment=TA_CENTER,
        ))
        loc_h = location_para.wrap(left_w - 2 * padding, 10000)[1]
        if loc_h > label_h - 2 * padding - 30:
            raise ValueError(f"Location ID {cell.location_id!r} is too long for this label layout.")
        location_para.drawOn(canvas, x + padding, y + (label_h - loc_h) / 2)
        if parts > 1:
            canvas.setFont(regular, 7)
            canvas.drawCentredString(x + left_w / 2, y + padding, f"Part {part} of {parts}")

        cursor_y = y + label_h - padding
        if not products:
            canvas.setFillColor(colors.HexColor("#777777"))
            canvas.setFont(regular, 9)
            canvas.drawString(x + left_w + padding, cursor_y - 11, "No products assigned")
        for item, (id_para, id_h, name_para, name_h) in enumerate(product_blocks(products, cell.location_id)):
            id_para.drawOn(canvas, x + left_w + padding, cursor_y - id_h)
            cursor_y -= id_h + 2
            name_para.drawOn(canvas, x + left_w + padding, cursor_y - name_h)
            cursor_y -= name_h
            if item < len(products) - 1:
                canvas.setStrokeColor(colors.HexColor("#DDDDDD"))
                canvas.setLineWidth(0.4)
                canvas.line(x + left_w + padding, cursor_y - 4, x + label_w - padding, cursor_y - 4)
                cursor_y -= 8

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
