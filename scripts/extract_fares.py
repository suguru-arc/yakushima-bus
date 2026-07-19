#!/usr/bin/env python3
"""
料金表.pdf から運賃マトリクス(FARE)とサブ運賃表(FSUB)を機械的に抽出する。

抽出方式（前セッションで確立、地雷を踏んだ末の結論）:
  - 目視転記は絶対に行わない。206ペア中97ペアを取り違えた実績があるため。
  - 運賃表は「階段状の三角マトリクス」。各行が1つの主要停留所(ゾーン)に対応し、
    その行には「自分より手前(Nagata側)にあるゾーンとの運賃」が並ぶ。
  - 列のx座標は一定間隔(実測 約42.6pt)のグリッド上に並ぶ。列の位置は行に関わらず
    「どのゾーンに対する運賃か」で固定される(欠番のセルは単に存在しないだけで、
    ズレたりはしない)。値の有無ではなく x 座標そのものでターゲットゾーンを同定する。
  - 運賃は必ず10円単位(下1桁が0)。一方でゾーンIDの一部(112,127,129)は10の倍数
    ではないため、「下1桁が0」でフィルタするだけで運賃の数値とゾーンIDラベルの
    数値を確実に区別できる(実測で確認済み)。
  - 各行の左側には「対角線ラベル」としてその行自身のゾーンIDが単独の数字トークンで
    印字されている。ラベルのtop座標はデータ行のtopと最大5pt程度ズレることがある
    (フォント折返しの影響)。したがって単純な同一top近傍クラスタリングではなく、
    「候補ラベル(テキスト一致 かつ x0がデータ列より左)の中でtop差が最小のもの」を
    選ぶ最近傍マッチングで同定する。

出力: data/fares_extracted.json に {"FARE": {...}, "FSUB": {...}, "ZONE_SEQ": [...]} を書く。
検証は別途 scripts/verify_fares.py で行うこと。
"""
import json
import re
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / "data" / "料金表.pdf"
OUT_PATH = ROOT / "data" / "fares_extracted.json"

# 主要運賃表の対角ゾーン列(印字順=Nagataから遠ざかる順)。
MAIN_ZONE_SEQ = [1, 11, 20, 23, 25, 49, 62, 64, 68, 86, 94, 99, 112, 127, 129]

# サブ運賃表(白谷雲水峡・ヤクスギランド・紀元杉・荒川登山口)の行ゾーンIDとターゲット列
# (PDF上でx0昇順に並ぶ順)。
SUB_TARGETS = {
    29: [25, 23, 20],       # 白谷雲水峡
    71: [68, 64, 62],       # ヤクスギランド
    72: [71, 68, 64, 62],   # 紀元杉(ヤクスギランドとの区間も含む)
    70: [68],                # 荒川登山口
}

DATA_ROW_TOLERANCE = 2.0    # データ値トークンを同一行とみなすtopの許容差(pt)
LABEL_MAX_TOP_DIFF = 8.0    # ラベル探索時に許容する最大top差(pt)
GRID_TOLERANCE = 6.0        # 列グリッドに乗っているとみなすx0の許容差(pt)


def load_number_tokens(page):
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    return [w for w in words if re.fullmatch(r"\d+", w["text"])]


def cluster_by_top(tokens, tolerance):
    """topが近い(連鎖的にではなく単純平均で)トークンを同一行としてグルーピング。"""
    groups = []
    used = [False] * len(tokens)
    order = sorted(range(len(tokens)), key=lambda i: tokens[i]["top"])
    for i in order:
        if used[i]:
            continue
        base_top = tokens[i]["top"]
        group = [i]
        used[i] = True
        for j in order:
            if used[j]:
                continue
            if abs(tokens[j]["top"] - base_top) <= tolerance:
                group.append(j)
                used[j] = True
        groups.append(group)
    groups.sort(key=lambda g: sum(tokens[k]["top"] for k in g) / len(g))
    return groups


def find_nearest_label(tokens, zone_id, row_top, max_x0):
    """zone_idと文字列が一致し、x0がmax_x0未満のトークンのうちtop差が最小のものを返す。"""
    text = str(zone_id)
    candidates = [
        t for t in tokens
        if t["text"] == text and t["x0"] < max_x0
    ]
    if not candidates:
        return None
    best = min(candidates, key=lambda t: abs(t["top"] - row_top))
    if abs(best["top"] - row_top) > LABEL_MAX_TOP_DIFF:
        return None
    return best


