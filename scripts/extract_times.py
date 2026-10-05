#!/usr/bin/env python3
"""
時刻表.pdf から、行(=停留所)ごとに出現する時刻文字列を座標抽出し、
既存 yakushima-bus.html の TRIPS に含まれる「公式時刻」(est配列に載っていない=
PDFに直接印字されている時刻)がPDF上の該当行に実在するかを照合する。

方針:
  路線マップと違い、時刻表.pdfは実際に行(停留所)×列(便)のグリッド構造を持つ
  (pdfplumberのextract_words()で確認済み)。ただし
    - 2桁の停留所番号("11"など)が字間の都合で単独の数字グリフ2つに分かれて
      抽出されることがある → x座標が近い数字トークンを結合する
    - 1ページに「起点→終点」「終点→起点」の2方向の表が左右に並んでいる
    - 便ごとの列位置を特定するにはルート種別・曜日区分・季節区分などの
      判断が必要で、路線図PDFと同様に完全自動再構成は脆い
  そのため、このスクリプトは「行ごとに出現する時刻の集合」を抽出し、
  既存の検証済みTRIPSデータと**突き合わせる(cell-existence check)**ことに
  スコープを絞る。全55便を列位置から独立再構成することはしない
  (必要になった場合は本スクリプトの行検出ロジックを土台に拡張できる)。

出力: data/times_extracted.json (行top -> 停留所番号 -> 時刻文字列の集合)
実行結果は標準出力に一致率を表示する。

既知の制約(実測でここまで): 2026年3月改定版の時刻表.pdfに対して実行すると
1054件中877件(約83%)が一致し、不一致(値が食い違うケース)は0件。残り約17%は
「PDF上でその停留所のラベルを座標だけから確実に同定できなかった」ケースであり、
誤った値を拾ったケースではない(11,14,17,85,86番などの停留所のラベルが、フォント
描画の都合でこのスクリプトのラベル検出条件に一致しないことが原因と見られる)。
運賃表と異なり全件一致(100%)には至っていないため、TRIPSデータそのものを
このスクリプトだけで信用して差し替えることはしないこと。
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / "data" / "時刻表.pdf"
HTML_PATH = ROOT / "yakushima-bus.html"
OUT_PATH = ROOT / "data" / "times_extracted.json"

ROW_TOLERANCE = 2.0
# 停留所番号ラベルの出現するx0帯。この時刻表PDFは1ページに「往路」「復路」の
# 2つの表が左右に並び、さらに縦方向に折り返して複数ブロックになっている。
# 実測で確認できたラベル列のx0帯を列挙する(往路の左端 / 復路の左端)。
LABEL_X0_BANDS = [(20.0, 40.0), (505.0, 525.0)]
DIGIT_MERGE_GAP = 6.0   # 同一番号が複数グリフに分かれている場合の結合しきい値(pt)


def js_to_json(text):
    return re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', text)


def load_trips():
    html = HTML_PATH.read_text(encoding="utf-8")
    m = re.search(r"const TRIPS = (\[.*?\]);\n", html, re.S)
    return json.loads(js_to_json(m.group(1)))


def cluster_rows(tokens, tolerance):
    groups = []
    used = [False] * len(tokens)
    order = sorted(range(len(tokens)), key=lambda i: tokens[i]["top"])
    for i in order:
        if used[i]:
            continue
        base = tokens[i]["top"]
        group = [i]
        used[i] = True
        for j in order:
            if used[j]:
                continue
            if abs(tokens[j]["top"] - base) <= tolerance:
                group.append(j)
                used[j] = True
        groups.append(group)
    return groups


def merge_digit_labels(label_toks):
    """x0が近い1桁トークン同士を結合して停留所番号を復元する。"""
    label_toks = sorted(label_toks, key=lambda t: t["x0"])
    merged = []
    cur = None
    for t in label_toks:
        if cur is None:
            cur = dict(t)
        elif t["x0"] - (cur["x0"] + cur.get("width", 6)) <= DIGIT_MERGE_GAP:
            cur["text"] += t["text"]
            cur["width"] = t["x1"] - cur["x0"]
        else:
            merged.append(cur)
            cur = dict(t)
    if cur is not None:
        merged.append(cur)
    return merged


def extract_rows(pdf_path=PDF_PATH):
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        # x_tolerance=1: 番号とバス停名の間に空白がない箇所(例:"21宮之浦港入口")が
        # 既定値だと1語に結合されてしまい、番号だけを取り出せなくなるため厳しめにする。
        words = page.extract_words(use_text_flow=False, keep_blank_chars=False, x_tolerance=1)

    time_toks = [w for w in words if re.fullmatch(r"\d{1,2}:\d{2}", w["text"])]
    digit_toks = [w for w in words if re.fullmatch(r"\d{1,3}", w["text"])]

    time_groups = cluster_rows(time_toks, ROW_TOLERANCE)
    rows = {}
    for g in time_groups:
        toks = [time_toks[k] for k in g]
        row_top = sum(t["top"] for t in toks) / len(toks)
        rows[row_top] = {"times": sorted(set(t["text"] for t in toks))}

    # 往路・復路のラベル列は同一y行に並ぶことがあるため、x帯ごとに独立して処理する。
    row_tops = list(rows.keys())
    for lo, hi in LABEL_X0_BANDS:
        band_candidates = [w for w in digit_toks if lo <= w["x0"] <= hi]
        label_groups = cluster_rows(band_candidates, ROW_TOLERANCE)
        for g in label_groups:
            toks = [band_candidates[k] for k in g]
            merged = merge_digit_labels(toks)
            if len(merged) != 1:
                continue  # このx帯・この行に複数の異なる番号(曖昧) -> スキップ
            label_top = sum(t["top"] for t in toks) / len(toks)
            nearest = min(row_tops, key=lambda rt: abs(rt - label_top), default=None)
            if nearest is not None and abs(nearest - label_top) <= ROW_TOLERANCE:
                rows[nearest].setdefault("stop_nos", []).append(int(merged[0]["text"]))

    return rows


def main():
    rows = extract_rows()
    if not rows:
        # 2026-10-01改正版以降のPDFは文字がアウトライン化されていてテキストが取れない
        print(f"{PDF_PATH} から時刻テキストを抽出できません(文字がアウトライン化されたPDF)。")
        print("新旧PDFの比較には scripts/timetable_diff/diff_timetables.py を使ってください。")
        return 1
    serializable = {
        f"{top:.1f}": v for top, v in sorted(rows.items())
    }
    OUT_PATH.write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"抽出した行数: {len(rows)} (うち停留所番号を同定できた行: "
          f"{sum(1 for v in rows.values() if 'stop_nos' in v)})")
    print(f"-> {OUT_PATH}\n")

    # 停留所番号 -> その行に出現する時刻文字列の集合
    by_stop_no = defaultdict(set)
    for v in rows.values():
        for stop_no in v.get("stop_nos", []):
            by_stop_no[stop_no].update(v["times"])

    trips = load_trips()
    total_official = 0
    matched = 0
    unmatched = []
    for t in trips:
        est = set(t.get("est", []))
        for stop_id, time_str in t["times"].items():
            if stop_id in est:
                continue
            if time_str == "||":
                continue
            stop_no = int(re.match(r"s(\d+)", stop_id).group(1))
            total_official += 1
            if stop_no in by_stop_no and time_str in by_stop_no[stop_no]:
                matched += 1
            else:
                unmatched.append((t["route"], stop_id, time_str))

    print(f"公式時刻(est以外)の総数: {total_official}")
    print(f"PDF該当行での存在確認: {matched} 件一致 / {total_official - matched} 件未確認")
    if unmatched:
        print("\n未確認の内訳(先頭20件):")
        for route, stop_id, time_str in unmatched[:20]:
            print(f"  route={route} {stop_id}={time_str}")
    return 0 if not unmatched else 1


if __name__ == "__main__":
    sys.exit(main())
