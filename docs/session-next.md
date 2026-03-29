# Overmind — 다음 세션 브리핑

**마지막 업데이트**: 2026-03-29 (v3)
**현재 브랜치**: main

---

## 전체 진행 상태

### Phase 1: ✅ 완료
- [x] Server (FastAPI + FastMCP + SQLite store)
- [x] Plugin (4 hooks: SessionStart, PreToolUse, PostToolUse, SessionEnd)
- [x] Dashboard (Overview + Flow View + SSE live)
- [x] 2인 환경 검증, Plugin 설치 테스트
- [x] Multi-agent integration test (hook sim + Claude CLI)

### Phase 2-A: ✅ 서버 데이터 품질 개선 (완료)
- [x] `?detail=summary|full` pull 파라미터
- [x] 서버 측 서머리 생성 (SummaryGenerator Protocol + MockSummaryGenerator)
- [x] SQLite store 이관
- [x] 피드백 점수 (prevented_error, helpful/irrelevant) 축적
- [x] Push "why" 보강 (diff_collector + PostToolUse context capture)

### Phase 2-B: ✅ 클라이언트 레슨 반영 (완료)
- [x] `.claude/overmind-context.md` 동기화 (TTL 기반)
- [x] 구조화된 레슨 포맷 — `StructuredLesson {action, target, reason, replacement}`
- [x] pull 측 충돌 감지 — `conflict_detector.py` (deny/warn/ignore + legacy scope-aware fallback)
- [x] `overmind_memory` MCP tool — 팀 메모리 마크다운 조회 (scope 필터 지원)

### Phase 3: ✅ Branch-Aware Selective Intelligence (완료)
- [x] Branch metadata: `current_branch`/`base_branch` 자동 감지 + DB 저장
- [x] 이벤트 타입: `intent` 추가 (forward-looking 선언)
- [x] Pull relevance 3-tier: same branch > same base > different base
- [x] 선택적 수용: formatter PLANNED CHANGES + branch tag
- [x] Lesson 자동분류: action → event type 매핑

### Statistical AB Test Framework: ✅ 완료
- [x] ab_scaffolds/ — active: nightmare, branch_conflict (deprecated: simple, multistage, complex)
- [x] ab_runner.py — 공통 agent runner + JSONL 분석 + 통계 리포트
- [x] pytest 옵션: --student-n, --naive-m, --agent-model
- [x] test_live_agents_AB_statistical.py — parametrize × scaffold, N/M 병렬 반복
- [x] 저가치 scaffold deprecation (simple/multistage/complex → 레지스트리에서 제거, 파일 보존)

### 테스트 정리: ✅ 완료
- [x] 레거시 단일실행 AB 테스트 3개 삭제 (AB.py, _multistage.py, _complex.py)
- [x] 저가치 scaffold 3개 deprecated (Overmind 효과 측정 불가)
- [x] AB scaffold 설계 기준 4가지 CLAUDE.md에 명문화
- [x] UTF-8 인코딩 가이드 추가

---

## 테스트 현황

| 영역 | 수 | 내역 |
|------|-----|------|
| Server | 119 | models 12, store 30, api 14, mcp 6, scenarios 28, summary 2, nightmare 18, branch_conflict 11 |
| Plugin | 122 | api_client 32, flush 22, formatter 15, context_writer 10, diff_collector 6, conflict_detector 19, hooks 11 |
| E2E Live | 2 시나리오 | nightmare + branch_conflict (`claude` CLI 필요) |
| **합계** | **241** | 6 deselected (e2e_live/multi_agent 마커) |

**경고 사항**:
- websockets deprecation (server) — uvicorn 업그레이드 시 해결
- cp949 UnicodeDecodeError (plugin) — Windows에서 한글 subprocess 출력 디코딩 실패. `encoding="utf-8"` 명시 필요

---

## Statistical AB 벤치마크 결과 (2026-03-29)

### Model-Tier 벤치마크 (최적 방법론)

Pioneer=sonnet(상위모델) + SHARED_PROMPT → Student/Naive=haiku(하위모델). 프롬프트 조작 없이 모델 차이만으로 Overmind 가치 증명.

| Scaffold | Pioneer | Student vs Naive (시도) | Student vs Naive (성공) |
|----------|:---:|:---:|:---:|
| **nightmare** | sonnet, 2회 성공 | **-41% 서버 실행** | **100% vs 50%** |
| **branch_conflict** | sonnet, 1회 성공 | **-30% 서버 실행** | 100% vs 100% |

### PIONEER_PROMPT 방식 (레거시)

