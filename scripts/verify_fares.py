#!/usr/bin/env python3
"""
運賃データ(FARE/FSUB)の検証スクリプト。

運賃データを変更するたびに必ず実行すること。過去に目視転記で206ペア中97ペアを
間違えた経緯があるため、以下の2つの独立した検証を両方パスするまで運賃データを
信用しない。

1. 単調性チェック: 起点から遠いゾーンほど運賃が高くなるはず。
   ※「屋久杉自然館(68)」は安房からの内陸支線であり、海岸線の一直線上にないため
     この軸に沿った単調性チェックからは除外する。
2. 既知ペア突き合わせ: PDFのテキストを目視でも確実に読み取れる「隣接ゾーン間の
   運賃」(曖昧さのないセル)を正解データとして用意し、抽出結果と一致するか確認する。
   このリストは座標抽出ロジックとは独立に作成されたものなので、抽出コードの
   バグを検出できる。

使い方:
  python3 scripts/verify_fares.py                     # data/fares_extracted.json を検証
  python3 scripts/verify_fares.py --source html        # yakushima-bus.html 埋め込みデータを検証
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 主要運賃表の軸順(Nagataから遠ざかる順)。
MAIN_ZONE_SEQ = [1, 11, 20, 23, 25, 49, 62, 64, 68, 86, 94, 99, 112, 127, 129]

# 単調性チェックから除外するスプール(内陸支線)ゾーン。
SPUR_ZONES = {68}

AXIS_EXCLUDING_SPURS = [z for z in MAIN_ZONE_SEQ if z not in SPUR_ZONES]

# 目視で確実に読み取れる既知ペア(隣接ゾーン間・曖昧さのないセル)。
# 抽出ロジックとは独立に、PDFのextract_text()生テキストを直接読んで用意した正解データ。
KNOWN_GOOD_FARE = {
    "11_1": 530,
    "20_11": 530,
    "23_20": 140,
    "25_23": 140,
    "49_25": 570,
    "62_49": 410,
    "64_62": 140,
    "68_64": 240,
    "86_68": 570,
    "94_86": 270,
    "99_94": 210,
    "112_99": 350,
    "127_112": 500,
    "129_127": 280,
}
KNOWN_GOOD_FSUB = {
    "s29_s25": 500,   # 白谷雲水峡 -> 小原町
    "s71_s68": 920,   # ヤクスギランド -> 屋久杉自然館
    "s72_s71": 620,   # 紀元杉 -> ヤクスギランド
    "s70_s68": 1000,  # 荒川登山口 -> 屋久杉自然館
}


def load_from_json(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["FARE"], data["FSUB"]


def load_from_html(path):
    html = Path(path).read_text(encoding="utf-8")
    fare = json.loads(re.search(r"const FARE = (\{.*?\});", html).group(1))
    fsub = json.loads(re.search(r"const FSUB = (\{.*?\});", html).group(1))
    return fare, fsub


def check_monotonic(fare, axis):
    """originから見て軸上を遠ざかるにつれ運賃が非減少であることを確認する。"""
    problems = []
    for i, origin in enumerate(axis):
        for direction in (list(reversed(axis[:i])), axis[i + 1:]):
            vals = []
            for d in direction:
                v = fare.get(f"{origin}_{d}")
                if v is not None:
                    vals.append((d, v))
            for k in range(1, len(vals)):
                if vals[k][1] < vals[k - 1][1]:
                    problems.append(
                        f"{origin}: {vals[k-1][0]}={vals[k-1][1]}円 -> "
                        f"{vals[k][0]}={vals[k][1]}円 (遠いのに安い)"
                    )
    return problems


def check_known_pairs(fare, known):
    problems = []
    for key, expected in known.items():
        actual = fare.get(key)
        if actual is None:
            problems.append(f"{key}: データなし(期待値{expected}円)")
        elif actual != expected:
            problems.append(f"{key}: {actual}円 (期待値{expected}円)")
    return problems


def check_symmetry(fare):
    """A_B と B_A は必ず同額のはず。"""
    problems = []
    for key, value in fare.items():
        a, b = key.split("_")
        rev = f"{b}_{a}"
        if fare.get(rev) != value:
            problems.append(f"{key}={value} だが {rev}={fare.get(rev)}")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--source", choices=["json", "html"], default="json",
        help="json: data/fares_extracted.json / html: yakushima-bus.html (default: json)",
    )
    args = ap.parse_args()

    if args.source == "json":
        path = ROOT / "data" / "fares_extracted.json"
        fare, fsub = load_from_json(path)
    else:
        path = ROOT / "yakushima-bus.html"
        fare, fsub = load_from_html(path)
    print(f"検証対象: {path}")
    print(f"FARE: {len(fare)}ペア, FSUB: {len(fsub)}ペア\n")

    ok = True

    print("[1/3] 単調性チェック(軸: " + "→".join(str(z) for z in AXIS_EXCLUDING_SPURS) + ")")
    problems = check_monotonic(fare, AXIS_EXCLUDING_SPURS)
    if problems:
        ok = False
        print(f"  FAIL: {len(problems)}件の逆転を検出")
        for p in problems:
            print(f"    - {p}")
    else:
        print("  PASS")

    print(f"\n[2/3] 既知ペア突き合わせ({len(KNOWN_GOOD_FARE) + len(KNOWN_GOOD_FSUB)}件)")
    problems = check_known_pairs(fare, KNOWN_GOOD_FARE) + check_known_pairs(fsub, KNOWN_GOOD_FSUB)
    if problems:
        ok = False
        print(f"  FAIL: {len(problems)}件不一致")
        for p in problems:
            print(f"    - {p}")
    else:
        print("  PASS")

    print("\n[3/3] 対称性チェック(A→B と B→A が同額か)")
    problems = check_symmetry(fare) + check_symmetry(fsub)
    if problems:
        ok = False
        print(f"  FAIL: {len(problems)}件不一致")
        for p in problems:
            print(f"    - {p}")
    else:
        print("  PASS")

    print()
    if ok:
        print("全チェック PASS。運賃データは信用できます。")
        return 0
    else:
        print("検証に失敗しました。運賃データを確定させないでください。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
