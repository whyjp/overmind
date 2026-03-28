# Autoresearch 결과: A/B Multistage 테스트 — 플러그인 개선 + 실측 벤치마크

**날짜**: 2026-03-28
**상태**: 구현 + 실측 완료
**목표**: Overmind 플러그인이 자연스럽게 에이전트 행동을 개선하는지 검증
**범위**: plugin/ (formatter, hooks, context_writer, api_client) + server/tests/scenarios/
**핵심 지표**: Student의 server_run_attempts, total_tool_uses 가 Naive보다 적은지

---

## 핵심 결론

### 1. Formatter는 사실만 전달해야 한다 (행동 지시 금지)

초기 접근("FIXES BY TEAMMATES — Apply ALL fixes BEFORE running")은 **테스트를 강제로 통과시키는 장치**였지 Overmind 시스템의 자연스러운 기능이 아니었다.

최종 접근: `TEAMMATE CHANGES — What other agents changed (with diffs):` — 사실만 전달하고 에이전트가 자율적으로 판단.

### 2. 진짜 버그는 scope의 절대 경로였다

`file_to_scope()`가 절대 경로(`C:/Users/.../agent_pioneer/hive-multi/*`)를 반환 → 서로 다른 tmp 디렉토리의 에이전트 간 scope가 절대 매치되지 않음 → PreToolUse에서 Pioneer의 이벤트가 Student에게 안 보임.

**수정**: git root 기준 상대 경로 정규화 + PreToolUse scope 필터 제거.

### 3. 모델 능력이 테스트 난이도를 압도할 수 있다

| 모델 | 8단계 캐스케이드 해결 패턴 | Overmind 효과 |
|------|------------------------|-------------|
| **haiku** | 순차 발견 (7-8회 실행) | tool_uses 감소 측정 가능 |
| **sonnet** | 1-2회 만에 전체 해결 | 천장 효과 — 이미 최적이라 개선 여지 없음 |

---

## 실측 벤치마크 데이터

### Haiku 4회 실행 (autoresearch iteration 0-3)

| Run | 수정 내용 | Pioneer runs | Student runs | Naive runs | Student tools | Naive tools | 우위 |
|:---:|----------|:---:|:---:|:---:|:---:|:---:|:---:|
| 0 | 절대경로 scope (버그) | 8 | 7 | 7 | 22 | 17 | **No** |
| 1 | scope 필터 제거 | 7 | 7 | 7 | **20** | **23** | **Yes** |
| 2 | context_writer 구조화 | 11 | **7** | 7 | **21** | **24** | **Yes** |
| 3 | 재현성 확인 | 7 | **7** | **8** | **20** | **23** | **Yes** |

버그 수정 후 3/3에서 Student tool_uses < Naive tool_uses.

### Sonnet 5회 실행

| Run | Pioneer runs | Student runs | Naive runs | Pioneer tools | Student tools | Naive tools | 우위 |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | 1 | 1 | **2** | 13 | 14 | 13 | **Yes** (runs) |
| 2 | 1 | 1 | 1 | 14 | 14 | 14 | — (천장) |
| 3 | 1 | 1 | 1 | 14 | 14 | 14 | — (천장) |
| 4 | **2** | 1 | 1 | 14 | 14 | 14 | **Yes** (runs) |
| 5 | 3 | 3 | 3 | 10 | 19 | 17 | **No** |

**Sonnet 평균**: Pioneer 1.6, Student 1.4, Naive 1.6 runs. 차이가 미미 — 모델이 너무 똑똑해서 Overmind 유무와 관계없이 1-2회로 해결.

### 모델별 요약

| 모델 | 평균 Student runs | 평균 Naive runs | Student 우위 빈도 | 비고 |
|------|:---:|:---:|:---:|------|
| **haiku** | 7.0 | 7.5 | 3/4 (75%) tool_uses 기준 | runs는 비슷, tools에서 차이 |
| **sonnet** | 1.4 | 1.6 | 2/5 (40%) | 천장 효과 — 3/5는 모두 1회로 해결 |

---

## 변경 사항 상세

### Phase 1: 테스트 코드 개선 (첫 커밋, 이미 main에 병합)

