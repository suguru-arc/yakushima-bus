#!/usr/bin/env python3
"""
STOPS(130停留所)の緯度経度を取得する。

路線マップPDFは模式図(実際の地理とは無関係な概念図)のため座標を含まない。
このスクリプトは複数の外部データソースを優先順位付きで組み合わせる:

  1. buste.in (https://buste.in) — 種子島・屋久島交通の運行バス停を専門に
     収録したサイト。一覧ページのLeafletマップ初期化スクリプト内に全129件の
     停留所名・よみがな・住所・緯度経度がJSリテラルとして埋め込まれており、
     curlで直接取得できる。同社バスの停留所として個別に採番・確認された
     データなので最も信頼できる(ただしサイト自身が明記する通り2010年頃の
     データが中心で、新しい停留所は未収録の場合がある)。
  2. Overpass API (OpenStreetMap) — highway=bus_stop / public_transport=platform
     ノードのうち、`ref`タグが本アプリの停留所番号と一致するもの、または
     名称が完全一致するもの。
  3. Nominatim(OpenStreetMapの地名検索) — 屋久島のバウンディングボックス内に
     限定して「停留所名 屋久島」を検索する。
     ★重要な教訓: バウンディングボックス制約(bounded=1 & viewbox)を付けずに
     検索すると、「八幡神社」「大崎橋」のような全国にありふれた地名が
     愛知県・長崎県など全く別の場所にマッチする事故が実際に起きた。
     地理制約は必須。
  4. 上記いずれでも見つからない停留所は、停留所番号が近い(=物理的に隣接して
     いる可能性が高い)前後の解決済み停留所の座標を線形補間する(最終手段、
     精度は低い)。

出力: data/stop_coords.json
  {"s1": {"lat":..,"lon":..,"source":"busteins"|"osm_ref"|"osm_name"|"nominatim"|"interpolated",
          "confidence":"high"|"medium"|"low"|"very_low"}, ...}
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = ROOT / "yakushima-bus.html"
OUT_PATH = ROOT / "data" / "stop_coords.json"
UA = "Mozilla/5.0 yakushima-bus-app/1.0 (offline transit search tool for tourists)"

BUSTEINS_LIST_URL = "https://buste.in/search/bus/list/BusteisBusNm/map/1680"
BUSTEINS_CACHE = ROOT / "data" / "busteins_raw.json"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_CACHE = ROOT / "data" / "overpass_bus_stops_cache.json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# 屋久島全体を覆うバウンディングボックス(south,west,north,east)
BBOX = (30.10, 130.25, 30.55, 130.70)

# buste.inの2010年頃データには無い/名称が異なる停留所の手動対応表。
# {stop_id: busteinsのname文字列}
MANUAL_ALIASES = {
    "s24": "宮之浦支所",       # 宮之浦支所前
    "s30": "Aコープ前",        # Ａコープ前(全角A)
    "s38": "楠川",             # 楠川温泉入口(温泉入口の個別データなし、近傍代用)
    "s46": "診療所前",         # 小瀬田診療所前
    "s49": "空港",             # 屋久島空港
    "s112": "海中温泉",        # 平内海中温泉
    "s801": "吉田",            # 吉田橋(近傍代用、実際は吉田と白河の間)
}


def js_to_json(text):
    return re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', text)


def load_stops():
    html = HTML_PATH.read_text(encoding="utf-8")
    m = re.search(r"const STOPS = (\[.*?\]);\n", html, re.S)
    return json.loads(js_to_json(m.group(1)))


def in_bbox(lat, lon):
    south, west, north, east = BBOX
    return south <= float(lat) <= north and west <= float(lon) <= east


def norm(s):
    if not s:
        return ""
    s = re.sub(r"[ \-ー・（）()]", "", s)
    s = s.replace("Ａ", "A").replace("ａ", "a")
    return s.lower()


def fetch_busteins():
    if BUSTEINS_CACHE.exists():
        print(f"  (キャッシュを使用: {BUSTEINS_CACHE})")
        return json.loads(BUSTEINS_CACHE.read_text(encoding="utf-8"))
    req = urllib.request.Request(BUSTEINS_LIST_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    marker_re = re.compile(r"L\.marker\(\[([\d.\-]+),\s*([\d.\-]+)\][^;]*bindPopup\(html(\d+)\)")
    markers = {m.group(3): (m.group(1), m.group(2)) for m in marker_re.finditer(html)}
    html_re = re.compile(r'var html(\d+)\s*=\s*"([^"]*(?:\\.[^"]*)*)"')

    results = []
    for hm in html_re.finditer(html):
        idx, raw = hm.group(1), hm.group(2)
        name_m = re.search(r">([^<]+)バス停</a>", raw)
        yomi_m = re.search(r"\(([^)]+)\)<br", raw)
        addr_m = re.search(r"住所：([^<]+)<", raw)
        pos = markers.get(idx)
        if not (name_m and pos):
            continue
        results.append({
            "name": name_m.group(1),
            "yomi": yomi_m.group(1) if yomi_m else None,
            "addr": addr_m.group(1) if addr_m else None,
            "lat": pos[0], "lon": pos[1],
        })
    BUSTEINS_CACHE.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def fetch_overpass():
    if OVERPASS_CACHE.exists():
        print(f"  (キャッシュを使用: {OVERPASS_CACHE})")
        return json.loads(OVERPASS_CACHE.read_text(encoding="utf-8"))["elements"]
    query = f"""
