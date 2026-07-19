#!/usr/bin/env python3
"""
data/stop_coords.json + STOPS(yakushima-bus.html) から、Google マイマップに
インポートできるKMLファイルを生成する。

使い方(Googleマイマップへの取り込み手順):
  1. python3 scripts/export_kml.py を実行 -> yakushima-bus-stops.kml が生成される
  2. https://www.google.com/maps/d/ を開き「+ 新しい地図を作成」
  3. 左上の「インポート」から yakushima-bus-stops.kml を選択
  4. マイマップ画面の検索窓で行きたい場所(例:「Yakushima Bless」)を検索すると、
     インポート済みのバス停ピンと検索結果が同じ地図上に表示され、最寄りの
     バス停を目視で確認できる

精度について: ピンの信頼度は3段階。
  - high(OSMバス停実測データ): そのまま信用できる
  - low(Nominatim地名検索): 停留所名の地名・施設としての位置。誤差がありうる
  - very_low(隣接停留所からの線形補間): あくまで目安。現地の道路形状によっては
    ずれる可能性がある
KML内の説明文(description)に精度を明記しているので、マイマップ上でピンを
クリックすれば確認できる。
"""
import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = ROOT / "yakushima-bus.html"
COORDS_PATH = ROOT / "data" / "stop_coords.json"
OUT_PATH = ROOT / "yakushima-bus-stops.kml"

CONFIDENCE_LABEL = {
    "high": "高精度(OSM実測バス停データ)",
    "low": "低精度(地名検索による近似値)",
    "very_low": "最低精度(近隣停留所からの補間・目安)",
}

# Googleのkml/shapes/にホストされている標準アイコンセット(Google Earth/マイマップが
# 昔から参照可能な既定URL)。バス停アイコンを薄いグレーで着色する。
ICON_URL = "http://maps.google.com/mapfiles/kml/shapes/bus.png"
ICON_COLOR = "ffcccccc"  # KML色形式(aabbggrr)。ccccccは薄いグレー


def js_to_json(text):
    return re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', text)


def load_stops():
    html = HTML_PATH.read_text(encoding="utf-8")
    m = re.search(r"const STOPS = (\[.*?\]);\n", html, re.S)
    return json.loads(js_to_json(m.group(1)))


def main():
    stops = load_stops()
    coords = json.loads(COORDS_PATH.read_text(encoding="utf-8"))

    placemarks = []
    for s in stops:
        c = coords.get(s["id"])
        if not c:
            continue
        num = s["id"][1:]  # "s20" -> "20"(公式路線図・時刻表に印字されている停留所番号)
        name = f"{num} {s['ja']} / {s['en']}"
        conf_label = CONFIDENCE_LABEL.get(c["confidence"], c["confidence"])
        desc = f"{conf_label}"
        if c.get("nominatim_label"):
            desc += f"\n{c['nominatim_label']}"
        placemarks.append(f"""  <Placemark>
    <name>{escape(name)}</name>
    <description>{escape(desc)}</description>
    <styleUrl>#busStop</styleUrl>
    <Point><coordinates>{c['lon']},{c['lat']},0</coordinates></Point>
  </Placemark>""")

    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>屋久島バス停 / Yakushima Bus Stops</name>
  <Style id="busStop">
    <IconStyle>
      <color>{ICON_COLOR}</color>
      <Icon><href>{ICON_URL}</href></Icon>
    </IconStyle>
  </Style>
{chr(10).join(placemarks)}
</Document>
</kml>
"""
    OUT_PATH.write_text(kml, encoding="utf-8")
    print(f"{len(placemarks)}件のバス停を書き出しました -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
