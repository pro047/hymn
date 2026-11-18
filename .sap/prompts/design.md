### 이번 과제 — (각색: 매 과제마다 여기를 바꾼다)

#### 홈 콘티 카드 드래그 정렬 (2026-11-18, CRUD 전수조사 후속)

배경: 홈의 콘티 카드(`frontend/src/features/home/sections/stage-card.jsx`)는 `GET /scores` 가 주는 **업로드 시각 순**
(`backend/src/app/routes/score.py:117` `order_by(Score.created_at.asc())`)으로 곡을 그린다. 콘티 화면의 순서는
`set_items.order_no` 라서 두 순서가 다를 수 있다. 인도자가 홈 카드에서 **드래그로(휴대폰·태블릿 터치 포함)** 곡 순서를
바꾸고, 그 순서가 웹 홈·콘티 화면·태블릿 앱에 똑같이 보이게 한다. 순서 저장 API 는 이미 있다
(`PATCH /weeks/{week_of}/conti/order`, `routes/conti.py:104`, `services/conti.py` `set_week_order`).
드래그 패키지는 develop 에 이미 들어 있다 — `@dnd-kit/core`·`@dnd-kit/sortable`·`@dnd-kit/utilities`(`frontend/package.json`, 커밋 `a58112a`).
**새 패키지를 추가하지 않는다.**

요구 (번호가 검증 기준이 된다):
1. `GET /scores` 의 정렬을 바꾼다: `week_of` 오름차순 → 같은 주차 안에서는 콘티와 **같은 규칙**
   (`services/conti.py` `list_week_entries` 의 `order_by(order_no.asc().nulls_last(), Score.created_at.asc(), Score.id.asc())`,
   `order_no` 는 그 score 의 `min(SetItem.order_no)`). 토큰 유무와 무관하게 같은 규칙이다
2. `GET /scores` 의 응답 키 집합·행 집합(교회 필터·`week_of IS NOT NULL`)은 바뀌지 않는다
   (`tests/test_conti_pdf_route.py:598` `test_get_scores_should_keep_its_exact_key_set_and_ordering` 계속 통과)
3. 같은 주차에서 `GET /scores` 의 순서와 `GET /weeks/{week_of}/conti` 의 순서(페이지를 펼친 순서)가 같다 — 테스트로 고정
4. `PATCH /weeks/{week_of}/conti/order` 의 항목 `starts_new_page` 를 **생략 가능**하게 바꾼다(`schemas/conti.py:53`, 지금은 기본 `False`).
   생략하면 그 곡의 **기존 값을 유지**하고, SetItem 이 새로 만들어지는 곡은 `False`. 명시하면 지금처럼 그 값을 쓴다.
   첫 자리 곡의 표시를 끄는 규칙(`set_week_order` 의 `item.starts_new_page and position > 1`)은 유지
5. 콘티 화면은 계속 `starts_new_page` 를 명시해 보낸다(`frontend/src/lib/conti-order.ts:166` `toOrderPayload`) — 동작 불변
6. 홈 콘티 카드에서 **인도자(`canManage`)만** 곡을 드래그해 순서를 바꿀 수 있다. dnd-kit 의 포인터·터치·키보드 센서를 쓰고,
   터치에서는 스크롤과 구분되도록 활성화 조건(지연 또는 거리)을 둔다. 팀원에게는 드래그 손잡이·이벤트가 없다
7. 놓으면 그 주차 곡 **전체**(카드가 5곡만 그려도 `upcomingSundayScores` 전체, 그린 범위 밖 곡은 기존 상대 순서로 뒤에)를
   `starts_new_page` **없이** 보낸다. 성공하면 점수 목록을 다시 읽어 서버 순서로 그린다. 실패하면 오류를 보여주고 서버 순서로 되돌린다.
   저장 중에는 다음 드래그를 막는다
8. `stage-card.jsx:11-15` 의 "reordering has no API" 주석을 사실에 맞게 고친다(섞기·발행 버튼 부활은 하지 않는다)
9. 기존 테스트 중 **기대값 변경은 `tests/test_score_list_scope.py:252` `test_listing_with_a_token_should_keep_the_created_at_order`
   하나만 허용**한다(사람 승인 2026-11-18). 업로드 시각 순 대신 콘티 순서를 기대하도록 바꾸고 테스트 이름도 맞춘다.
   그 밖의 기존 테스트는 기대값을 바꾸지 않고 통과한다

범위 밖 (이미 결정됨 — BLOCKED 사유로 되돌리지 말 것):
- Flutter 앱 코드 변경 — 앱 홈 탭은 서버 순서를 그대로 쓰고(`hymn_app/lib/screens/home_tab.dart:15-24`), 우리 교회 태블릿은 구버전 앱 고정이다
- 콘티 화면의 기존 드래그·위아래 버튼을 dnd-kit 으로 옮기는 것
- 홈 카드의 5곡 제한 해제 · 섞기/발행 버튼 · 스키마·마이그레이션 · 새 엔드포인트 · 새 패키지
- 보관함 곡 수정 UI(별도 과제)

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
