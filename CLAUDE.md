
# 파이프라인 런처 프로토콜 (serial-agent-pipeline)

이 리포에는 셸 오케스트레이터(`orchestrate.sh`)가 있다. 세션(LLM)은 **런처**다 — 실행·전달만 하고 판정하지 않는다.

- 실행: worktree 에서 `./orchestrate.sh <feature>` 를 백그라운드로. 진행 중에는 `.pipeline/<feature>/STATE.md` 만 읽는다 (`*.stream.jsonl` tail 금지 — 컨텍스트 오염)
- 멈추면 STATE.md 의 `## 다음 행동` 블록을 그대로 따른다. exit 4 = 사람 승인 대기(실패 아님), 2 = 게이트 위반, 3 = BLOCKED
- 게이트 승인은 사람만 한다 — 방법은 STATE.md 안내를 따른다. 세션이 approve.sh 를 대신 실행하거나 `.approved` 파일을 쓰는 것은 금지
- 사람에게 터미널을 더 열라고 안내하지 마라 — advisor.sh 는 선택지일 뿐, 상담은 이 세션이 STATE.md·산출물 읽기로 대신한다