[out:json][timeout:90];
(
  node["highway"="bus_stop"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  node["public_transport"="platform"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
);
out body;
""".strip()
    req = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": UA},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=100) as resp:
                data = json.load(resp)
            OVERPASS_CACHE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return data["elements"]
        except Exception as ex:
            print(f"  Overpass取得失敗(試行{attempt+1}/3): {ex}")
            time.sleep(5)
    print("  Overpass APIから取得できませんでした。スキップします。")
    return []


def nominatim_search(query):
    # bounded=1 + viewbox で屋久島のバウンディングボックス外の結果を除外する。
    # 制約なしだと「八幡神社」「大崎橋」のような全国にありふれた地名が
    # 遠く離れた県の同名スポットにマッチしてしまう事故が実際に起きたため必須。
    south, west, north, east = BBOX
    viewbox = f"{west},{north},{east},{south}"
    params = {"q": query, "format": "json", "limit": 1, "viewbox": viewbox, "bounded": 1}
    url = NOMINATIM_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def main():
    stops = load_stops()
    print(f"STOPS: {len(stops)}件\n")

    print("[1/4] buste.inから取得中...")
    busteins = fetch_busteins()
    print(f"  {len(busteins)}件")
    busteins_by_name = {norm(b["name"]): b for b in busteins}

    result = {}
    for s in stops:
        alias = MANUAL_ALIASES.get(s["id"])
        key = norm(alias) if alias else norm(s["ja"])
        b = busteins_by_name.get(key)
        if b and in_bbox(b["lat"], b["lon"]):
            conf = "high" if not alias else "medium"
            result[s["id"]] = {
                "lat": b["lat"], "lon": b["lon"],
                "source": "busteins", "confidence": conf,
            }
    print(f"  一致: {len(result)}/{len(stops)}件\n")

    remaining = [s for s in stops if s["id"] not in result]
    if remaining:
        print(f"[2/4] Overpass API(OSM)でフォールバック中... (残り{len(remaining)}件)")
        elements = fetch_overpass()
        by_ref, name_index = {}, {}
        for e in elements:
            tags = e.get("tags", {})
            ref = tags.get("ref")
            if ref and ref.isdigit():
                by_ref.setdefault(int(ref), e)
            for key in ("name", "name:ja", "name:en"):
                v = tags.get(key)
                if v:
                    name_index.setdefault(norm(v), e)
        found = 0
        for s in remaining:
            num = int(re.match(r"s(\d+)", s["id"]).group(1))
            e = by_ref.get(num)
            source = "osm_ref"
            if e is None:
                e = name_index.get(norm(s["ja"]))
                source = "osm_name"
            if e is not None and in_bbox(e["lat"], e["lon"]):
                result[s["id"]] = {"lat": e["lat"], "lon": e["lon"], "source": source, "confidence": "high"}
                found += 1
        print(f"  一致: {found}/{len(remaining)}件\n")

    remaining = [s for s in stops if s["id"] not in result]
    if remaining:
        print(f"[3/4] Nominatimでフォールバック中... (残り{len(remaining)}件、1件/秒)")
        for i, s in enumerate(remaining):
            query = f"{s['ja']} 屋久島"
            try:
                hits = nominatim_search(query)
            except Exception as ex:
                print(f"  [{i+1}/{len(remaining)}] {s['ja']}: エラー {ex}")
                hits = []
            if hits and in_bbox(hits[0]["lat"], hits[0]["lon"]):
                h = hits[0]
                result[s["id"]] = {
                    "lat": h["lat"], "lon": h["lon"], "source": "nominatim", "confidence": "low",
                    "nominatim_label": h.get("display_name"),
                }
                print(f"  [{i+1}/{len(remaining)}] {s['ja']}: 見つかりました")
            elif hits:
                print(f"  [{i+1}/{len(remaining)}] {s['ja']}: 範囲外の結果を棄却")
            else:
                print(f"  [{i+1}/{len(remaining)}] {s['ja']}: 見つかりませんでした")
            time.sleep(1)
        print()

    remaining = [s for s in stops if s["id"] not in result]
    if remaining:
        print(f"[4/4] 隣接停留所からの線形補間... (残り{len(remaining)}件)")
        nums_sorted = sorted(int(s["id"][1:]) for s in stops if s["id"] in result and s["id"][1:].isdigit())
        for s in remaining:
            if not s["id"][1:].isdigit():
                continue
            num = int(s["id"][1:])
            lower = max([n for n in nums_sorted if n < num], default=None)
            upper = min([n for n in nums_sorted if n > num], default=None)
            if lower is None or upper is None:
                print(f"  {s['ja']}: 補間不可(前後に解決済み停留所がありません)")
                continue
            lo, hi = result[f"s{lower}"], result[f"s{upper}"]
            frac = (num - lower) / (upper - lower)
            lat = float(lo["lat"]) + (float(hi["lat"]) - float(lo["lat"])) * frac
            lon = float(lo["lon"]) + (float(hi["lon"]) - float(lo["lon"])) * frac
            result[s["id"]] = {
                "lat": f"{lat:.7f}", "lon": f"{lon:.7f}",
                "source": "interpolated", "confidence": "very_low",
                "interpolated_between": [f"s{lower}", f"s{upper}"],
            }
            print(f"  {s['ja']}: s{lower}とs{upper}の間で補間")

    # 最終防衛ライン: どのソースであれbbox外の座標は採用しない
    for sid in list(result):
        v = result[sid]
        if not in_bbox(v["lat"], v["lon"]):
            print(f"  警告: {sid} の座標が屋久島の範囲外のため除外します: {v}")
            del result[sid]

    still_missing = [s for s in stops if s["id"] not in result]
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\n合計: {len(result)}/{len(stops)}件の座標を取得")
    for conf in ("high", "medium", "low", "very_low"):
        n = sum(1 for v in result.values() if v["confidence"] == conf)
        if n:
            print(f"  {conf}: {n}")
    if still_missing:
        print(f"  未解決: {len(still_missing)}件")
        for s in still_missing:
            print(f"    {s['id']} {s['ja']} {s['en']}")
    print(f"-> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
