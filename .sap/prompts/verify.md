### 허용된 명령

허용된 명령은 **정확히 이 형태**다 (다른 형태는 헤드리스에서 거부된다):

```bash
# 백엔드 — hymn-db-1 컨테이너가 떠 있어야 한다
cd backend && .venv/bin/python -m pytest -q
cd backend && .venv/bin/ruff check src tests alembic

# 프론트 (jsdom + vitest)
cd frontend && pnpm test
cd frontend && pnpm lint
cd frontend && pnpm format:check
cd frontend && pnpm typecheck
```

- **★ 네 테스트 파일은 ruff(import 정렬 포함)·eslint·prettier 를 통과해야 한다.** 셸의 검증 목록에
  린트·포맷 검사가 들어 있고, 구현은 테스트 파일을 한 글자도 못 고친다 — 형식이 어긋난 테스트 하나면
  green 에 영영 못 가고 재시도만 소진한다. 제출 전에 위 검사 명령으로 **네 파일**이 깨끗한지 확인하라.
  형식 실패는 "잘못된 실패"다 (할 일 4).

### 테스트 위치·픽스처

- 백엔드 테스트는 `backend/tests/test_*.py` 에 있고 `conftest.py` 가 `APP_ENV=test`·
  `EMAIL_SENDER=console`·`PASSWORD_RESET_ENABLED=true` 를 **앱 import 전에** 세운다.
  안 세우면 전 스위트가 import 에서 죽는다 — 새 conftest 를 만들지 말고 기존 것을 쓴다.
  같은 conftest 가 S3 존재 확인(`get_object_probe`)을 "있음" 으로 덮는다 — 실 S3 를 부르지 않는다.
- 프론트 테스트는 소스 옆 `*.test.{ts,tsx,js,jsx}` 다 (vitest + jsdom).
  **jsdom 이 판정할 수 없는 부류가 있다**(레이아웃·캔버스 픽셀) — 그건 사람 체크리스트로 넘긴다.

### 이 저장소에서 꼭 덮을 것

- **스키마를 바꿨다면 마이그레이션 자체를 테스트한다.** 모델이 맞는 것과 마이그레이션이
  도는 것은 다른 문제다. up → down → up 왕복, 그리고 **기존 데이터가 있는 상태에서의 up**
  (운영에는 175행이 있다, 2026-09-27)을 확인한다. 기존 `test_migration_*.py` 가 틀이다.
- **`GET /scores` 의 정렬·응답 필드를 고정하는 테스트가 이미 있는지 확인하고,
  없으면 만든다.** 웹 홈과 Flutter 앱의 공유 계약인데 지키는 테스트가 없으면
  다음 사람이 조용히 깬다.
