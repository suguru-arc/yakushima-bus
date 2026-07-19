#!/usr/bin/env python3
"""
yakushima-bus.html を「抽出済みデータで再生成」し、現在のファイルと差分がないか
確認する。ダイヤ・運賃改定のたびにPDFを差し替えて再現できるパイプラインの要。

現状の対応範囲:
  - FARE/FSUB: scripts/extract_fares.py の出力(data/fares_extracted.json)で
    完全に置き換える(100%検証済み、scripts/verify_fares.py参照)。
  - STOPS/ROUTES/TRIPS/ZONE/FKEY: 現時点では現在のyakushima-bus.htmlの値を
    そのまま使う(自動置き換えはしない)。理由:
      * STOPS: 元データが装飾的な路線図PDFで機械抽出が非現実的
        (scripts/extract_stops.pyは整合性検証のみ)
      * TRIPS: scripts/gen.py による再生成は99.7%の再現率(scripts/verify_gen.py)
        であり、100%でない限り自動的に本番データへ反映すべきではない

運賃データを更新する場合の使い方:
  1. data/料金表.pdf を新しいものに差し替える
  2. python3 scripts/extract_fares.py    # data/fares_extracted.json を再生成
  3. python3 scripts/verify_fares.py     # 全チェックPASSを確認してから
  4. python3 scripts/build_html.py       # yakushima-bus.html のFARE/FSUBを更新
  5. ブラウザで実際に動作確認してからコミットする
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = ROOT / "yakushima-bus.html"
FARES_JSON = ROOT / "data" / "fares_extracted.json"


def to_js_object(d):
    """Pythonのdictを、既存htmlと同じ書式(キーはダブルクオート、区切りにスペースなし)のJS object literalへ。"""
    parts = ",".join(f'"{k}":{v}' for k, v in d.items())
    return "{" + parts + "}"


def main():
    if not FARES_JSON.exists():
        print("data/fares_extracted.json がありません。先に scripts/extract_fares.py を実行してください。")
        return 1

    extracted = json.loads(FARES_JSON.read_text(encoding="utf-8"))
    html = HTML_PATH.read_text(encoding="utf-8")

    before = html
    html = re.sub(
        r"const FARE = \{.*?\};",
        lambda _: f"const FARE = {to_js_object(extracted['FARE'])};",
        html, count=1,
    )
    html = re.sub(
        r"const FSUB = \{.*?\};",
        lambda _: f"const FSUB = {to_js_object(extracted['FSUB'])};",
        html, count=1,
    )

    if html == before:
        print("差分なし(既にPDF抽出結果と一致しています)。")
    else:
        HTML_PATH.write_text(html, encoding="utf-8")
        print("yakushima-bus.html のFARE/FSUBを抽出結果で更新しました。")
        print("次に scripts/verify_fares.py --source html を実行して検証してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
