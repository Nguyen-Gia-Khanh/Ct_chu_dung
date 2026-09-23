"""Landscape or Portrait A4 labels: a large location and one short line per product.

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


@dataclass(frozen=True)
class LabelSlot:
    x: float
    y: float
    w: float
    h: float
    rotated: bool = False


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


def _compute_layout_slots(
    page_w: float,
    page_h: float,
    print_mode: str,
    label_height_cm: int,
    orientation: str,
    mm_unit: float,
) -> list[LabelSlot]:
    is_portrait = orientation.lower() == "portrait"
    margin = MARGIN_MM * mm_unit
    left_w = LEFT_WIDTH_MM * mm_unit
    label_h = LABEL_HEIGHTS_MM[label_height_cm] * mm_unit
    landscape_w = max(page_w, page_h)
    primal_product_w = (landscape_w - 2 * margin) - left_w  # 207 * mm_unit

    if print_mode == "full":
        label_w = page_w - 2 * margin
        labels_per_page = int(page_h // label_h)
        stack_h = labels_per_page * label_h + (labels_per_page - 1) * (GAP_MM * mm_unit)
        top_margin = (page_h - stack_h) / 2
        slots = []
        for row in range(labels_per_page):
            y = page_h - top_margin - (row + 1) * label_h - row * (GAP_MM * mm_unit)
            slots.append(LabelSlot(x=margin, y=y, w=label_w, h=label_h, rotated=False))
        return slots

    elif print_mode == "product_only":
        item_w = primal_product_w  # 207 mm
        item_h = label_h           # 70 mm or 150 mm
        slots = []
        if not is_portrait and label_height_cm == 7:
            # Landscape 7cm: 3 unrotated stacked vertically + 1 rotated in the leftover 80mm column
            for row in range(3):
                y = (2 - row) * 70 * mm_unit
                slots.append(LabelSlot(x=5 * mm_unit, y=y, w=item_w, h=item_h, rotated=False))
            # 4th item rotated 90 deg: width on page is 70mm (222mm to 292mm), height is 207mm (1.5mm to 208.5mm)
            slots.append(LabelSlot(x=222 * mm_unit, y=1.5 * mm_unit, w=item_w, h=item_h, rotated=True))
        elif is_portrait and label_height_cm == 7:
            # Portrait 7cm: 4 unrotated stacked vertically
            left_margin = (page_w - item_w) / 2
            top_margin = (page_h - 4 * 70 * mm_unit) / 2
            for row in range(4):
                y = page_h - top_margin - (row + 1) * 70 * mm_unit
                slots.append(LabelSlot(x=left_margin, y=y, w=item_w, h=item_h, rotated=False))
        else:
            # 15cm height: 1 item centered
            slots.append(LabelSlot(
                x=(page_w - item_w) / 2,
                y=(page_h - item_h) / 2,
                w=item_w,
                h=item_h,
                rotated=False,
            ))
        return slots

    elif print_mode == "location_only":
        item_w = left_w  # 80 mm
        item_h = label_h  # 70 mm or 150 mm
        slots = []
        if not is_portrait and label_height_cm == 7:
            # Landscape 7cm: 3 cols x 3 rows = 9 slots unrotated
            left_margin = (page_w - 3 * 80 * mm_unit) / 2
            for r in range(3):
                y = (2 - r) * 70 * mm_unit
                for c in range(3):
                    slots.append(LabelSlot(x=left_margin + c * 80 * mm_unit, y=y, w=item_w, h=item_h, rotated=False))
        elif is_portrait and label_height_cm == 7:
            # Portrait 7cm: 3 cols x 3 rows = 9 slots rotated 90 deg (each is 70mm wide x 80mm high on page)
            top_margin = (page_h - 3 * 80 * mm_unit) / 2
            for r in range(3):
                y = page_h - top_margin - (r + 1) * 80 * mm_unit
                for c in range(3):
                    slots.append(LabelSlot(x=c * 70 * mm_unit, y=y, w=item_w, h=item_h, rotated=True))
        elif not is_portrait and label_height_cm == 15:
            # Landscape 15cm: 3 cols x 1 row = 3 slots unrotated
            left_margin = (page_w - 3 * 80 * mm_unit) / 2
            y = (page_h - 150 * mm_unit) / 2
            for c in range(3):
                slots.append(LabelSlot(x=left_margin + c * 80 * mm_unit, y=y, w=item_w, h=item_h, rotated=False))
        else:
            # Portrait 15cm: 1 col x 3 rows = 3 slots rotated 90 deg (each is 150mm wide x 80mm high on page)
            left_margin = (page_w - 150 * mm_unit) / 2
            top_margin = (page_h - 3 * 80 * mm_unit) / 2
            for r in range(3):
                y = page_h - top_margin - (r + 1) * 80 * mm_unit
                slots.append(LabelSlot(x=left_margin, y=y, w=item_w, h=item_h, rotated=True))
        return slots

    raise ValueError(f"Unknown print_mode: {print_mode!r}. Choose 'full', 'location_only', or 'product_only'.")


def render_labels_pdf(
    cells: list[Cell] | tuple[Cell, ...],
    output_path: Path,
    *, label_height_cm: int = 7,
    orientation: str = "landscape",
    print_mode: str = "full",
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
        from reportlab.lib.pagesizes import A4, landscape, portrait
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

    is_portrait = orientation.lower() == "portrait"
    page_size = portrait(A4) if is_portrait else landscape(A4)
    page_w, page_h = page_size
    padding = PADDING_MM * mm
    location_padding = LOCATION_PADDING_MM * mm
    left_w = LEFT_WIDTH_MM * mm

    slots = _compute_layout_slots(
        page_w,
        page_h,
        print_mode=print_mode,
        label_height_cm=label_height_cm,
        orientation=orientation,
        mm_unit=mm,
    )
    if not slots:
        raise ValueError("No slots could be placed for the selected layout.")

    total_pages = math.ceil(len(cells) / len(slots))
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=page_size, pageCompression=1)
    canvas.setTitle("Warehouse location labels" + (" - draft sample" if sample else ""))
    canvas.setAuthor("Warehouse Label Printer")

    def product_table(products, location, target_w, target_h):
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
            name_col_w = target_w - id_col_w
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
            table_w, table_h = table.wrap(target_w, target_h)
            if table_w <= target_w + 0.1 and table_h <= target_h:
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

    def draw_location_id(w, h, location_id):
        raw_location = unicodedata.normalize("NFC", " ".join(str(location_id).split()))
        location_lines = (raw_location[:4], raw_location[4:]) if len(raw_location) > 4 else (raw_location,)
        widest_location_line = max(location_lines, key=lambda line: pdfmetrics.stringWidth(line, bold, LOCATION_FONT_SIZE))
        loc_size = LOCATION_FONT_SIZE
        location_body_h = h - 2 * location_padding
        ascent, descent = pdfmetrics.getAscentDescent(bold, loc_size)
        loc_h = (len(location_lines) - 1) * loc_size + ascent - descent
        while loc_size > MIN_LOCATION_FONT_SIZE and (
            pdfmetrics.stringWidth(widest_location_line, bold, loc_size)
            > w - 2 * location_padding
            or loc_h > location_body_h
        ):
            loc_size -= 0.5
            ascent, descent = pdfmetrics.getAscentDescent(bold, loc_size)
            loc_h = (len(location_lines) - 1) * loc_size + ascent - descent
        if loc_h > location_body_h:
            raise ValueError(f"Location ID {location_id!r} is too long for this label layout.")
        first_baseline = (h + loc_h) / 2 - ascent
        canvas.setFillColor(colors.black)
        canvas.setFont(bold, loc_size)
        for line_number, line in enumerate(location_lines):
            canvas.drawCentredString(
                w / 2,
                first_baseline - line_number * loc_size,
                line,
            )

    def draw_products(w, h, products, location_id):
        target_w = w - 2 * padding
        target_h = h - 2 * padding
        if not products:
            canvas.setFillColor(colors.HexColor("#777777"))
            canvas.setFont(regular, 24 if h > 100 * mm else 18)
            canvas.drawString(
                padding,
                h / 2 - 8,
                "No products assigned",
            )
        else:
            table, products_h = product_table(products, location_id, target_w, target_h)
            table.drawOn(
                canvas,
                padding,
                (h - products_h) / 2,
            )

    for index, cell in enumerate(cells):
        slot_index = index % len(slots)
        page_index = index // len(slots) + 1
        if slot_index == 0:
            if index > 0:
                canvas.showPage()
            progress(f"Creating A4 page {page_index} of {total_pages}...")

        slot = slots[slot_index]
        canvas.saveState()
        if slot.rotated:
            canvas.translate(slot.x + slot.h, slot.y)
            canvas.rotate(90)
        else:
            canvas.translate(slot.x, slot.y)

        # Draw outer label border
        canvas.setStrokeColor(colors.HexColor("#777777"))
        canvas.setLineWidth(0.55)
        canvas.rect(0, 0, slot.w, slot.h)

        if print_mode == "full":
            canvas.setStrokeColor(colors.HexColor("#BBBBBB"))
            canvas.line(left_w, 0, left_w, slot.h)
            draw_location_id(left_w, slot.h, cell.location_id)
            canvas.saveState()
            canvas.translate(left_w, 0)
            draw_products(slot.w - left_w, slot.h, cell.products, cell.location_id)
            canvas.restoreState()
        elif print_mode == "product_only":
            draw_products(slot.w, slot.h, cell.products, cell.location_id)
        elif print_mode == "location_only":
            draw_location_id(slot.w, slot.h, cell.location_id)

        canvas.restoreState()

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
    return PrintResult(output_path, len(cells), len(cells), total_pages)