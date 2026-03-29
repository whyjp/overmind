# Overmind — 다음 세션 브리핑

**마지막 업데이트**: 2026-03-30 (v4)
**현재 브랜치**: main

---

## 전체 진행 상태

### Phase 1~3: ✅ 완료 (변경 없음)

### Statistical AB Test Framework: ✅ 완료
- [x] 세트 기반 병렬 구조: `[Pioneer→Student]` 동일 repo_id, 세트 간 병렬, Naive 독립
- [x] ab_scaffolds/ — active: nightmare, branch_conflict
- [x] deprecated: simple, multistage, complex, **microservices** (Pioneer context 역효과)
- [x] scaffold 설계 기준 6가지 (소스 복잡도 + 순차 캐스케이드 추가)

---

## 테스트 현황

| 영역 | 수 | 내역 |
|------|-----|------|
| Server | 134 | models 12, store 30, api 14, mcp 6, scenarios 28, summary 2, nightmare 18, branch_conflict 11, microservices 15 |
| Plugin | 122 | api_client 32, flush 22, formatter 15, context_writer 10, diff_collector 6, conflict_detector 19, hooks 11 |
| E2E Live | 2 시나리오 | nightmare + branch_conflict (`claude` CLI 필요) |
| **합계** | **256** | |

---

## Statistical AB 벤치마크 결과

### 세트 기반 (2026-03-30, 최신 구조)

각 세트 = [Pioneer(sonnet) → Student(haiku)] 동일 repo_id. Naive(haiku) 독립 실행.

**nightmare (N=2, M=2):**

| 메트릭 | Pioneer | Student | Naive | 차이 |
|--------|---------|---------|-------|------|
| server_run_attempts | 6 | 12.0 | 15.0 | **Student -20%** |
| 성공률 | 100% | **100%** | **50%** | **Student 2배** |
| config_file_edits | 7 | 13.0 | 14.5 | -10% |
| elapsed | 122s | 170s | 174s | 비슷 |
| proactive_config_fix | Yes | **0%** | 0% | **둘 다 못함** |

**microservices (N=3, M=3) — DEPRECATED:**

| 메트릭 | Pioneer | Student | Naive | 차이 |
|--------|---------|---------|-------|------|
| server_run_attempts | 1 | **5.3** | **2.7** | **Naive 2배 나음** |
| 성공률 | 100% | 100% | 100% | 차이 없음 |
| elapsed | 88s | 73s | **50s** | **Naive 31% 빠름** |

### 핵심 인사이트: Overmind 가치 갭

1. **이벤트 전달은 동작함** — Pioneer 17~19개 이벤트가 Student에게 도달
2. **하지만 Student가 이를 선제적으로 활용하지 못함** — proactive_config_fix = 0%
3. **단순 문제에서 Pioneer context는 해로움** — microservices에서 Naive가 2배 나음
4. **nightmare에서만 성공률 차이 유의미** (100% vs 50%) — 소스 복잡도 + 순차 캐스케이드 필수

---

## 완료된 작업 (이번 세션)

### ✅ A1. cp949 → UTF-8 수정
- subprocess 호출 9곳에 `encoding="utf-8"` 추가

### ✅ B1. microservices scaffold 구현 → deprecated
- 5트랩 scaffold 구현 + 15 테스트
- 트랩 강화 (misleading 에러) + ab_runner 메트릭 확장
- 세트 기반 AB 실행 결과: Pioneer context 역효과 확인 → deprecated

### ✅ AB 테스트 인프라 개선
- 세트 기반 병렬 구조 (`[Pioneer→Student]` 동일 repo_id)
- ab_runner: `api_post()`, `services/*.toml` 메트릭, `All services running` 감지
- scaffold 설계 기준 6가지로 확장 (소스 복잡도 + 순차 캐스케이드)
- nightmare 세트 기반 검증: 100% vs 50% 성공 (기존 결과 재현)

---

## 다음 세션: Overmind 가치 상승 전략 (최우선)

현재 Overmind는 이벤트를 전달하지만 에이전트 행동을 효과적으로 변경하지 못함. **가치 상승이 새 scaffold보다 우선.**

### 0. 가치 갭 분석 (첫 작업)
현재 Pioneer가 push하는 이벤트 내용과 Student가 받는 context를 상세 분석:
- Pioneer 이벤트의 lesson 구조/품질
- formatter가 Student에게 주입하는 context의 실제 내용
- Student가 context를 받은 후 첫 행동 패턴

### 1. Push 품질 개선
Pioneer의 PostToolUse 이벤트가 구조화된 lesson(action/target/replacement)으로 자동 변환되어야 함.
현재: diff + scope 기반 raw 이벤트 → 개선: 구체적 수정 지시로 변환.

### 2. Pull 포맷 강화
formatter가 RULES/CONTEXT로 분류하지만 에이전트가 실행 가능한 형태가 아님.
- "파일 X의 라인 Y를 Z로 변경하라" 수준의 구체적 지시
- proactive_config_fix를 유도하는 포맷 실험

### 3. SessionStart 주입 전략
context.md에 Pioneer 지식이 들어가지만 에이전트가 "먼저 읽고 적용" 하지 않음.
- systemMessage에 "이 context를 먼저 적용하라" 지시 추가 실험
- 또는 CLAUDE.md에 Overmind context 우선 적용 규칙 추가

### 4. conflict_detector 실전 활용
prohibit/replace lesson이 실제 동작하는지 라이브 검증.
PreToolUse deny가 Student의 잘못된 시도를 차단하는 시나리오.

### 5. 양방향 상호작용 테스트
Pioneer→Student 단방향이 아닌 Student↔Student 양방향 시나리오.
실제 팀 작업에 더 가까운 형태.

---

## 기타 작업 (가치 상승 후)

### A. 제품 품질
- A2. SummaryGenerator LLM 교체
- A3. Dashboard branch 시각화

### B. 플러그인 성숙도
- C1. 마켓플레이스 배포 점검
- C2. TTL 기반 context.md 만료
- C3. overmind_memory branch/time 필터

---

## 핵심 변경 맵 (최근)

| 영역 | 파일 | 변경 |
|------|------|------|
| Infra | `ab_runner.py` | +api_post, +seed_pioneer_events, services/*.toml 메트릭, encoding utf-8 |
| Infra | `test_live_agents_AB_statistical.py` | 세트 기반 병렬 구조 ([Pioneer→Student] 동일 repo_id) |
| Infra | `ab_scaffolds/__init__.py` | active: nightmare, branch_conflict. deprecated += microservices |
| New | `ab_scaffolds/microservices.py` | 5트랩 scaffold (deprecated — Pioneer context 역효과) |
| Fix | `plugin/scripts/*.py` | subprocess encoding="utf-8" (cp949 해결) |
| Docs | `CLAUDE.md` | scaffold 설계 기준 6가지, UTF-8 가이드, 테스트 수 |
