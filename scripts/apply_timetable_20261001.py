#!/usr/bin/env python3
"""
2026年10月1日ダイヤ改正を yakushima-bus.html の TRIPS に反映する。

新時刻表(data/時刻表.pdf, 2026-10-01改正)は文字がアウトライン化されていてテキスト
抽出できないため、scripts/timetable_diff/ の手順(新旧PDFを同条件で描画→Vision OCR→
停留所×列グリッド化→差分セルを新旧並べた画像で全件目視確認)で旧版(2026-03-01改正)と
比較した。主要2表・白谷雲水峡線・紀元杉線・荒川登山バスのうち、変更があったのは
主要2表の次の3便のみ(差分76セルを全件目視確認、残りはOCRの読み誤り)。

  1. 往路 宮之浦港14:10発 栗生橋ゆき -> 14:20発。宮之浦港〜栗生橋の全停留所が+10分
  2. 往路 宮之浦港15:20発 大川の滝ゆき -> 栗生橋止まり(大川の滝17:02着が廃止)
  3. 復路 大川の滝17:45発 -> 大川の滝発が廃止され栗生橋17:29発に。
     栗生橋〜宮之浦港の全停留所が-20分

1と3は公式時刻がすべて同じ分数だけずれているため、比例配分で補完した中間停留所
(est)の時刻も同じ分数だけずらせば補完ロジック(scripts/gen.py)の結果と一致する。

あわせて、時刻表の列見出しと食い違っていた既存の行先表記を修正する
(終点が宮之浦港なのに「永田ゆき」になっていた便など。改正とは無関係の既存バグ)。

便の特定はindexではなく時刻で行う(TRIPSの並び順に依存しない)。何度実行しても
同じ結果になる(適用済みなら何もしない)。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = ROOT / "yakushima-bus.html"

ENTRY_RE = re.compile(r'(s\d+):"(\d{1,2}:\d{2}|\|\|)"')


def t2m(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def m2t(m):
    return f"{m // 60}:{m % 60:02d}"


def parse_times(line):
    block = re.search(r"times:\{(.*?)\}", line).group(1)
    return ENTRY_RE.findall(block)


def replace_times(line, entries):
    body = ", ".join(f'{s}:"{v}"' for s, v in entries)
    return re.sub(r"times:\{.*?\}", lambda _: "times:{" + body + "}", line, count=1)


def remove_from_est(line, stop_ids):
    m = re.search(r"est:\[(.*?)\]", line)
    if not m:
        return line
    ids = [x.strip('"') for x in m.group(1).split(",") if x]
    kept = [x for x in ids if x not in stop_ids]
    return line[:m.start()] + "est:[" + ",".join(f'"{x}"' for x in kept) + "]" + line[m.end():]


def set_head(line, ja, en):
    line = re.sub(r'head_ja:"[^"]*"', f'head_ja:"{ja}"', line, count=1)
    return re.sub(r'head_en:"[^"]*"', f'head_en:"{en}"', line, count=1)


def find(lines, **times):
    """times(stop_id=時刻)をすべて含む便の行番号を返す。ちょうど1件でなければエラー。"""
    hits = [i for i, ln in enumerate(lines) if ln.strip().startswith("{route:")
            and all(f'{s}:"{v}"' in ln for s, v in times.items())]
    if len(hits) != 1:
        raise RuntimeError(f"便の特定に失敗: {times} -> {len(hits)}件")
    return hits[0]


def shift(lines, i, minutes):
    entries = [(s, v if v == "||" else m2t(t2m(v) + minutes)) for s, v in parse_times(lines[i])]
    lines[i] = replace_times(lines[i], entries)


def drop_stops(lines, i, stop_ids):
    entries = [(s, v) for s, v in parse_times(lines[i]) if s not in stop_ids]
    lines[i] = remove_from_est(replace_times(lines[i], entries), stop_ids)


def main():
    html = HTML_PATH.read_text(encoding="utf-8")
    m = re.search(r"(const TRIPS = \[\n)(.*?)(\n\];)", html, re.S)
    lines = m.group(2).split("\n")
    changes = []

    # 1. 往路 宮之浦港14:10発 -> 14:20発(全区間+10分)
    try:
        i = find(lines, s20="14:10", s127="15:48")
        shift(lines, i, +10)
        changes.append("往路 宮之浦港14:10発 栗生橋ゆき -> 14:20発(全停留所+10分)")
    except RuntimeError:
        find(lines, s20="14:20", s127="15:58")  # 適用済みであることを確認

    # 2. 往路 宮之浦港15:20発 大川の滝ゆき -> 栗生橋止まり
    try:
        i = find(lines, s20="15:20", s129="17:02")
        drop_stops(lines, i, {"s128", "s129"})
        lines[i] = set_head(lines[i], "栗生橋ゆき", "For Kuriobashi")
        changes.append("往路 宮之浦港15:20発 大川の滝ゆき -> 栗生橋止まり(16:58着)")
    except RuntimeError:
        find(lines, s20="15:20", s127="16:58")

    # 3. 復路 大川の滝17:45発 -> 栗生橋17:29発(大川の滝発廃止、全区間-20分)
    try:
        i = find(lines, s129="17:45", s20="19:31")
        drop_stops(lines, i, {"s129", "s128"})
        shift(lines, i, -20)
        changes.append("復路 大川の滝17:45発 -> 大川の滝発廃止、栗生橋17:29発(全停留所-20分)")
    except RuntimeError:
        find(lines, s127="17:29", s20="19:11")

    # 既存バグ: 時刻表の列見出しと食い違っていた行先表記を修正
    head_fixes = [
        (dict(s127="8:04", s20="9:44"), "宮之浦港ゆき", "For Miyanoura Port"),
        (dict(s127="8:29", s20="10:09"), "宮之浦港ゆき", "For Miyanoura Port"),
        (dict(s129="11:00", s20="12:44"), "宮之浦港ゆき", "For Miyanoura Port"),
        (dict(s129="15:25", s20="17:09"), "宮之浦港ゆき", "For Miyanoura Port"),
        (dict(s127="17:29", s20="19:11"), "宮之浦港ゆき", "For Miyanoura Port"),
        (dict(s68="17:10", s19="17:55"), "シーサイドホテルゆき", "For Seaside Hotel"),
    ]
    for times, ja, en in head_fixes:
        i = find(lines, **times)
        new = set_head(lines[i], ja, en)
        if new != lines[i]:
            lines[i] = new
            changes.append(f"行先表記修正 {times} -> {ja}")

    if not changes:
        print("変更なし(適用済み)")
        return 0
    HTML_PATH.write_text(html[:m.start(2)] + "\n".join(lines) + html[m.end(2):], encoding="utf-8")
    print("\n".join(changes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
