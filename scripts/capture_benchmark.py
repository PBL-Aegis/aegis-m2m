"""
세 출처(Epoch·OpenRouter·AA)를 떠서 판매 목록과 시작값을 새로 만든다. 수집·짝짓기 로직은
agent_m2m/benchmark_sources.py 에 있고, 앱도 구매 때 같은 로직으로 숫자를 갱신한다.

  uv run python scripts/capture_benchmark.py          data/catalog.json · data/benchmark.json · data/sellers.json 갱신
  uv run python scripts/capture_benchmark.py --list   저장하지 않고 짝지어진 모델과 뺀 모델만 보여 줌

판매 목록이 바뀌는 곳은 여기뿐이다. 결과를 확인하고 커밋한다.
판매자 주소는 회사별로 하나다. 처음 보는 회사에는 anvil 공개 테스트 계정(2번부터)을 차례로 붙이고,
한 번 붙인 주소는 data/sellers.json 에 남겨 다시 바꾸지 않는다.
AA 키는 .env.local 의 AA_API_KEY 에서만 읽고, 저장 파일에는 넣지 않는다.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_m2m.benchmark_sources import build_catalog, build_snapshot, fetch_aa, fetch_epoch, fetch_openrouter  # noqa: E402
from agent_m2m.payment import anvil_account  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SELLERS_FILE = DATA / "sellers.json"
# 0번은 운영자, 1번은 구매자라 판매자는 2번부터 쓴다.
FIRST_SELLER_INDEX = 2


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    key = (os.environ.get("AA_API_KEY") or "").strip()
    if key == "":
        sys.exit(".env.local 에 AA_API_KEY 가 없습니다")

    epoch_rows, openrouter_models, aa_models = fetch_epoch(), fetch_openrouter(), fetch_aa(key)

    sellers = json.loads(SELLERS_FILE.read_text()) if SELLERS_FILE.exists() else {"note": "", "sellers": {}}
    used = [item["index"] for item in sellers["sellers"].values()]
    next_index = max([FIRST_SELLER_INDEX - 1, *used]) + 1

    def recipient_of(provider_id: str) -> str:
        nonlocal next_index
        if provider_id not in sellers["sellers"]:
            sellers["sellers"][provider_id] = {"index": next_index, "address": anvil_account(next_index).address}
            next_index += 1
        return sellers["sellers"][provider_id]["address"]

    catalog = build_catalog(epoch_rows, openrouter_models, aa_models, recipient_of)
    snapshot = build_snapshot(catalog, epoch_rows, openrouter_models, aa_models)

    print(f"짝지어진 모델 {len(catalog['entries'])}개 · 뺀 모델 {len(catalog['excluded'])}개 (Epoch {len(epoch_rows)}개 중)")
    for model in snapshot["models"]:
        print(
            f"  {model['key']}: ECI {model['eci']} ({model['eciCiLow']}~{model['eciCiHigh']}) · "
            f"${model['inputPricePerMillion']}/{model['outputPricePerMillion']} · "
            f"{model['outputTokensPerSecond']} 토큰/초 [{', '.join(model['aaModelNames'])}]"
        )

    if "--list" in sys.argv:
        print("\n뺀 모델")
        for item in catalog["excluded"]:
            print(f"  {item['name']}: {item['reason']}")
        return

    sellers["note"] = "회사별 판매자 주소. anvil 공개 테스트 계정(index)이라 실제 자산이 없다. capture 스크립트가 처음 보는 회사에만 새로 붙인다."
    write_json(SELLERS_FILE, sellers)
    write_json(DATA / "catalog.json", catalog)
    write_json(DATA / "benchmark.json", snapshot)
    print("\n저장 완료: data/catalog.json · data/benchmark.json · data/sellers.json")


if __name__ == "__main__":
    main()
