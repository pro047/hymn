### 이번 과제 — (각색: 매 과제마다 여기를 바꾼다)

#### M0 — 교회 격리 선행분 (2026-09-30, 커뮤니티화 기획 `.claude/plan-community.md` 7-2 M0)

배경: `GET /scores` 가 인증·교회 필터 없이 모든 교회 악보를 준다(`backend/src/app/routes/score.py:80-81`).
소비자가 둘이다 — 태블릿 앱(`hymn_app/lib/data/scores_api.dart:12`, 로그인 없음)과 **웹 홈**
(`frontend/src/features/score/hooks/use-scores.js:25`, 토큰 없는 plain `fetch`). 앱은 아직 로그인을
못 하므로 무토큰 차단은 이번 과제가 아니다. 이번에는 **앱을 깨지 않고 웹 홈의 교회 간 노출을 닫는다.**

요구 (번호가 검증 기준이 된다):
1. `GET /scores` 에 `Authorization` 헤더가 **없으면** 응답이 지금과 완전히 같다 — 모든 교회의 행, 정렬·필드 불변.
   기존 `backend/tests/test_score_auth.py` 의 무토큰 테스트가 계속 통과해야 한다
2. 헤더가 있고 유효하면 **그 사용자의 교회(`user.church_id`) 행만** 준다
3. 헤더가 있는데 무효·만료·형식 오류·`token_version` 불일치면 **401** 이다 — `deps.get_current_user` 와
   같은 판정·같은 메시지. **전체 목록으로 폴백하지 않는다** (폴백하면 만료 토큰을 가진 인도자의 홈에
   모든 교회 악보가 조용히 보이고, 웹 `apiFetch` 의 자동 refresh 도 안 돈다)
4. 웹 홈 `use-scores.js` 의 `fetchScores` 가 `apiFetch`(`frontend/src/api/client.ts`)를 쓴다
5. `/auth/me` 가 토큰 클레임의 `church_id` 가 아니라 DB 의 `user.church_id` 로 교회를 찾는다(`routes/auth.py:360` 부근)
6. 업로드 키 검사 `_reject_foreign_object_key`(`routes/score.py:32-49`)를 접두사 비교에서 **세그먼트 파싱**으로
   바꾼다 — `/` 로 나눠 정확히 3조각, 첫째 `scores`, 둘째가 교회 id 와 정확히 같고, 셋째가 비어 있지 않으며,
   어느 조각도 `.`·`..` 가 아니다. `scores/{내교회}/../{남교회}/x.png` 는 400. 검사 시점(쓰기 때만)은 그대로
7. **교회 간 유출 전수 테스트** — 교회 A 가 만든 리소스를 교회 B 토큰으로 데이터 라우트 전부(`routes/score.py`·
   `song.py`·`conti.py`)에 대고 부르면 404(또는 A 의 데이터 0건). 그리고 **앱에 등록된 데이터 라우트 목록과
   테스트가 다루는 목록이 같은지** 대조해, 새 라우트가 테스트 없이 추가되면 실패하게 한다

범위 밖 (이미 결정됨 — BLOCKED 사유로 되돌리지 말 것):
- 무토큰 `GET /scores` 를 401 로 막는 것 (앱 로그인 뒤, 기획서 M4)
- Flutter 앱 변경 · 레이트 리밋 · 스키마·마이그레이션 변경 · 새 엔드포인트
- `weeks`·`set_items` 의 `church_id` 부재 (읽기는 이미 `Score.church_id` 로 걸러진다)

> **낡은 과제 서술을 남겨두면 다음 실행이 그걸 읽는다.** 새 과제를 여기 쓰고,
> 요구는 번호를 매겨 검증 가능한 문장으로 적는다 — 그 번호가 설계의 검증 기준이 된다.
> 범위 밖으로 이미 결정된 것도 함께 적어라 — 안 적으면 설계가 그것을 BLOCKED 사유로
> 되돌려 보내 사람 판단을 한 번 더 태운다.
>
> **★ 과제 서술이 전제하는 API·스키마가 실제로 그 브랜치에 있는지 먼저 확인해라.**
> 2026-09-06 에 그것을 안 맞춰 첫 주행이 BLOCKED 로 끝났다 — 만든 코드를 커밋하지 않은
> 채 worktree 를 갈랐고, 설계는 없는 계약 위에 설계할 수 없다고 정확히 멈췄다.

### 입력 문서

- `$ROOT/.claude/handoff.md` — **이 저장소의 결정 이력·지뢰 정본.**
  **이 파일이 없으면 즉시 `STATUS: BLOCKED`.** 근거 없이 설계하지 않는다.
  최소한 읽을 것: 상단 "지금 상태" 블록 · 1-A절(상시 지뢰) · 9절(미뤄둔 것·별건 버그)
