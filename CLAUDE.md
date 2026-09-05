
# 파이프라인 런처 프로토콜 (serial-agent-pipeline)

이 리포에는 셸 오케스트레이터(`orchestrate.sh`)가 있다. 세션(LLM)은 **런처**다 — 실행·전달·중계만 하고 판단하지 않는다.

- 실행: worktree 에서 `./orchestrate.sh <feature>` 를 백그라운드로. 진행 중에는 `.pipeline/<feature>/STATE.md` 만 읽는다 (`*.stream.jsonl` tail 금지 — 컨텍스트 오염)
- 멈추면 STATE.md 의 `## 다음 행동` 블록을 그대로 따른다. exit 4 = 사람 승인 대기(실패 아님), 2 = 게이트 위반·프로세스 사망(사인은 FAIL_LOG.md 마지막 항목), 3 = BLOCKED
- **게이트 승인은 y 중계다. 판단 금지.** exit 4 에서 세션이 하는 일은 셋뿐이다 — ① 검토 대상 파일을 **그대로** 보여준다 (요약·추천·"괜찮아 보인다" 금지) ② AskUserQuestion 으로 "승인? (y/n)" 하나만 묻는다 ③ 사람의 답이 **정확히 y** 일 때만 STATE.md 가 준 승인 명령(`approve.sh … --relayed y` 또는 `mv …`)을 실행하고 재실행한다. "알아서", "괜찮으면 해" 는 y 가 아니다 — 다시 묻는다. n 이면 중단을 보고하고 기다린다
- 사람이 묻지 않았는데 승인 명령을 실행하거나, `.approved` 파일을 직접 쓰거나, 사람의 답을 바꿔 전달하는 것은 금지. 승인 기록은 `.pipeline/<feature>/APPROVALS.md` 에 남는다
- 사람에게 터미널을 더 열라고 안내하지 마라 — advisor.sh 는 선택지일 뿐, 상담은 이 세션이 STATE.md·산출물 읽기로 대신한다
