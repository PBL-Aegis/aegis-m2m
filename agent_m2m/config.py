"""
설정. 저장소 맨 위의 .env.local 을 환경변수로 읽는다(이미 있는 환경변수는 덮어쓰지 않는다).

값은 각 모듈이 쓸 때마다 os.environ 에서 읽는다. 테스트가 환경변수를 바꿔 가며 시험할 수 있게 하기 위해서다.
"""

from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env.local", override=False)
