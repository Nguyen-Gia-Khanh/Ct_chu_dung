"""A4 labels with a location column, or a split header on 14.5 cm labels.

Used by utils.labels.app. ReportLab is imported only when creating a
PDF. Change the constants below to revise the printed design.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import math
import os
from pathlib import Path
import re
import struct
import tempfile
import unicodedata
from xml.sax.saxutils import escape


MARGIN_MM = 5
LEFT_WIDTH_MM = 80
THREE_CM_LOCATION_WIDTH_MM = 40
PADDING_MM = 4
LOCATION_PADDING_MM = 4
LOCATION_FONT_SIZE = 140
MIN_LOCATION_FONT_SIZE = 20
PRODUCT_FONT_SIZE = 56
MIN_PRODUCT_FONT_SIZE = 7
LABEL_HEIGHTS_CM = (3, 7, 14.5)
LARGE_LABEL_HEIGHT_CM = 14.5
LARGE_LOCATION_PADDING_PT = 8
LARGE_LOCATION_FONT_SIZE = 144
LARGE_PRODUCT_FONT_SIZE = 64

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


def _location_width_mm(label_height_cm: int | float) -> int:
    # The 80 mm column leaves large blank sides around a two-line ID on 3 cm labels.
    return THREE_CM_LOCATION_WIDTH_MM if label_height_cm == 3 else LEFT_WIDTH_MM


def _split_location_id(location_id: str) -> tuple[str, str]:
    """Keep the floor/side prefix together, including multi-digit segments."""
    text = unicodedata.normalize("NFC", " ".join(str(location_id).split()))
    match = re.fullmatch(r"(L\d+-\d+)(.*)", text, re.IGNORECASE)
    return match.groups() if match else (text, "")


def _font_files() -> tuple[Path, Path]:
    if FONT_REGULAR_PATH and FONT_BOLD_PATH:
        candidates = [(Path(FONT_REGULAR_PATH), Path(FONT_BOLD_PATH))]
    else:
        windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        bundled = Path(__file__).resolve().parent / "fonts"
        candidates = [
            (windows_fonts / "arial.ttf", windows_fonts / "arialbd.ttf"),
            (bundled / "DejaVuSans.ttf", bundled / "DejaVuSans-Bold.ttf"),
            (
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            ),
            (
                Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
                Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
            ),
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
    label_height_cm: int | float,
    orientation: str,
    mm_unit: float,
) -> list[LabelSlot]:
    is_portrait = orientation.lower() == "portrait"
    margin = MARGIN_MM * mm_unit
    left_w = _location_width_mm(label_height_cm) * mm_unit
    label_h = label_height_cm * 10 * mm_unit

    def fit(span: float, size: float) -> int:
        # Allow for tiny floating-point differences in A4 and millimetre conversions.
        return max(0, math.floor((span + 1e-6) / size))

    def grid(
        x: float, y: float, cols: int, rows: int, w: float, h: float,
        rotated: bool = False,
    ) -> list[LabelSlot]:
        box_w, box_h = (h, w) if rotated else (w, h)
        return [
            LabelSlot(x + col * box_w, y + (rows - row - 1) * box_h, w, h, rotated)
            for row in range(rows)
            for col in range(cols)
        ]

    if print_mode == "full":
        rows = fit(page_h, label_h)
        return grid(
            margin, (page_h - rows * label_h) / 2,
            1, rows, page_w - 2 * margin, label_h,
        )

    if print_mode == "product_only":
        item_w = page_w - 2 * margin - left_w
        upright_x = margin + left_w if is_portrait else margin
        spare_x = margin if is_portrait else margin + item_w
        upright_rows = fit(page_h, label_h)
        slots = grid(
            upright_x, (page_h - upright_rows * label_h) / 2,
            1, upright_rows, item_w, label_h,
        )
        rotated_cols = fit(left_w, label_h)
        rotated_rows = fit(page_h, item_w)
        slots += grid(
            spare_x + (left_w - rotated_cols * label_h) / 2,
            (page_h - rotated_rows * item_w) / 2,
            rotated_cols, rotated_rows, item_w, label_h, True,
        )
    elif print_mode == "location_only":
        item_w = left_w
        upright_cols = fit(page_w - 2 * margin, item_w)
        upright_rows = fit(page_h, label_h)
        spare_w = page_w - 2 * margin - upright_cols * item_w
        rotated_cols = fit(spare_w, label_h)
        rotated_rows = fit(page_h, item_w)
        # Keep the upright grid centred unless the spare strip holds rotated labels.
        upright_x = (
            margin if rotated_cols and rotated_rows
            else (page_w - upright_cols * item_w) / 2
        )
        slots = grid(
            upright_x, (page_h - upright_rows * label_h) / 2,
            upright_cols, upright_rows, item_w, label_h,
        )
        slots += grid(
            margin + upright_cols * item_w + (spare_w - rotated_cols * label_h) / 2,
            (page_h - rotated_rows * item_w) / 2,
            rotated_cols, rotated_rows, item_w, label_h, True,
        )
    else:
        raise ValueError(
            f"Unknown print_mode: {print_mode!r}. Choose 'full', 'location_only', or 'product_only'."
        )

    # Large labels fit better rotated. For smaller labels, keep the mixed layout
    # when both arrangements hold the same number of labels.
    rotated_cols = fit(page_w, label_h)
    rotated_rows = fit(page_h, item_w)
    rotated_slots = grid(
        (page_w - rotated_cols * label_h) / 2,
        (page_h - rotated_rows * item_w) / 2,
        rotated_cols, rotated_rows, item_w, label_h, True,
    )
    return rotated_slots if len(rotated_slots) > len(slots) else slots


def render_labels_pdf(
    cells: list[Cell] | tuple[Cell, ...],
    output_path: Path,
    *,
    label_height_cm: int | float = 7,
    orientation: str = "landscape",
    print_mode: str = "full",
    limit_to_30_characters: bool = True,
    sample: bool = False,
    progress=lambda _text: None,
) -> PrintResult:
    """Render one label per warehouse cell using product IDs and shortened names.

    The product font and row spacing shrink automatically until every assigned product
    fits on the cell's label. The caller determines shelf/cell order and should pass the
    shortened product name in ``Product.name``. An empty cell receives a location label.
    By default, names longer than 30 characters print their first 30 followed by "...".
    Disable ``limit_to_30_characters`` to print the complete names.
    Output is replaced only after every label has been laid out successfully.
    """
    if not cells:
        raise ValueError("There are no cells to print.")
    if label_height_cm not in LABEL_HEIGHTS_CM:
        heights = ", ".join(f"{height:g}" for height in LABEL_HEIGHTS_CM)
        raise ValueError(f"Choose a label height from {heights} cm.")
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
            ".venv\\Scripts\\python.exe -m pip install reportlab"
        ) from error

    regular_path, bold_path = _font_files()
    regular, bold = "WarehouseLabelRegular", "WarehouseLabelBold"
    if regular not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(regular, str(regular_path)))
        pdfmetrics.registerFont(TTFont(bold, str(bold_path)))
        pdfmetrics.registerFontFamily(
            regular, normal=regular, bold=bold, italic=regular, boldItalic=bold
        )

    def clean(value: str, *, limit_name: bool = False) -> str:
        # Canonical combining marks and XML escaping preserve Vietnamese and &/<.
        text = unicodedata.normalize("NFC", " ".join(str(value).split()))
        if limit_name and limit_to_30_characters and len(text) > 30:
            text = text[:30] + "..."
        return escape(text)

    is_portrait = orientation.lower() == "portrait"
    page_size = portrait(A4) if is_portrait else landscape(A4)
    page_w, page_h = page_size
    padding = PADDING_MM * mm
    location_padding = LOCATION_PADDING_MM * mm
    left_w = _location_width_mm(label_height_cm) * mm

    is_large_label = label_height_cm == LARGE_LABEL_HEIGHT_CM
    product_font_size = LARGE_PRODUCT_FONT_SIZE if is_large_label else PRODUCT_FONT_SIZE

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
        for step in range(round((product_font_size - MIN_PRODUCT_FONT_SIZE) * 2) + 1):
            size = product_font_size - step / 2
            leading = size * 1.10
            column_gap = max(4, size * 0.65)
            row_padding = max(0.4, size * 0.06)

            # Measure IDs with the actual bold font used in the table. The first
            # column therefore adapts to each cell rather than using a fixed width.
            raw_ids = [
                unicodedata.normalize("NFC", " ".join(str(product.product_id).split()))
                for product in products
            ]
            id_text_w = max(
                pdfmetrics.stringWidth(value, bold, size) for value in raw_ids
            )
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
                name_para = Paragraph(clean(product.name, limit_name=True), name_style)
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
            "Choose a larger label height or shorten the product names further."
            if label_height_cm < max(LABEL_HEIGHTS_CM)
            else "Shorten the product names further."
        )
        raise ValueError(
            f"The product list in {location} does not fit the {label_height_cm} cm label "
            f"even at {MIN_PRODUCT_FONT_SIZE} pt. {next_step} No PDF was saved."
        )

    def draw_location_id(w, h, location_id):
        raw_location = unicodedata.normalize("NFC", " ".join(str(location_id).split()))
        location_lines = (
            (raw_location[:4], raw_location[4:])
            if len(raw_location) > 4
            else (raw_location,)
        )
        widest_location_line = max(
            location_lines,
            key=lambda line: pdfmetrics.stringWidth(line, bold, LOCATION_FONT_SIZE),
        )
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
            raise ValueError(
                f"Location ID {location_id!r} is too long for this label layout."
            )
        first_baseline = (h + loc_h) / 2 - ascent
        canvas.setFillColor(colors.black)
        canvas.setFont(bold, loc_size)
        for line_number, line in enumerate(location_lines):
            canvas.drawCentredString(
                w / 2,
                first_baseline - line_number * loc_size,
                line,
            )

    def draw_location_cells(w, label_h, location_id):
        parts = _split_location_id(location_id)
        cell_w = w / 2
        target_w = cell_w - 2 * location_padding
        size = LARGE_LOCATION_FONT_SIZE
        while True:
            if max(pdfmetrics.stringWidth(part, bold, size) for part in parts) <= target_w:
                break
            if size <= MIN_LOCATION_FONT_SIZE:
                raise ValueError(
                    f"Location ID {location_id!r} is too long for this label layout."
                )
            size -= 0.5

        # Measure the actual glyph ink, excluding the font's unused ascender and
        # descender space, so both visible vertical gaps are exactly 8 points.
        face = pdfmetrics.getFont(bold).face
        glyph_data = face.get_table("glyf")
        bounds = []
        for character in set("".join(parts)):
            glyph = face.charToGlyph.get(ord(character), 0)
            offset = face.glyphPos[glyph]
            if offset != face.glyphPos[glyph + 1]:
                _, _, bottom, _, top = struct.unpack_from(
                    ">hhhhh", glyph_data, offset
                )
                bounds.append((bottom, top))
        descent = min((bottom for bottom, _ in bounds), default=0) * size / face.unitsPerEm
        ascent = max((top for _, top in bounds), default=0) * size / face.unitsPerEm
        h = ascent - descent + 2 * LARGE_LOCATION_PADDING_PT
        body_h = label_h - h
        canvas.setStrokeColor(colors.HexColor("#BBBBBB"))
        canvas.line(0, body_h, w, body_h)
        canvas.saveState()
        canvas.translate(0, body_h)
        canvas.line(cell_w, 0, cell_w, h)
        canvas.setFillColor(colors.black)
        canvas.setFont(bold, size)
        baseline = LARGE_LOCATION_PADDING_PT - descent
        for index, part in enumerate(parts):
            canvas.drawCentredString((index + 0.5) * cell_w, baseline, part)
        canvas.restoreState()
        return body_h

    def draw_products(w, h, products, location_id, *, align_top=False):
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
                h - padding - products_h if align_top else (h - products_h) / 2,
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

        if print_mode == "full" and is_large_label:
            body_h = draw_location_cells(slot.w, slot.h, cell.location_id)
            draw_products(slot.w, body_h, cell.products, cell.location_id, align_top=True)
        elif print_mode == "full":
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
        with tempfile.NamedTemporaryFile(
            dir=output_path.parent, prefix=".label_", suffix=".pdf", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(buffer.getvalue())
        os.replace(temporary, output_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return PrintResult(output_path, len(cells), len(cells), total_pages)
