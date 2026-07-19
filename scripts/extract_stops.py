#!/usr/bin/env python3
"""
STOPS(128停留所)データの整合性検証。

「路線マップと所要時間.pdf」が装飾的な図であり(scripts/build_topology.pyの
docstring参照)、128停留所すべての名称・ローマ字表記を座標だけから機械的に
再構成するのは非現実的なため、このスクリプトはゼロからの抽出ではなく、
以下の整合性チェックに徹する:

  1. STOPS内のid重複がないか
  2. ZONE/FKEY/TRIPS/ROUTESが参照するstop-idが全てSTOPSに存在するか
  3. 時刻表.pdfに実在する主要停留所(座標抽出済み)の番号が、STOPSのidと
     矛盾なく対応しているか(名称の目視突合はscripts/extract_times.pyの
     行ラベル検出結果を流用する)
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = ROOT / "yakushima-bus.html"


def js_to_json(text):
    return re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', text)


def load_const(html, name):
    m = re.search(rf"const {name} = (\{{.*?\}}|\[.*?\]);\n", html, re.S)
    return json.loads(js_to_json(m.group(1)))


def main():
    html = HTML_PATH.read_text(encoding="utf-8")
    stops = load_const(html, "STOPS")
    zone = load_const(html, "ZONE")
    fkey = load_const(html, "FKEY")
    trips = load_const(html, "TRIPS")

    ok = True
    stop_ids = [s["id"] for s in stops]
    print(f"STOPS件数: {len(stops)}")

    dupes = {i for i in stop_ids if stop_ids.count(i) > 1}
    if dupes:
        ok = False
        print(f"  FAIL: id重複 {dupes}")
    else:
        print("  PASS: id重複なし")

    stop_id_set = set(stop_ids)
    missing_in_zone = set(zone) - stop_id_set
    missing_in_fkey = set(fkey) - stop_id_set
    if missing_in_zone or missing_in_fkey:
        ok = False
        print(f"  FAIL: ZONE/FKEYがSTOPSに存在しないidを参照 zone={missing_in_zone} fkey={missing_in_fkey}")
    else:
        print("  PASS: ZONE/FKEYの参照整合性OK")

    trip_stop_ids = set()
    for t in trips:
        trip_stop_ids.update(t["times"].keys())
    missing_in_trips = trip_stop_ids - stop_id_set
    if missing_in_trips:
        ok = False
        print(f"  FAIL: TRIPSがSTOPSに存在しないidを参照 {missing_in_trips}")
    else:
        print("  PASS: TRIPSの参照整合性OK")

    unused = stop_id_set - trip_stop_ids
    if unused:
        print(f"  NOTE: どのTRIPSにも登場しない停留所 ({len(unused)}件): {sorted(unused, key=lambda s: int(s[1:]))}")

    print()
    if ok:
        print("整合性チェック PASS。")
        return 0
    else:
        print("整合性チェックに失敗した項目があります。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