def extract(pdf_path=PDF_PATH):
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        all_tokens = load_number_tokens(page)

    # 運賃の値トークン: 3桁以上 かつ 10円単位(下1桁が0)。
    # これによりゾーンIDラベル(112,127,129など10の倍数でないもの)を確実に除外する。
    value_tokens = [
        t for t in all_tokens
        if len(t["text"]) >= 3 and int(t["text"]) % 10 == 0
    ]

    data_row_groups = cluster_by_top(value_tokens, DATA_ROW_TOLERANCE)
    data_rows = []
    for g in data_row_groups:
        toks = sorted((value_tokens[k] for k in g), key=lambda t: t["x0"])
        row_top = sum(t["top"] for t in toks) / len(toks)
        data_rows.append({"top": row_top, "tokens": toks})

    # x座標グリッドを推定(基準列=Nagata(1)の列は最大x0)
    all_x0 = [t["x0"] for row in data_rows for t in row["tokens"]]
    x_ref = max(all_x0)
    spacing = 42.6
    # 実測値で微調整(既知のjが1以上のトークンから平均を取る)
    diffs = []
    for x in all_x0:
        j = round((x_ref - x) / spacing)
        if j >= 1:
            diffs.append((x_ref - x) / j)
    if diffs:
        spacing = sum(diffs) / len(diffs)

    def col_zone(x0):
        j = round((x_ref - x0) / spacing)
        if 0 <= j < len(MAIN_ZONE_SEQ):
            return MAIN_ZONE_SEQ[j]
        return None

    # 各データ行にゾーンIDラベルを割り当てる(メイン14行 + サブ4行 = 18行のはず)。
    all_zone_ids = MAIN_ZONE_SEQ[1:] + list(SUB_TARGETS.keys())
    assigned = {}  # zone_id -> data_row dict
    unmatched_rows = []
    for row in data_rows:
        min_x0 = row["tokens"][0]["x0"]
        best_zone = None
        best_diff = None
        for zid in all_zone_ids:
            if zid in assigned:
                continue
            label = find_nearest_label(all_tokens, zid, row["top"], min_x0)
            if label is None:
                continue
            diff = abs(label["top"] - row["top"])
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_zone = zid
        if best_zone is None:
            unmatched_rows.append(row)
        else:
            assigned[best_zone] = row

    if unmatched_rows:
        tops = [r["top"] for r in unmatched_rows]
        raise RuntimeError(f"ラベルを同定できないデータ行があります(top={tops})")

    missing = set(MAIN_ZONE_SEQ[1:]) - set(assigned)
    if missing:
        raise RuntimeError(f"主要運賃表: 行が見つからないゾーン: {sorted(missing)}")
    missing_sub = set(SUB_TARGETS) - set(assigned)
    if missing_sub:
        raise RuntimeError(f"サブ運賃表: 行が見つからないゾーン: {sorted(missing_sub)}")

    FARE = {}
    for row_zone in MAIN_ZONE_SEQ[1:]:
        row = assigned[row_zone]
        for t in row["tokens"]:
            col_zone_id = col_zone(t["x0"])
            value = int(t["text"])
            if col_zone_id is None:
                raise RuntimeError(
                    f"ゾーン{row_zone}の行: x0={t['x0']:.1f}がグリッドに一致しません(value={value})"
                )
            if col_zone_id == row_zone:
                raise RuntimeError(
                    f"ゾーン{row_zone}の行で自分自身の列({col_zone_id})に値が割当てられました"
                )
            FARE[f"{row_zone}_{col_zone_id}"] = value
            FARE[f"{col_zone_id}_{row_zone}"] = value

    FSUB = {}
    for row_zone, targets in SUB_TARGETS.items():
        row = assigned[row_zone]
        if len(row["tokens"]) != len(targets):
            raise RuntimeError(
                f"サブ表ゾーン{row_zone}: 値の個数({len(row['tokens'])})が"
                f"想定ターゲット数({len(targets)})と不一致"
            )
        for t, target in zip(row["tokens"], targets):
            value = int(t["text"])
            FSUB[f"s{row_zone}_s{target}"] = value
            FSUB[f"s{target}_s{row_zone}"] = value

    return {
        "ZONE_SEQ": MAIN_ZONE_SEQ,
        "FARE": FARE,
        "FSUB": FSUB,
    }


def main():
    result = extract()
    OUT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"FARE: {len(result['FARE'])} pairs, FSUB: {len(result['FSUB'])} pairs")
    print(f"-> {OUT_PATH}")


if __name__ == "__main__":
    sys.exit(main())
