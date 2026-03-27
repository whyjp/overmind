# Overmind — 다음 세션 브리핑

**마지막 업데이트**: 2026-03-27
**현재 브랜치**: main (origin보다 40+ commits ahead, push 필요)

---

## 이번 세션 완료 사항

### 1. P1-3: PostToolUse Push + SessionEnd 경량화
- PostToolUse hook 신규: Write/Edit 완료 후 변경 파일을 state에 누적, 개수(5)/시간(30분)/스코프 전환 시 batch push
- SessionEnd: 잔여 pending flush만 (generic "session ended" 제거)
- 공통 로직: `file_to_scope`, `should_flush`, `build_change_events`, `flush_pending_changes`를 api_client.py에 추출
- 빈 stdin graceful 처리, 첫 accumulation 시 즉시 flush 방지 (배칭 정상화)

### 2. 테스트 보강 (33 → 112)
- Plugin 59개: api_client, flush_logic, formatter, hooks subprocess
- Server 53개: concurrent push stress, E2E subprocess, multi-agent hook simulation
- e2e_live 마커: Claude CLI 실제 테스트 (수동 실행)

### 3. Multi-Agent Integration Test
- Hive scaffold: 20파일 TypeScript 프로젝트 생성기
- Hook 시뮬레이션 (C): 결정적 cross-agent 테스트 — flush, PreToolUse 경고, polymorphism
- Claude CLI live (A): `run_live_agents.py basic|full|stress` 3가지 시나리오
- 4개 agent 역할: auth_lead, task_dev, cache_infra, security_audit

### 4. 대시보드 개선
- SSE 실시간 업데이트: `/api/stream` 엔드포인트, EventSource 기반 LIVE 모드
- 새 repo 자동 감지 및 dropdown 추가 (SSE global version)
- Flow View: Sequence 모드 (균등 간격), HEAD 라벨 (push 좌측/pull 우측 + agent 이름)
- pull_log JSONL 영구 저장 (서버 재시작 후에도 유지)
- Timeline 탭 제거 (Flow View가 대체)

### 5. 코드 리뷰 전체 수정
- 8건 모두 해결: monkeypatch, SSE disconnect, 헬퍼 중복 추출, 포트 문서화 등

---

## 전체 진행 상태

### Phase 1: ✅ 완료
- [x] Server (FastAPI + FastMCP + JSONL store)
- [x] Plugin (4 hooks: SessionStart, PreToolUse, PostToolUse, SessionEnd)
- [x] Dashboard (Overview + Flow View + SSE live)
- [x] 2인 환경 검증, Plugin 설치 테스트
- [x] 테스트 112개 (plugin 59 + server 53)
- [x] Multi-agent integration test (hook sim + Claude CLI)

### Phase 2-A: 서버 데이터 품질 개선 (미시작)
- [ ] `?detail=lesson|diff|full` pull 파라미터
- [ ] 서버 측 서머리 생성 (mocking API → lesson 압축)
- [ ] SQLite store 이관 (JSONL → SQLite)
- [ ] 피드백 점수 (relevance_score, prevented_error) 축적
- [ ] lesson 필드 활용: `build_change_events`에서 lesson→type 매핑 (`api_client.py`에 TODO 있음)

### Phase 2-B: 클라이언트 레슨 반영 (미시작)
- [ ] `.claude/overmind-context.md` 동기화 (TTL 기반)
- [ ] pull 측 충돌 감지 (deny/ask/systemMessage 판단)
- [ ] MCP resource: `overmind://memory/{repo_id}`
- [ ] 구조화된 레슨 포맷 `{action, target, reason}`
- [ ] 영향 측정: cross-agent 이벤트가 실제로 agent 행동을 바꿨는지 검증 방법

### 설계 인사이트 (Phase 2 스펙 반영 대기)
- Pull 응답 최적화: delta-only pull
- urgent → high_priority 네이밍 재검토
- 서머리 생성: 구조적 추출 우선, LLM은 압축 시에만

---

## 즉시 해야 할 것

### 1. git push
```bash
cd D:\github\overmind && git push origin main
```
40+ 커밋이 로컬에만 있음.

### 2. CLAUDE.md 업데이트
이번 세션의 변경사항 반영 필요:
- 테스트 수: 110 → 112
- Dashboard: SSE, Flow View Sequence mode, HEAD labels, Timeline 제거
- pull_log 영구 저장
- Multi-agent test infrastructure 추가
- Key Files 테이블 업데이트

### 3. 수동 검증 (run_live_agents.py)
```bash
# 서버 시작
cd server && python -m overmind.main

# 대시보드 열고 LIVE 켜기
# http://localhost:7777/dashboard

# 다른 터미널에서 full 시나리오 실행
python server/tests/scenarios/run_live_agents.py full
```
- SSE가 실시간으로 이벤트를 전달하는지 확인
- Flow View Sequence 모드에서 노드가 균등 배치되는지 확인
- HEAD 라벨이 올바르게 표시되는지 확인

---

## 다음 세션 추천 작업 (우선순위순)

### 높음
1. **Phase 2-A: `?detail` 파라미터** — pull API에 lesson/diff/full 레벨 도입. 가장 빠르게 데이터 품질에 영향.
2. **Phase 2-B: overmind-context.md** — 훅이 관리하는 로컬 컨텍스트 파일. agent가 Overmind 없이도 팀 컨텍스트를 가짐.

### 중간
3. **Phase 2-A: SQLite 이관** — JSONL의 한계(파일 잠금, 동시성, 쿼리). 데이터 규모 증가 전에 해야 함.
4. **영향 측정 메커니즘** — cross-agent 이벤트가 agent 행동을 바꿨는지 검증. acknowledge 기반 프롬프트 접근법 논의됨.

### 낮음
5. **test_multi_agent_sim / test_live_agents에도 shared helpers 적용** — test_hooks_e2e는 리팩토링 완료, 나머지 2개는 아직 로컬 정의 사용
6. **urgent → high_priority 네이밍** — 동작은 pull 시 상단 정렬뿐이므로 영향 적음

---

## 핵심 파일 변경 맵 (이번 세션)

| 영역 | 파일 | 변경 |
|------|------|------|
| Hook | `plugin/hooks/on_post_tool_use.py` | 신규 — 변경 누적 + batch push |
| Hook | `plugin/hooks/on_session_end.py` | 재작성 — flush only |
| Hook | `plugin/hooks/hooks.json` | PostToolUse 등록 |
| Shared | `plugin/scripts/api_client.py` | +file_to_scope, should_flush, build_change_events, flush_pending_changes |
| Server | `server/overmind/store.py` | +version counter, global_version, pull_log persist |
| Server | `server/overmind/api.py` | +SSE /api/stream 엔드포인트 |
| Dashboard | `server/overmind/dashboard/static/app.js` | SSE, Sequence mode, HEAD labels, Timeline 제거 |
| Test | `server/tests/fixtures/server_helpers.py` | 공통 ServerThread, run_hook, api helpers |
| Test | `server/tests/fixtures/scaffold_hive.py` | Hive 프로젝트 scaffold 생성기 |
| Test | `server/tests/scenarios/test_multi_agent_sim.py` | Hook 시뮬레이션 cross-agent 테스트 |
| Test | `server/tests/scenarios/run_live_agents.py` | 3 시나리오 live agent runner |
