### 이번 과제 — (각색: 매 과제마다 여기를 바꾼다)

#### 보관함 곡 수정 화면 M2 — 웹 (2026-11-18, M1 후속)

배경: 보관함 곡을 고치는 API 는 develop 에 있다(M1, `3183995`) — `POST /songs/{song_id}/file`(업로드 URL 발급, 열 안 바꿈),
`PATCH /songs/{song_id}` 본문 `{title?, file_uri?}`, 응답은 `GET /songs` 항목과 같은 모양(`SongLibraryItem`), 같은 교회 같은
제목이면 409 `같은 제목의 곡이 이미 있습니다.`. 그런데 이를 부르는 웹 화면이 없다. 또 week-copy(`faabe09`) 뒤로 주차 화면의
수정은 그 주차만 바꾸므로, **곡 자체를 고치는 웹 경로는 이 과제가 유일하다.** 보관함에서 고친 값은 이후 새로 배치하는 주차부터
복사되고, 이미 배치된 주차는 바뀌지 않는다(서버 동작, 이번에 바꾸지 않는다).

요구 (번호가 검증 기준이 된다):
1. 보관함 카드(`frontend/src/features/score/components/saved-scores-card.jsx`)의 곡마다 **"수정" 버튼**을 둔다.
   **타일 버튼(`:50-53`, 누르면 배치 다이얼로그) 바깥**에 두어 버튼 안에 버튼이 없고, 수정을 눌러도 배치 다이얼로그(`onApplyRequest`)가 열리지 않는다
2. 수정 버튼은 **기존 `ScoreEditDialog`(`score-edit-dialog.jsx`)를 그대로 재사용**해 연다(사람 결정). 다이얼로그 파일은 고치지 않는 것이 기본이며,
   곡을 `{ id: song_id, title, download_url, file_url }` 모양으로 넘기고 `onSubmit` 만 곡 수정 함수로 바꿔 끼운다.
   다이얼로그 수정이 불가피하면 주차 화면 동작이 그대로라는 기존 테스트(`score-edit-dialog.test.jsx`)가 기대값 변경 없이 통과해야 한다
3. `useScores`(`features/score/hooks/use-scores.js`)에 곡 수정 함수(예: `updateSong`)를 둔다. 순서는 기존 `updateScore`(`:127-196`)와 같은 3단계:
   파일이 있으면 `POST /songs/{id}/file` → 받은 `upload_url` 로 S3 PUT → `PATCH /songs/{id}` `{file_uri: s3_key}`(제목이 바뀌었으면 함께).
   제목만이면 PATCH `{title}` 하나. 업로드가 실패하면 PATCH 를 보내지 않는다
4. 성공하면 보관함 목록(`librarySongs`)에 바뀐 제목·이미지가 보인다(다시 읽거나 PATCH 응답으로 그 항목을 바꾼다). 주차 목록(`GET /scores`)은 다시 읽지 않아도 된다
5. 409 등 실패 응답은 서버 `detail` 문구를 그대로 보인다(기존 `readApiError` 사용, `updateScore` 와 같은 방식)
6. `API_PATHS`(`frontend/src/api/paths.ts`)에 곡 하나·곡 파일 경로를 추가한다
7. 홈(`pages/home-page.jsx`)에서 연결한다 — 보관함 탭은 이미 인도자(`canManage`)에게만 보인다. 팀원에게 수정 버튼·요청이 생기지 않는다
8. 기존 테스트는 기대값을 바꾸지 않고 전부 통과한다

범위 밖 (이미 결정됨 — BLOCKED 사유로 되돌리지 말 것):
- 백엔드·스키마 변경 일체(M1 API 그대로) · 곡 삭제 · 이미 배치된 주차에 반영하는 옵션
- 다이얼로그에 "이후 배치부터 적용" 같은 안내 문구(사람이 주차 쪽 문구도 넣지 않기로 했다)
- 화면 낭독기 UUID 낭독 수정 · Flutter 앱 · 새 패키지

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
