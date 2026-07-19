#!/usr/bin/env python3
"""
隣接停留所間の所要時間(トポロジー)を求める。

「路線マップと所要時間.pdf」は表ではなく装飾的な路線図の画像で、停留所名や
分数ラベルが図の周りに散らばっている(pdfplumberのextract_text()でほぼ判読不能・
find_tables()も図中の線の交差を誤検出するのみ)。そのため、このPDFを直接
座標解析して129停留所間の所要時間グラフを毎回自動再構成するのは脆く現実的でない。

代わりに、既にブラウザ動作確認済みの yakushima-bus.html の TRIPS データ
(公式時刻から比例配分で補完済み・est配列で補完箇所を明示)から、隣接する
停留所番号ペアの時刻差を逆算してトポロジーを導出する。これは「路線マップと
所要時間.pdf」を人間が読み取って比例配分ロジックで組み込んだ結果を経由した
間接的な情報源だが、以下の理由で信頼できる:
  - 55便すべてを横断して同じセグメントの値をクロスチェックできる
  - 起点・終点ともに公式時刻(非est)である区間は「停留所間の物理的な所要時間」
    ではなく「停留所での停車時間のばらつき」を含むため、トポロジーの対象からは
    除外する(例: 宮之浦港(20)は便によって停車時間が1〜6分と大きくばらつく)
  - est(補完値)が関わる区間のみを対象にすると、120区間中114区間で全便一致、
    残り6区間も±1分の丸め誤差のみ(最頻値を採用)

出力: data/topology.json
  {"segments": {"a_b": {"minutes": N, "confidence": "high"|"low", "samples": {...}}}}

今後、時刻表が改定された場合はこのファイルをそのまま再利用し、gen.py が
新しい公式時刻(anchors)と組み合わせて中間停留所の時刻を再補完する。
路線図PDFが差し替わった場合のみ、このスクリプトの再実行(またはtopology.jsonの
手動更新)が必要になる。
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = ROOT / "yakushima-bus.html"
OUT_PATH = ROOT / "data" / "topology.json"

# 停留所ID順序表の末尾に追加登録された特殊停留所(番号が物理的な並び順を
# 反映していない)。s801(吉田橋)は実際にはs8(吉田)とs9(白河)の間に位置する。
EXTRA_ADJACENT_PAIRS = {(8, 801), (9, 801)}


def js_to_json(text):
    return re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', text)


def load_trips():
    html = HTML_PATH.read_text(encoding="utf-8")
    m = re.search(r"const TRIPS = (\[.*?\]);\n", html, re.S)
    return json.loads(js_to_json(m.group(1)))


def t2m(s):
    if s == "||":
        return None
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def build_topology(trips):
    seg = defaultdict(Counter)
    for t in trips:
        times = t["times"]
        est = set(t.get("est", []))
        ids = list(times.keys())
        nums = [int(re.match(r"s(\d+)", i).group(1)) for i in ids]
        for i in range(len(ids) - 1):
            a, b = ids[i], ids[i + 1]
            na, nb = nums[i], nums[i + 1]
            pair = (min(na, nb), max(na, nb))
            if abs(na - nb) != 1 and pair not in EXTRA_ADJACENT_PAIRS:
                continue
            if a not in est and b not in est:
                continue  # 両端が公式時刻同士 = 停車時間のばらつきを含む可能性、対象外
            ta, tb = t2m(times[a]), t2m(times[b])
            if ta is None or tb is None:
                continue
            diff = tb - ta
            if diff < 0:
                diff += 1440
            seg[(min(na, nb), max(na, nb))][diff] += 1

    segments = {}
    for (a, b), counter in seg.items():
        total = sum(counter.values())
        best_val, best_count = counter.most_common(1)[0]
        confidence = "high" if len(counter) == 1 else (
            "medium" if best_count / total >= 0.7 else "low"
        )
        segments[f"{a}_{b}"] = {
            "minutes": best_val,
            "confidence": confidence,
            "samples": dict(counter),
        }
    return segments


def main():
    trips = load_trips()
    segments = build_topology(trips)
    low = [k for k, v in segments.items() if v["confidence"] == "low"]
    medium = [k for k, v in segments.items() if v["confidence"] == "medium"]
    OUT_PATH.write_text(
        json.dumps({"segments": segments}, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"セグメント数: {len(segments)}")
    print(f"  confidence=high: {sum(1 for v in segments.values() if v['confidence']=='high')}")
    print(f"  confidence=medium: {len(medium)} {medium}")
    print(f"  confidence=low: {len(low)} {low}")
    print(f"-> {OUT_PATH}")


if __name__ == "__main__":
    sys.exit(main())
