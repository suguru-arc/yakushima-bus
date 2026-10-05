#!/usr/bin/env python3
"""
新旧の時刻表PDFを比較し、主要2表(往路L・復路R)の時刻が異なるセルを一覧にする。

2026-10-01改正版のPDFは文字がアウトライン化されていてテキスト抽出できなかったため、
新旧とも同じ条件で画像に描画し、macOS標準のVision OCR(ocr.swift)で読み取って
「停留所×列」のグリッドに変換して比較する。

  1. 新旧PDFを scale 6(全体)・scale 8(表を4分割)で描画し、それぞれOCR
  2. 各時刻トークンを行(停留所)・列(便)に割り当て、複数回のOCR結果を投票で統合
     (旧PDFにテキストがあればそれを重み3で加える)
  3. 新旧で値が異なるセルを diffs.json に出力し、diff_NN.png に「旧|新」を並べた
     確認用画像を書き出す

★ OCRには桁落ち(17:48 -> 7:48)や読み落としがあるので、diffs.json の結果をそのまま
  信用しないこと。必ず diff_NN.png を全件目視確認し、実際の変更だけを反映する
  (2026-10-01改正では差分76セル中、実際の変更は3便分のみだった)。
  確認後の反映は scripts/apply_timetable_20261001.py を参考に別スクリプトで行う。

★ 行・列の位置(L_STOPS/R_STOPS/L_COLS/R_COLS/PITCH)はこの時刻表のレイアウト固有。
  将来のPDFでレイアウトが変わったら、描画画像を見てこれらの定数を更新すること。

使い方(macOS専用。swiftc と pdfplumber/pypdfium2/Pillow が必要):
  python3 scripts/timetable_diff/diff_timetables.py OLD.pdf NEW.pdf OUTDIR
"""
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent

L_STOPS = [1, 5, 8, 11, 14, 17, 20, 19, 21, 23, 25, 30, 31, 34, 37, 41, 44, 48, 49, 52, 56, 59, 62, 63, 64,
           66, 67, 68, 73, 78, 85, 86, 89, 94, 97, 99, 102, 112, 114, 123, 127, 129]
R_STOPS = [129, 127, 123, 114, 112, 102, 99, 97, 94, 89, 86, 85, 78, 73, 68, 67, 66, 64, 63, 62, 59, 56, 52,
           49, 48, 44, 41, 37, 34, 31, 30, 25, 23, 21, 19, 20, 17, 14, 11, 8, 5, 1]
L_COLS = [87, 110, 133, 156, 178.5, 201, 224, 247, 271, 294, 317, 340, 363, 386, 421, 445, 467]
R_COLS = [572, 595, 618, 641, 664, 687, 709, 732, 755, 778, 802, 825, 848, 872, 906, 929, 952]
PITCH = 9.62                       # 行の間隔(pt)
TABLES = (('L', L_STOPS, L_COLS, (70, 505)), ('R', R_STOPS, R_COLS, (560, 975)))
TABLE_Y = (80, 500)                # 主要2表の縦範囲(pt)
QUADRANTS = [(50, 75, 506, 300), (50, 287, 506, 506), (537, 75, 987, 300), (537, 287, 987, 506)]  # pt
TIME_RE = re.compile(r'^(\d{1,2}):(\d{2})$')


def valid(t):
    m = TIME_RE.match(t)
    return bool(m) and 4 <= int(m.group(1)) <= 21 and int(m.group(2)) < 60


def ocr_binary():
    exe = HERE / 'ocr'
    if not exe.exists() or exe.stat().st_mtime < (HERE / 'ocr.swift').stat().st_mtime:
        subprocess.run(['swiftc', '-O', str(HERE / 'ocr.swift'), '-o', str(exe)], check=True)
    return exe


def render(pdf_path, scale, out_png):
    pdfium.PdfDocument(str(pdf_path))[0].render(scale=scale).to_pil().save(out_png)


def run_ocr(png, out_json, scale, crop_pt=None):
    args = [str(ocr_binary()), str(png), str(out_json)]
    if crop_pt:
        args += [str(int(v * scale)) for v in crop_pt]
    subprocess.run(args, check=True, capture_output=True)
    d = json.loads(Path(out_json).read_text())
    return [dict(text=w['text'], x0=w['x0'] / scale, top=w['top'] / scale) for w in d if w['kind'] == 'time']


