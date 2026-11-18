### 이번 과제 — (각색: 매 과제마다 여기를 바꾼다)

#### 주차별 수정 — 주차는 보관함 곡의 복사본을 쓴다 (2026-11-18, 사람 결정)

배경: 화면·앱·PDF 가 곡 행(`songs.title`·`songs.file_uri`)을 읽어서, 한 곡을 배치한 **모든 주차가 같은 값을 공유**한다.
주차 화면에서 고치면(`PATCH /scores/{id}`) 곡 행이 바뀌어 지나간 주차까지 바뀌고(`routes/score.py:337`·`:350`),
보관함에서 고쳐도(`PATCH /songs/{id}`) 모든 주차가 바뀐다. **사람 결정(2026-11-18): 보관함이 정본이고, 주차는 배치하는
순간 그 값을 복사해 쓴다. 이후 보관함을 고쳐도 이미 배치된 주차는 바뀌지 않는다. 주차 화면에서 고치면 그 주차만 바뀐다.**
복사는 이미 일어나고 있다 — `add_usage`(`services/song.py:126-133`)가 배치 때 `scores.title`·`file_url`·`file_uri` 에 곡 값을 쓴다.
**읽는 곳을 이 복사본으로 옮기는 것이 이번 과제의 본체다. 스키마·마이그레이션 변경 없음.**

운영 실측(2026-11-18, `.claude/ops/measure-snapshot-drift-out.txt`): 배치 210행 중 복사본 ≠ 곡 — 제목 2행(끝 공백만),
파일 내용(size:ETag) 7행(전부 2026-02~03 지난 주차), 복사본 키가 S3 에 없는 행 0. **이 7행은 전환 뒤 당시 올린 파일로 보이는 것을
사람이 승인했다(데이터를 맞추지 않는다).**

요구 (번호가 검증 기준이 된다):
1. `GET /scores`·`GET /scores/{id}` 의 `title`·`file_url`·`file_uri` 는 **그 행의 복사본**(`Score.title`·`Score.file_url`·`Score.file_uri`)이다.
   `download_url` 은 `edited_file_uri` 가 있으면 그것, 없으면 `Score.file_uri` 를 서명한다(지금 `score.py:120-126`·`:157-160` 은 곡 값)
2. 콘티(`GET /weeks/{week_of}/conti`)와 PDF 는 제목 `Score.title`, 파일 `coalesce(Score.edited_file_uri, Score.file_uri)` 를 쓴다(`services/conti.py:159`·`:163`)
3. `PATCH /scores/{id}` 는 **그 행만** 바꾼다
   - `title`: `Score.title` 만 바꾼다(앞뒤 공백 제거). `rename_song` 을 부르지 않고, **곡 제목 중복 409 는 더 이상 없다**. 길이 검증은 그대로
   - `file_uri`: 기존 키 검사(`_reject_foreign_object_key`) 후 `Score.file_uri`·`Score.file_url`(`object_url`) 만 바꾸고, 그 행의 편집본을 지운다(`clear_edit`, 지금과 같음). `replace_song_file` 을 부르지 않는다
   - `week_of`: 지금과 같다
   - 응답은 요구 1 과 같은 규칙(복사본 + 편집본 우선)
   - **곡 행(`songs`)은 이 라우트로 절대 바뀌지 않는다** — 테스트로 고정
4. 편집기: `GET /scores/{id}/edit` 의 바탕 이미지는 `edit_source_uri` 가 있으면 그것, 없으면 **`Score.file_uri`**(지금 `score.py:214` 는 곡 파일).
   `PUT /scores/{id}/edit` 이 기록하는 `edit_source_uri` 도 **`Score.file_uri`**(지금 `score.py:290` 은 곡 파일)
5. 보관함(`GET /songs`·`PATCH /songs/{id}`·`POST /songs/{id}/file`)은 곡 행만 읽고 쓴다 — 동작 불변. 보관함에서 고친 뒤
   **이미 배치된 주차의 `GET /scores`·콘티·PDF 가 바뀌지 않고**, 그 뒤 새로 배치한 주차는 고친 값을 복사한다 — 테스트로 고정
6. 보관함 업로드의 "파일이 도착하지 않은 곡 치유" 경로(`routes/song.py:144-145`)는 곡 파일을 바꿀 때, 그 곡의 사용 행 중
   **복사본 키가 치유 전 곡 키와 같은 행**의 `file_uri`·`file_url` 도 새 키로 바꾼다(그 행들은 존재하지 않는 파일을 복사해 갔다).
   `tests/test_song_library.py:250` `test_a_healed_song_should_show_its_new_file_on_the_sundays_it_was_placed_on` 이 기대값 변경 없이 통과
7. 기존 테스트 기대값 변경은 **아래 5개만 허용**(사람 승인 2026-11-18) — 모두 "고치면 모든 주차가 바뀐다"를 고정한 테스트다.
   새 의미(복사본)에 맞게 기대값과 이름을 바꾼다. 그 밖에 깨지는 기존 테스트가 있으면 구현으로 맞추지 말고 **[결정]으로 사람에게 올린다**
   - `tests/test_song_split.py:154` `test_replacing_the_file_should_show_on_every_week`
   - `tests/test_song_split.py:183` `test_renaming_should_change_the_title_of_every_week`
   - `tests/test_song_split.py:401` `test_the_library_should_follow_the_song_after_a_rename_or_file_swap`
   - `tests/test_song_edit.py:337` `test_a_rename_should_show_on_every_sunday_without_rewriting_usages_AC_6`
   - `tests/test_song_edit.py:419` `test_replacing_the_file_should_show_it_on_every_unedited_sunday_AC_8`

범위 밖 (이미 결정됨 — BLOCKED 사유로 되돌리지 말 것):
- 스키마·마이그레이션·운영 데이터 수정(7행을 맞추지 않는다 — 사람 결정) · `songs.title`/`scores.title` 정규화
- 보관함 곡 수정 웹 화면(M2, 별도 과제) · 지나간 주차 잠금 · 곡 삭제 · Flutter 앱 코드
- 화면 낭독기 안내 문구(UUID 낭독) 수정
- 웹 프론트 변경 전부 — 수정 다이얼로그 문구·409 분기 포함(사람 결정 2026-11-18: 넣지 않는다)

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