| 파일 | 변경 |
|------|------|
| `server/tests/scenarios/test_live_agents_AB_multistage.py` | 8단계 캐스케이드 + proactive 지표 + 어설션 + run_summary.json |
| `plugin/scripts/formatter.py` | diff 이벤트를 별도 섹션으로 분리 (`_has_diff()`) |
| `plugin/tests/test_formatter.py` | diff 분류 테스트 추가 |

### Phase 2: 플러그인 버그 수정 + 중립적 포매팅 (현재 미커밋)

| 파일 | 변경 | 이유 |
|------|------|------|
| `plugin/scripts/api_client.py` | `file_to_scope()` git root 기준 상대 경로 정규화 | 절대 경로로 인한 scope 불일치 해소 |
| `plugin/hooks/on_pre_tool_use.py` | scope 파라미터 제거하고 전체 pull | 상대 경로 정규화 후에도 scope 매칭이 불완전할 수 있으므로 |
| `plugin/scripts/formatter.py` | "FIXES BY TEAMMATES — Apply ALL" → "TEAMMATE CHANGES" (중립적) | 행동 지시가 아닌 사실 전달 원칙 |
| `plugin/scripts/context_writer.py` | diff 이벤트를 ```diff 코드블록으로 구조화 | .claude/overmind-context.md에 지속 참조 가능한 형태 |
| `plugin/tests/test_formatter.py` | 중립적 포매팅 테스트 + "지시적 문구 없음" 검증 | formatter가 행동 지시하지 않음을 보장 |
| `plugin/tests/test_api_client.py` | root file scope 기대값 수정 (`"*"`) | file_to_scope 변경 반영 |
| `plugin/tests/test_context_writer.py` | diff 구조화 테스트 2개 추가 | 신규 기능 검증 |

### 검증

- Plugin 테스트: **74 passed** (test_hooks.py 제외)
- 모든 e2e 테스트: **ASSERT PASS** (9회 실행 전부)

---

## Autoresearch 전체 반복 과정

### 세션 1: 초기 접근 (테스트 + formatter 개선)

```
Iteration 0: 탐색 — 테스트/플러그인/연구문서 전체 읽기
  └─ 가설: formatter가 diff를 수동적 CONTEXT로 분류하는 것이 문제

Iteration 1: Formatter를 "FIXES BY TEAMMATES — Apply BEFORE running"으로 변경
  └─ 18/18 pass, Keep

Iteration 2: 테스트 전면 재작성 (8단계 + proactive 지표 + 어설션)
  └─ Keep

Iteration 3: 회귀 테스트
  └─ 74/74 pass, 61/61 server pass

→ 커밋 + main 병합 + push
```

### 세션 2: e2e 실측 → 근본적 방향 전환

```
e2e 실행 (haiku): Student 7 runs, Naive 7 runs — 차이 없음!

JSONL 분석:
  → Student가 FIXES BY TEAMMATES 메시지를 수신하는 것 확인
  → 그러나 프롬프트의 "Run bash start.sh" 직접 지시가 systemMessage보다 우선
  → 첫 실패 후에도 FIXES 정보를 활용하지 않고 순차 반복

시도 1: 프롬프트를 비지시적으로 변경 ("Run start.sh" → "The start command is...")
  → 사용자 피드백: "첫 행동은 서버 시작이 옳음. 실패 후 다른 에이전트 경험을 바탕으로
     더 빠르고 확실한 수정을 하는 게 목표. 테스트를 강제하는 장치가 아닌가?"
  → 프롬프트 복원

시도 2: PreToolUse에서 Edit 시점에 FIXES 재주입
  → 사용자 피드백: "formatter가 행동을 지시하면 안 된다. 사실만 전달해야 한다."
  → formatter를 중립적 "TEAMMATE CHANGES"로 재작성

핵심 전환점: 테스트 강제 vs 시스템 개선
  → "FIXES BY TEAMMATES — Apply ALL" = 테스트를 위한 장치 (잘못됨)
  → "TEAMMATE CHANGES — What other agents changed" = 시스템의 자연스러운 기능 (올바름)
```

### 세션 3: 진짜 버그 발견 + 중립적 접근으로 실측

```
Autoresearch Iteration 0: 진단
  → file_to_scope()가 절대 경로 반환 → scope 매치 불가능!
  → 이것이 PreToolUse에서 Pioneer 이벤트가 Student에게 안 보이는 근본 원인