| Scaffold | 트랩 | Pioneer 프롬프트 | Student vs Naive |
|----------|------|:---:|---|
| ~~simple (N=2,M=2)~~ | ~~3~~ | ~~SHARED~~ | ~~없음~~ — **deprecated** |
| ~~multistage (N=2,M=2)~~ | ~~9~~ | ~~SHARED~~ | ~~없음~~ — **deprecated** |
| **nightmare (N=3,M=3)** | **5** | **PIONEER** | **-23% 시간, 33% vs 0% 성공** |

**인사이트**: Model-Tier가 PIONEER_PROMPT보다 설득력 있는 벤치마크. 상위 모델이 자연스럽게 더 나은 해결 과정 생성 → Overmind 자동 전파 → 하위 모델의 시행착오 감소 + 성공률 증가.

---

## 완료된 작업 (이번 세션)

### ✅ 프로젝트 리뷰 + 테스트 가동
- 전체 241 테스트 통과 확인 (server 119 + plugin 122)
- cp949 경고 발견 → UTF-8 인코딩 가이드 CLAUDE.md에 추가

### ✅ 저가치 AB scaffold deprecation
- simple/multistage/complex 레지스트리에서 제거
- 각 파일 DEPRECATED docstring + 재생성 금지 명시
- AB scaffold 설계 기준 4가지 명문화

---

## 다음 세션 추천 작업

### A. 제품 품질 개선 (높은 가치)

#### A1. cp949 → UTF-8 수정
Plugin hook의 subprocess 호출에서 `encoding="utf-8"` 누락. Windows 한글 환경에서 경고 발생.
- 영향 파일: `plugin/hooks/on_*.py`, `plugin/scripts/api_client.py`
- 난이도: 낮음 (subprocess.run/Popen에 encoding 파라미터 추가)

#### A2. SummaryGenerator LLM 교체
현재 MockSummaryGenerator — 실제 LLM 기반 요약으로 교체하면 pull 시 이벤트 소화 품질 향상.
- Protocol은 이미 정의됨, 구현체만 추가
- Claude API 또는 경량 모델 호출

#### A3. Dashboard branch 시각화
Flow View에 branch 정보 표시, branch별 필터. Phase 3 데이터는 DB에 있으나 UI 미반영.

### B. 벤치마크 강화 (Overmind 가치 증명)

#### B1. 새 고가치 scaffold 설계
현재 nightmare(단일 repo)과 branch_conflict(cross-branch)만 활성. 더 다양한 시나리오 필요:
- **multi-repo scaffold**: 서로 다른 repo의 에이전트가 공유 인프라(DB schema, API contract) 수정 시 충돌
- **regression scaffold**: Pioneer가 발견한 regression을 Student가 회피하는 시나리오
- 설계 기준 4가지 (misleading error, cross-file, 누적 제약, 정량 측정) 필수 충족

#### B2. N=5 M=5 대규모 통계 검증
현재 N=2~3, M=2~3. 통계적 유의성을 위해 더 큰 샘플 필요.
- 비용/시간 고려: haiku 기준 예상 소요

#### B3. Pioneer=opus 벤치마크
Pioneer=sonnet은 검증됨. opus가 더 나은 이벤트를 생성하는지 비교.

### C. 플러그인 성숙도 (배포 준비)

#### C1. 마켓플레이스 배포 최종 점검
plugin.json, hooks.json 스키마 검증. README/설치 가이드 업데이트.

#### C2. TTL 기반 context.md 만료
현재 context.md가 무한 누적. TTL 기반으로 오래된 이벤트 자동 제거.

#### C3. overmind_memory MCP tool 고도화
scope 필터 외 branch 필터, time range 필터 추가.

### D. 코드 품질

#### D1. Plugin hook subprocess encoding 일관성
UTF-8 가이드를 실제 코드에 반영 (A1과 연동).

#### D2. 테스트 경고 제거
websockets deprecation + cp949 경고 해결.

---

## 핵심 변경 맵 (최근)

| 영역 | 파일 | 변경 |
|------|------|------|
| Model | `models.py` | +current_branch, +base_branch, +intent type |
| Store | `store.py` | +branch 컬럼, 3-tier pull relevance |
| API | `api.py` | +branch/base_branch pull 파라미터 |
| Plugin | `api_client.py` | +get_current_branch(), +get_base_branch() |
| Plugin | `on_session_start.py` | branch metadata 자동 첨부 |
| Plugin | `formatter.py` | +PLANNED CHANGES section, +branch tag |
| Test | `test_store.py` | +8 branch 테스트 |
| Infra | `ab_scaffolds/` | active: nightmare, branch_conflict (deprecated: simple, multistage, complex) |
| Infra | `ab_runner.py` | 공통 agent runner + 통계 + port_conflict_count metric |
| Docs | `CLAUDE.md` | +UTF-8 가이드, +AB scaffold 설계 기준, 테스트 수 업데이트 |
| Docs | `session-next.md` | v3 — deprecated scaffold 반영, 다음 작업 재구성 |
