"""agent-M2M 서버. 모델 선택·결제·감사·기록을 담당하고, 화면(web/)은 이 서버의 API 만 부른다."""

from agent_m2m import config as _config  # noqa: F401  .env.local 을 가장 먼저 읽는다.
