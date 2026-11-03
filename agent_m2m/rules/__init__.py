"""
서버 감사 규칙 등록부. 규칙 파일을 이 폴더에 하나씩 두고 여기서 불러온다.

규칙 파일은 불러올 때 audit.py 의 ON_REQUEST_CHECKS · BEFORE_PAYMENT_CHECKS · AFTER_PAYMENT_CHECKS 중
맞는 곳에 자기 함수를 append 한다. 불러온 순서가 곧 도는 순서다.
purchase.py 가 이 패키지를 한 번 불러오므로, 새 규칙은 아래에 import 한 줄만 더하면 된다.
예: from agent_m2m.rules import limit  # noqa: F401
"""