def text_tokens(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        ws = pdf.pages[0].extract_words(use_text_flow=False, keep_blank_chars=False, x_tolerance=1)
    return [dict(text=w['text'], x0=w['x0'], top=w['top']) for w in ws if TIME_RE.match(w['text'])]


def table_top0(tokens):
    """行0(表の先頭行)のtop。全体ページのトークンから求める(切り出し画像からは求めない)。"""
    tops = [w['top'] for w in tokens if TABLE_Y[0] < w['top'] < TABLE_Y[1] and 70 <= w['x0'] <= 975]
    return min(tops) if tops else None


def assign(tokens, top0):
    out = {}
    for side, stops, cols, xr in TABLES:
        for w in tokens:
            if not (xr[0] <= w['x0'] <= xr[1] and TABLE_Y[0] < w['top'] < TABLE_Y[1]):
                continue
            ri = round((w['top'] - top0) / PITCH)
            ci = min(range(len(cols)), key=lambda i: abs(cols[i] - w['x0']))
            if 0 <= ri < len(stops) and abs(cols[ci] - w['x0']) <= 9:
                out.setdefault(f"{side}|{stops[ri]}|{ci}", []).append(w['text'])
    return out


def vote(sources):
    votes = {}
    for src, wgt in sources:
        for k, vals in src.items():
            for v in vals:
                votes.setdefault(k, Counter())[v] += wgt if valid(v) else wgt * 0.1
    return {k: c.most_common(1)[0][0] for k, c in votes.items()}


def build_grid(pdf_path, work, tag):
    """PDF -> (グリッド, 描画画像(scale8), 行0のtop(OCR基準))"""
    full = work / f'{tag}6.png'; big = work / f'{tag}8.png'
    render(pdf_path, 6, full); render(pdf_path, 8, big)
    full_toks = run_ocr(full, work / f'{tag}6.json', 6)
    top0 = table_top0(full_toks)
    sources = [(assign(full_toks, top0), 1)]
    for qi, q in enumerate(QUADRANTS):
        sources.append((assign(run_ocr(big, work / f'{tag}8_{qi}.json', 8, q), top0), 1))
    txt = text_tokens(pdf_path)
    if txt:  # テキストが取れるPDFなら正確なのでテキストを重く
        sources.append((assign(txt, table_top0(txt)), 3))
    return vote(sources), Image.open(big), top0


def order_key(k):
    side, stop, col = k.split('|')
    return (side, (L_STOPS if side == 'L' else R_STOPS).index(int(stop)), int(col))


def montage(keys, imgs, top0s, out, per=13):
    font = ImageFont.truetype('/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc', 28)
    sc = 8
    def crop(which, key):
        side, stop, col = key.split('|')
        stops = L_STOPS if side == 'L' else R_STOPS
        x = (L_COLS if side == 'L' else R_COLS)[int(col)]
        y = top0s[which] + stops.index(int(stop)) * PITCH
        return imgs[which].crop((int((x - 26) * sc), int((y - 6) * sc), int((x + 48) * sc), int((y + 13) * sc)))
    pages = []
    for p in range(0, len(keys), per):
        rows = []
        for k in keys[p:p + per]:
            o, n = crop('old', k), crop('new', k)
            row = Image.new('RGB', (260 + o.width + 20 + n.width, max(o.height, n.height) + 8), 'white')
            d = ImageDraw.Draw(row)
            d.text((8, row.height // 2 - 16), k, fill='black', font=font)
            row.paste(o, (260, 4)); row.paste(n, (260 + o.width + 20, 4))
            d.line((260 + o.width + 10, 0, 260 + o.width + 10, row.height), fill='red', width=4)
            rows.append(row)
        m = Image.new('RGB', (max(r.width for r in rows), sum(r.height for r in rows)), 'white')
        y = 0
        for r in rows:
            m.paste(r, (0, y)); y += r.height
        path = out / f'diff_{p // per:02d}.png'
        m.save(path); pages.append(path.name)
    return pages


def main():
    if len(sys.argv) != 4:
        print(__doc__); return 1
    old_pdf, new_pdf, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    old, old_img, old_top0 = build_grid(old_pdf, out, 'old')
    new, new_img, new_top0 = build_grid(new_pdf, out, 'new')
    keys = sorted(set(old) | set(new), key=order_key)
    diffs = [[k, old.get(k), new.get(k)] for k in keys if old.get(k) != new.get(k)]
    (out / 'grids.json').write_text(json.dumps({'old': old, 'new': new}, ensure_ascii=False, indent=0))
    (out / 'diffs.json').write_text(json.dumps(diffs, ensure_ascii=False, indent=0))
    pages = montage([d[0] for d in diffs], {'old': old_img, 'new': new_img},
                    {'old': old_top0, 'new': new_top0}, out)
    print(f'セル数 旧{len(old)} 新{len(new)} / 差分{len(diffs)}セル -> {out}/diffs.json')
    print('目視確認用:', ', '.join(pages))
    return 0


if __name__ == '__main__':
    sys.exit(main())