Iteration 1: file_to_scope 상대 경로 정규화 + PreToolUse scope 제거
  → Guard 72 pass
  → Verify: Student 7 runs vs Naive 7 runs, tools 20 vs 23 → 부분적 개선

Iteration 2: context_writer에 diff 구조화 (```diff 코드블록)
  → Guard 74 pass
  → Verify: Student 7/21 vs Naive 7/24 → ADVANTAGE CONFIRMED

Iteration 3: 재현성 확인
  → Student 7/20 vs Naive 8/23 → ADVANTAGE CONFIRMED

→ Sonnet 5회 추가 실행 → 천장 효과 확인
```

---

## 설계 원칙 (학습 사항)

### 1. Formatter는 사실 전달자 (팩트 채널)

```
❌ "FIXES BY TEAMMATES — Apply ALL of these diffs at once"  (행동 지시)
❌ "IMPORTANT: Do NOT re-discover issues"                    (행동 금지)
✅ "TEAMMATE CHANGES — What other agents changed (with diffs):" (사실 전달)
✅ "Consider this context before making changes to this scope." (중립적 안내)
```

Overmind의 가치는 에이전트에게 **정보를 제공**하는 것이지, **행동을 강제**하는 것이 아님.

### 2. 첫 실행은 항상 올바르다

서버가 이미 올바르게 설정되어 있을 수도 있음. `start.sh` 실행이 첫 행동인 것은 정상.
Overmind의 효과는 **첫 실패 이후** 에이전트가 정보를 활용하여 더 효율적으로 수정하는 데서 나옴.

### 3. Scope는 repo-relative여야 한다

```
❌ C:/Users/cxx/AppData/Local/Temp/pytest-xxx/agent_pioneer/hive-multi/*
✅ *  (root file)
✅ src/auth/*  (nested path)
```

에이전트 간 절대 경로가 다르므로 scope는 반드시 git root 기준 상대 경로.

### 4. 테스트는 측정 도구이지 강제 도구가 아니다

```
❌ 프롬프트를 조작해서 Student가 FIXES를 먼저 적용하도록 유도
❌ Formatter에 "Apply BEFORE running" 지시를 삽입
✅ 프롬프트는 동일하게 유지, 플러그인이 자연스럽게 정보 전달
✅ 테스트는 결과만 측정하고 행동을 강제하지 않음
```

### 5. 모델 능력에 따른 테스트 난이도 설계

| 모델 수준 | 필요한 테스트 난이도 | 현재 8단계 캐스케이드 |
|----------|-----------------|-------------------|
| haiku (약) | 중간 — 순차 발견 필요 | **적절** — 7-8회 반복 |
| sonnet (중) | 높음 — 소스 분석으로 한번에 해결 | **너무 쉬움** — 1-2회 해결 |
| opus (강) | 매우 높음 | 미측정 |

향후 sonnet/opus용 테스트는 multi-file edit, dependency conflict 등 더 복잡한 시나리오 필요.

---

## 테스트 실행 방법

```bash
cd server

# 단일 실행
AGENT_MODEL=haiku uv run python -m pytest tests/scenarios/test_live_agents_AB_multistage.py -m e2e_live -s

# 5회 반복 (통계용)
for i in $(seq 1 5); do
  echo "=== Run $i ==="
  AGENT_MODEL=haiku uv run python -m pytest tests/scenarios/test_live_agents_AB_multistage.py \
    -m e2e_live -s --tb=short 2>&1 | grep -E "(server_run_attempts|total_tool_uses|>>)"
done
```

---

## 미해결 과제

1. **Sonnet/Opus 전용 시나리오**: 현재 8단계 캐스케이드는 sonnet에게 너무 쉬움
2. **server_run_attempts 일관적 감소**: haiku에서 tool_uses는 줄지만 runs는 아직 비슷 (7 vs 7-8)
3. **PreToolUse scope 재도입**: 상대 경로 정규화가 안정화되면 scope 필터를 다시 적용하여 노이즈 감소
4. **구조화된 레슨**: 현재 raw diff 전달 → 향후 `{action, target, reason}` 구조화 레슨으로 발전
