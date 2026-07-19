#!/usr/bin/env python3
"""
公式時刻(anchors)とトポロジー(区間所要時間)から、中間停留所の時刻を比例配分で
補完する build(anchors, path) を実装する。

比例配分ロジック:
  ある区間の両端が公式時刻anchorA(時刻tA), anchorB(時刻tB)のとき、その間の
  中間停留所は data/topology.json の区間所要時間(分)を重みとして、
  tA からの累積比率で時刻を配分する。丸めは四捨五入(0.5は切り上げ)。
  例: tA=10:00, tB=10:10, 区間所要 [3,3,4]分 なら
      累積 [3,6,10] -> 比率 [0.3,0.6,1.0] -> +3分,+6分,+10分

このロジックが既存の yakushima-bus.html の TRIPS(est配列で補完箇所を明示済み)を
どれだけ再現できるかを scripts/verify_gen.py で検証すること。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOPOLOGY_PATH = ROOT / "data" / "topology.json"


def load_topology(path=TOPOLOGY_PATH):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    segments = {}
    for key, v in data["segments"].items():
        a, b = key.split("_")
        segments[(int(a), int(b))] = v["minutes"]
    return segments


def segment_minutes(topology, a, b):
    key = (min(a, b), max(a, b))
    return topology.get(key)


def round_half_up(x):
    import math
    return math.floor(x + 0.5)


def build(anchors, path, topology):
    """
    anchors: {stop_num: minutes_since_midnight} 公式時刻のある停留所のみ
    path: [stop_num, ...] このトリップが通る停留所番号の順序リスト(anchorsを含む)
    topology: {(a,b): minutes} 隣接停留所番号ペア -> 所要時間(分)。 build_topology.py の出力。

    戻り値: {stop_num: (minutes_since_midnight, is_estimated)}
    """
    result = {}
    anchor_positions = [i for i, s in enumerate(path) if s in anchors]
    for idx in range(len(anchor_positions) - 1):
        i, j = anchor_positions[idx], anchor_positions[idx + 1]
        stop_a, stop_b = path[i], path[j]
        ta, tb = anchors[stop_a], anchors[stop_b]
        result[stop_a] = (ta, False)
        if j == i + 1:
            continue
        weights = []
        ok = True
        for k in range(i, j):
            w = segment_minutes(topology, path[k], path[k + 1])
            if w is None:
                ok = False
                break
            weights.append(w)
        total_weight = sum(weights) if ok else 0
        total_time = tb - ta
        if total_time < 0:
            total_time += 1440
        cum = 0
        for k, w in enumerate(weights):
            cum += w
            stop = path[i + 1 + k]
            if not ok or total_weight == 0:
                # トポロジーに無い区間(欠測) -> 等分配で近似
                frac = (k + 1) / len(weights)
            else:
                frac = cum / total_weight
            t = ta + round_half_up(total_time * frac)
            result[stop] = (t % 1440, True)
    last = path[anchor_positions[-1]]
    result[last] = (anchors[last], False)
    return result
