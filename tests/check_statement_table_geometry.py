"""CPU-only regression for page edges, extra dividers, and speck-free rows.

Run with .venv-ocr/Scripts/python.exe tests/check_statement_table_geometry.py.
Only geometry function definitions are loaded; no notebook cell or OCR model runs.
"""
import ast
import json
from pathlib import Path
import statistics

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps


def check():
    path = Path(__file__).resolve().parents[1] / 'utils/ocr_work/statement_ocr_colab.ipynb'
    notebook = json.loads(path.read_text(encoding='utf-8'))
    core = next(''.join(cell['source']) for cell in notebook['cells']
                if 'def detect_table(image):' in ''.join(cell['source']))
    names = {'rectify', 'detect_table', 'visual_row_edges'}
    nodes = [node for node in ast.parse(core).body
             if (isinstance(node, ast.FunctionDef) and node.name in names)
             or (isinstance(node, ast.Assign) and any(
                 isinstance(target, ast.Name) and target.id == 'COLUMN_FRACTIONS'
                 for target in node.targets))]
    geometry = dict(globals())
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<CPU geometry>', 'exec'), geometry)
    image = Image.new('RGB', (1200, 1300), 'white')
    draw = ImageDraw.Draw(image)
    for fraction in geometry['COLUMN_FRACTIONS']:
        x = round(140 + 900 * fraction)
        draw.line((x, 70, x, 1220), fill='black', width=3)
    # Two paper margins and two unrelated internal/external line candidates.
    for x in (35, 75, 680, 1150):
        draw.line((x, 25, x, 1270), fill='black', width=3)
    for index, y in enumerate((85, 290, 505, 720, 940), 295):
        draw.text((147, y), str(index), fill='black', font_size=16)
    draw.rectangle((152, 450, 154, 454), fill='black')
    table, layout = geometry['detect_table'](image)
    assert layout['line_candidates'] >= 12, layout
    assert layout['selected_rules'] == 9, layout
    assert abs(layout['corners'][0][0] - 140) < 6, layout
    assert abs(layout['corners'][1][0] - 1040) < 6, layout
    np.testing.assert_allclose(np.array(layout['columns']) / table.width,
                               geometry['COLUMN_FRACTIONS'], atol=0.012)
    rows, _ = geometry['visual_row_edges'](table, layout['columns'])
    assert len(rows) - 1 == 5, rows
    try:
        geometry['detect_table'](Image.new('RGB', image.size, 'white'))
    except ValueError:
        pass
    else:
        raise AssertionError('Blank paper must not be accepted as a table')
    print('CPU geometry check passed: ignored extra rules and speck; preserved five rows.')


if __name__ == '__main__':
    check()