- `$ROOT/.claude/research-*.md` — 있으면 읽는다. 최근 리서치의 측정값이 들어 있다

### 이 저장소의 구조

```
backend/src/app/     FastAPI. models.py · schemas/ · routes/ · services/ · deps.py
backend/alembic/     마이그레이션. 스키마를 바꾸면 여기도 반드시 함께 바뀐다
frontend/src/        React + Vite. features/ · pages/ · api/ · lib/
hymn_app/            Flutter. **리포 루트에 중첩된 별도 git 저장소** (모노리포 아님)
```

### ★ 이 저장소에서 밟으면 되돌릴 수 없는 것 — 설계 전에 반드시 확인

1. **`GET /scores` 는 Flutter 앱이 호출하는 유일한 엔드포인트다**
   (`hymn_app/lib/data/scores_api.dart`). 정렬(`routes/score.py` 의 `created_at.asc()`)도
   응답 스키마도 **앱과의 공유 계약**이다. 앱에는 자체 업데이트 수단이 아직 없어서,
   깨면 교회 태블릿이 그날로 멈추고 복구가 안 된다.
   **이 엔드포인트의 응답 형태를 바꾸는 설계라면 하위호환 경로를 반드시 함께 설계한다.**
2. **`churches` 를 참조하는 `users`·`scores` 가 둘 다 `ondelete="CASCADE"` 다.**
   교회를 지우면 그 안의 계정이 함께 사라진다.
3. **마이그레이션은 새 코드보다 먼저 돈다** (`deploy.yml`). 코드가 참조하는 컬럼은
   그 배포의 마이그레이션에 반드시 포함돼야 한다. 반대로 **컬럼 삭제는 코드가 먼저 나간 뒤**다.
4. **운영에 실제 데이터가 있다** — 교회 1개, 계정 1명, **악보 175행 / 86곡**(2026-09-27 실측).
   스키마를 바꾸면 이 175행을 어떻게 옮길지가 설계의 일부다. 마이그레이션은
   **각 단계마다 rowcount 를 단언**하고, 순서(이동 → 잔여 0 확인 → 삭제)를 안전장치로 쓴다.

### DESIGN.md 에 더 쓸 것

- 공개 인터페이스에 **마이그레이션 revision** 도 포함한다
- **마이그레이션 계획** (스키마를 건드리는 경우) — up/down, 운영 175행 처리, rowcount 단언 지점
- **하위호환** — `GET /scores` 등 앱·웹이 이미 쓰는 계약을 건드리면 여기에 적는다. 안 건드리면 "해당 없음"

### 근거 확인

- **"X가 없다"는 부재 주장은 전수 확인 후에만** — 백엔드·프론트·Flutter 셋을 다 본다
- 운영 현황은 실측할 수 있다: `curl -s https://www.score-hymn.com/api/scores`
  (`GET /scores` 는 아직 무인증 공개다. 읽기 전용이므로 안전)
- **handoff 의 "반증된 것" 목록에 있는 주장을 되살리지 않는다**

### ALLOWED_FILES·TEST_FILES 에서 이 저장소가 빠뜨리기 쉬운 것

- **alembic 마이그레이션 파일을 빠뜨리지 말 것.** 파일명에 revision 해시가 들어가는데
  그건 구현 시점에 정해지므로, `backend/alembic/versions/` 아래 경로를 미리 확정해 적는다
  (예: `backend/alembic/versions/<revision>_split_song_usage.py` 처럼 쓰지 말고,
  revision 을 설계에서 직접 정해 **완전한 파일명**으로 적는다)
- 짝 테스트 파일은 이 저장소 관례대로 `backend/tests/test_foo.py` · `frontend/src/**/foo.test.jsx` 등

### 검증 가능성 — 이 저장소의 예

- **[사람 확인 필요]** 의 전형: 실제 S3·SES, 타이밍, UI 육안 확인, 운영 DB
- 라우트 핸들러 안에 로직을 묻지 말고 순수 함수로 빼면 그만큼 [테스트 가능] 으로 넘어간다

### 게이트에 걸리는 것 — 이 저장소의 파일

- 의존성 추가/제거: `backend/pyproject.toml`·`backend/requirements*.txt`·`frontend/package.json`·`frontend/pnpm-lock.yaml`
- 테스트 러너·린터 설정: `backend/pyproject.toml` 의 `[tool.pytest.ini_options]`·`[tool.ruff]`,
  `frontend/vite.config.js`·`eslint.config.js`·`.prettierrc.json`·`tsconfig*.json`
- `.claude/handoff.md`·`CLAUDE.md` 수정 — **`.claude/handoff.md` 를 수정하지 않는다.** 결정 이력의 정본이고 사람이 관리한다.
