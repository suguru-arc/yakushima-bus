#!/usr/bin/env python3
"""
gen.py の build() が、既存 yakushima-bus.html の TRIPS (est配列で補完箇所を
明示済み・ブラウザ動作確認済み)をどれだけ再現できるかを検証する。

各トリップについて、公式時刻(非est)を anchors として与え、build() が生成した
est値を実際のTRIPSのest値と突き合わせる。完全一致しない場合も、原因が
「topology.jsonの分単位の丸め」なのか「gen.pyのロジックの欠陥」なのかを
区別できるよう差分を分単位で報告する。
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen import build, load_topology  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = ROOT / "yakushima-bus.html"


def js_to_json(text):
    return re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', text)


def load_trips():
    html = HTML_PATH.read_text(encoding="utf-8")
    m = re.search(r"const TRIPS = (\[.*?\]);\n", html, re.S)
    return json.loads(js_to_json(m.group(1)))


def t2m(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def m2t(m):
    return f"{m // 60}:{m % 60:02d}"


def main():
    topology = load_topology()
    trips = load_trips()

    total_est = 0
    exact = 0
    off_by_1 = 0
    worse = []

    for ti, t in enumerate(trips):
        times = t["times"]
        est = set(t.get("est", []))
        ids = list(times.keys())
        nums = {s: int(re.match(r"s(\d+)", s).group(1)) for s in ids}
        path = [nums[s] for s in ids]
        anchors = {
            nums[s]: t2m(times[s]) for s in ids if s not in est and times[s] != "||"
        }
        if len(anchors) < 2:
            continue
        result = build(anchors, path, topology)
        for s in ids:
            if s not in est:
                continue
            n = nums[s]
            if n not in result:
                worse.append((ti, t["route"], s, "生成されず", times[s]))
                continue
            gen_val, is_est = result[n]
            actual_val = t2m(times[s])
            total_est += 1
            diff = gen_val - actual_val
            if diff == 0:
                exact += 1
            elif abs(diff) == 1:
                off_by_1 += 1
            else:
                worse.append((ti, t["route"], s, m2t(gen_val), times[s]))

    print(f"est(補完)値の総数: {total_est}")
    print(f"完全一致: {exact} ({exact/total_est*100:.1f}%)")
    print(f"±1分差: {off_by_1} ({off_by_1/total_est*100:.1f}%)")
    print(f"それ以上の差 / 生成失敗: {len(worse)}")
    for w in worse[:20]:
        print("  ", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
