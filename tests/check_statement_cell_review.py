"""Offline checks for numeric crop noise, real confidence, and export colors.

Run with .venv-ocr/Scripts/python.exe tests/check_statement_cell_review.py.
No notebook cells, OCR models, or live Sheets calls run.
"""
import ast
import bisect
from io import BytesIO
import json
from pathlib import Path
import re
import statistics
from types import SimpleNamespace
import unicodedata

import cv2
import numpy as np
from openpyxl import load_workbook
from PIL import Image, ImageDraw


def check():
    path = Path(__file__).resolve().parents[1] / 'utils/ocr_work/statement_ocr_colab.ipynb'
    notebook = json.loads(path.read_text(encoding='utf-8'))
    names = {'validate_and_flag_records', 'numeric_cell_crops', 'extract_with_v6',
             'export_to_google_sheets', 'export_to_excel'}
    constants = {'COLUMNS', 'VIETNAMESE_LETTERS', 'ROW_ISSUE_COLUMNS'}
    nodes = []
    for cell in notebook['cells']:
        source = ''.join(cell['source'])
        if not any('def ' + name in source for name in names):
            continue
        nodes.extend(node for node in ast.parse(source).body
                     if (isinstance(node, ast.FunctionDef) and node.name in names)
                     or (isinstance(node, ast.Assign) and any(
                         isinstance(target, ast.Name) and target.id in constants for target in node.targets)))
    helpers = dict(globals())
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<offline helpers>', 'exec'), helpers)
    columns = helpers['COLUMNS']
    validate = helpers['validate_and_flag_records']
    good = dict(zip(columns, ('295', '20/06/2025 12:18:37', '20/06/2025', 'FT25171ZT8T0',
                             'NGUYỄN VĂN ANH chuyển tiền', '', '18,678,000', '87,275,416')))
    good['content'] = unicodedata.normalize('NFD', good['content'])
    valid = validate([dict(good)], 0.85)
    assert not valid['issues'], valid
    assert all(score is None for score in valid['confidence'][0].values())
    assert unicodedata.is_normalized('NFC', valid['rows'][0]['content'])
    debit = dict(good, money_out='15,400', money_in='')
    assert not validate([debit])['issues']
    both = validate([dict(good, money_out='15,400')])
    assert both['review_columns'][1] == {'money_out', 'money_in'}
    foreign = validate([dict(good, money_in='2023年1月1日')])
    assert foreign['review_columns'][1] == {'money_in'}
    assert foreign['rows'][0]['money_in'] == '2023年1月1日'  # Preserve raw output for review.
    foreign_text = validate([dict(good, content='chuyển tiền 文字')])
    assert foreign_text['review_columns'][1] == {'content'}
    scores = dict.fromkeys(columns, 0.99)
    scores['money_in'] = 0.84
    flagged = validate([dict(good)], 0.85, cell_confidence=[scores])
    assert flagged['review_columns'][1] == {'money_in'}
    assert flagged['issues'][0]['issue'] == 'low_confidence'

    # Exercise the PP-OCRv6 path with token results, without loading an OCR engine.
    def token(text, score):
        return {'text': text, 'score': score, 'box': [10, 20, 30, 40]}
    helpers['read_tokens'] = lambda *args, **kwargs: next(tokens)
    helpers['read_index_tokens'] = lambda *args: [token('295', 0.99)]
    helpers['detect_rows'] = lambda *args: [0, 100]
    token_lists = [[token(good[name], 0.84 if name == 'money_in' else 0.99)]
                   if good[name] else [] for name in columns[1:]]
    tokens = iter(token_lists)
    pp_layout = {'columns': list(range(0, 901, 100))}
    pp_result = helpers['extract_with_v6'](Image.new('RGB', (900, 100)), pp_layout, 0.85, None, None)
    assert pp_result['review_columns'][1] == {'money_in'}
    assert abs(pp_result['confidence'][0]['money_in'] - 0.84) < 1e-12

    image = Image.new('RGB', (820, 200), (200, 200, 200))
    draw = ImageDraw.Draw(image)
    for x, y, text in ((510, 20, '12,345,000'), (670, 20, '87,275,416'),
                       (350, 125, '15,400'), (670, 125, '87,260,016')):
        draw.text((x, y), text, fill='black', font_size=24)
    draw.rectangle((360, 65, 363, 70), fill='black')  # Speck in a blank debit cell.
    draw.text((515, 160), '123', fill='red', font_size=24)  # Seal in a blank credit cell.
    layout = {'native_rows': [0, 100, 200], 'native_columns': [0, 40, 100, 160, 220, 340, 500, 660, 820],
              'glyph_height': 22}
    crops, issues = helpers['numeric_cell_crops'](image, layout)
    assert set(crops) == {(0, 6), (0, 7), (1, 5), (1, 7)}, set(crops)
    assert not issues, issues
    draw.text((515, 65), '456', fill='black', font_size=24)
    _, issues = helpers['numeric_cell_crops'](image, layout)
    assert any(i['row'] == 1 and i['column'] == 'money_in'
               and i['issue'] == 'extra_ink_in_numeric_cell' for i in issues), issues

    flagged['source'] = 'sample.png'
    requests = []
    sheet = SimpleNamespace(id=0, update_title=lambda _: None, resize=lambda **_: None,
                            update=lambda *args, **kwargs: None)
    book = SimpleNamespace(sheet1=sheet, batch_update=lambda body: requests.extend(body['requests']))
    client = SimpleNamespace(create=lambda _: book)
    helpers['export_to_google_sheets'](client, [flagged], [], 'Offline check')
    rule = next(r['addConditionalFormatRule']['rule'] for r in requests if 'addConditionalFormatRule' in r)
    assert rule['ranges'][0]['startColumnIndex'] == 8
    assert rule['ranges'][0]['endColumnIndex'] == 9
    pink = [r['repeatCell']['range'] for r in requests if 'repeatCell' in r
            and r['repeatCell']['range'].get('startRowIndex') == 1]
    assert len(pink) == 1 and pink[0]['startColumnIndex'] == 6, pink
    buffer = BytesIO()
    helpers['export_to_excel'](buffer, [flagged])
    excel = load_workbook(buffer)
    assert excel.active['G2'].fill.fgColor.rgb.endswith('F4CCCC')
    assert excel.active['I2'].fill.fgColor.rgb.endswith('FFF2CC')
    assert excel.active['H2'].fill.patternType is None
    excel.close()
    print('Offline check passed: blank/noise crops skipped, real confidence applied, exports match cell colors.')


if __name__ == '__main__':
    check()
