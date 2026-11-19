### 이번 과제 — (각색: 매 과제마다 여기를 바꾼다)

#### 보관함 곡 삭제 — 하드 딜리트, 배치된 주차는 남긴다 (2026-11-18, 사람 결정)

배경: 곡 삭제 API 가 없다(2026-08 에 휴지통을 뺐다 — "곡 삭제 = FK CASCADE 로 모든 주차에서 사라짐", `.claude/handoff.md:1919`).
지금 `scores.song_id` 는 `nullable=False`·`ondelete="CASCADE"`(`backend/src/app/models.py:179`, 제약 이름 `fk_scores_song_id_songs`,
`alembic/versions/d2a7e5f1c3b9_split_songs_from_scores.py:79`)이고 ORM 도 `Song.usages` 가 `cascade="all, delete-orphan"`(`models.py:170`)이라
곡을 지우면 그 곡의 모든 주차 행이 사라진다. 그런데 week-copy(`faabe09`) 뒤로 화면·앱·PDF 는 주차 행의 복사본(`scores.title`·`file_uri`)을
읽으므로 주차 행은 곡 행 없이도 보일 수 있다. **사람 결정(2026-11-18): 하드 딜리트. 보관함에서 곡 행을 지우고, 이미 배치된 주차 행은
`song_id` 만 비운 채 그대로 남긴다. 소프트 딜리트·되살리기는 하지 않는다.**

요구 (번호가 검증 기준이 된다):
1. 마이그레이션 1개(현재 head `0ffde4301ddb` 다음): `scores.song_id` 를 nullable 로, FK `fk_scores_song_id_songs` 를 `ondelete="SET NULL"` 로
   바꾼다. 데이터는 바꾸지 않는다. downgrade 는 `song_id IS NULL` 행이 하나라도 있으면 **지우지 않고 예외로 멈춘다**(데이터 손실 금지),
   없으면 NOT NULL·CASCADE 로 되돌린다. 마이그레이션 테스트로 둘 다 고정
2. ORM: `Score.song_id` 는 Optional, `Song.usages` 는 곡 삭제가 주차 행을 지우지 않도록(`delete-orphan` 제거, DB 의 SET NULL 에 맡김 —
   `passive_deletes=True` 등) 바꾼다. **ORM 경로로 지워도 주차 행이 남는다**를 테스트로 고정
3. `DELETE /songs/{song_id}` 추가 — 204. `require_leader`(무토큰 401·팀원 403), 다른 교회 곡 404(`_church_song_or_404`, `routes/song.py:38`)
4. 삭제 뒤: `GET /songs` 에서 빠진다. 그 곡을 배치했던 주차의 `GET /scores`·`GET /scores/{id}`·콘티·PDF 는 **삭제 전과 같은 제목·파일·편집본**을
   준다(`song_id` 만 null). 그 주차의 PATCH·편집 저장·편집 지우기·순서 변경·주차 이동도 200 으로 동작한다
5. **S3 객체를 지우지 않는다.** 곡과 그 곡을 배치한 주차 복사본은 같은 S3 키를 가리킨다(`add_usage` 가 키를 복사). 앱 코드에 S3 삭제 호출이
   지금 0건이며 이번에도 0건이어야 한다 — 삭제 라우트가 S3 클라이언트를 부르지 않음을 테스트로 고정
6. 삭제 뒤 같은 교회에 같은 제목으로 `POST /songs` 하면 201(새 곡)이다. 지운 곡 id 로 `POST /songs/{id}/usages`·`PATCH /songs/{id}`·`POST /songs/{id}/file` 은 404
7. 새 라우트를 `tests/test_leader_only.py` `LEADER_ONLY` 와 `tests/test_church_isolation.py` 격리 케이스에 등록한다(메타 테스트)
8. 웹: 보관함 카드의 케밥 메뉴(`frontend/src/features/score/components/saved-scores-card.jsx`)에 **"삭제"** 항목을 수정 아래에 둔다.
   누르면 `window.confirm("「<제목>」을 보관함에서 삭제할까요? 이미 배치된 주차에는 그대로 남습니다.")` — 취소면 요청 없음. 확인이면
   `DELETE /songs/{id}` 후 보관함 목록에서 사라진다. 실패는 서버 `detail` 을 보인다(기존 `readApiError`). `API_PATHS` 의 곡 경로를 재사용.
   `saved-scores-card.jsx:6-7` 의 "nothing to take out" 주석을 사실에 맞게 고친다
9. 기존 테스트는 기대값을 바꾸지 않고 통과한다. 깨지는 기존 테스트가 있으면 구현으로 맞추지 말고 **[결정]으로 사람에게 올린다**

범위 밖 (이미 결정됨 — BLOCKED 사유로 되돌리지 말 것):
- 소프트 딜리트·되살리기·휴지통 · S3 객체 정리 · 주차 행 삭제 방식 변경
- Flutter 앱(앱은 `song_id` 를 읽지 않는다) · 화면 낭독기 UUID 낭독 · 새 패키지

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
