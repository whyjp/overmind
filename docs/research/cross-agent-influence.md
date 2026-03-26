# Cross-Agent Influence 연구: 다른 에이전트의 행동을 어떻게 바꿀 것인가

## 핵심 아이디어

프롬프트 실행 전 훅이 발동 → 리모트 에이전트의 lesson을 pull → 현재 프롬프트에 덧붙임
→ lesson이 포함된 경우 기존(pull 없을 때)과 **다른 결과**를 도출 (더 나은/개선된/규칙을 지키는)

## 현재 상태: 동작하지만 한계가 있다

| 상황 | 현재 동작 | 결과 |
|------|----------|------|
| Claude가 **스스로** 판단해서 코드 작성 | systemMessage의 RULES 참조 → 레슨 반영 | **동작함** ✓ |
| 유저가 **직접** 위반을 지시 | systemMessage < 유저 지시 | **밀림** ✗ |
| urgent correction + scope 매칭 | PreToolUse deny → 도구 차단 | **동작함** ✓ |

**핵심 구분**: Claude의 자율적 판단에는 영향을 줄 수 있지만, 유저의 직접 지시를 거스르지는 못한다.
이것은 Claude의 설계 원칙(유저 지시 > 시스템 메시지)에 기인하며, Overmind의 결함이 아니다.

실제 사용 시나리오의 대부분은 Claude가 자율적으로 판단하는 경우다:
- "이 버그를 고쳐줘" → Claude가 어떤 파일을 어떻게 수정할지 결정 → RULES의 "bcrypt 대신 argon2" 반영
- "API 엔드포인트 추가해줘" → Claude가 패턴 선택 → RULES의 "input validation 필수" 반영
- "캐시 구현해줘" → Claude가 라이브러리 선택 → CONTEXT의 "Redis v3 메모리릭" 참조

**결론: 원래 아이디어는 유효하고, 현재 구현으로 핵심 시나리오(Claude 자율 판단)는 커버된다.**

## 남은 문제: 한계와 보강 방향

현재 아키텍처의 세 가지 한계:

1. **systemMessage는 참고사항** — Claude는 유저의 직접 지시를 우선한다
2. **SessionStart 1회 주입** — 세션 중반에 효력이 사라진다
3. **패턴 다양성** — 억제만이 아니라, 대체 제안/규칙 기록/지식 공유 등 다양한 레슨이 있다

## 레슨 패턴 분류

| 패턴 | 예시 | 필요한 영향력 |
|------|------|-------------|
| 억제 | "cpp 파일 수정 금지" | 도구 차단 (hard block) |
| 대체 제안 | "bcrypt 대신 argon2" | 편집 시 능동적으로 반영 |
| 영구 규칙 | "모든 API에 input validation" | 세션 전체 지속 |
| 지식 공유 | "이 라이브러리 v3에 메모리릭" | scope 접근 시 경고 |
| 설계 방향 | "factory 패턴 사용" | 관련 코드 작성 시 참조 |
| 위험 경고 | "이 파일 건드리면 CI 깨짐" | 도구 차단 또는 강한 경고 |

## Claude Code의 영향력 채널 (강도 순)

### 1. Permission Rules (강제 — harness 수준)

```json
// .claude/settings.local.json
{
  "permissions": {
    "deny": ["Bash(rm -rf *)", "Edit(src/deploy/*)"],
    "allow": ["Bash(pnpm *)"]
  }
}
```

- **강도**: 최강. harness가 강제하므로 Claude도 유저도 우회 불가
- **지속성**: 세션 전체, 파일 변경 시 즉시 반영
- **한계**: 정적 패턴만 가능. 동적 규칙(레슨 기반) 불가
- **Overmind 활용**: SessionStart 훅에서 urgent correction을 파싱 → permissions deny 규칙으로 변환 → settings.local.json에 기록

### 2. PreToolUse Hook — permissionDecision: "deny" (강제 — 도구 차단)

```python
# 현재 구현됨
{"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "OVERMIND BLOCK: ..."
}}
```

- **강도**: 강함. 도구 사용 자체를 차단
- **지속성**: 매 도구 호출 시 평가 (잊혀지지 않음)
- **한계**: 차단만 가능. "이렇게 바꿔라"는 표현 불가
- **Overmind 활용**: 현재 urgent correction + scope 매칭 시 차단 구현 완료

### 3. CLAUDE.md (강한 참고 — 컨텍스트 수준)

```markdown
# .claude/CLAUDE.md 또는 프로젝트 루트 CLAUDE.md
## Team Rules (Overmind-managed, do not edit manually)
- Use argon2 instead of bcrypt for all password hashing
- All API endpoints must validate input with Pydantic
```

- **강도**: 중상. system prompt보다 신뢰도 높음. compaction 후에도 재로드됨
- **지속성**: 세션 전체 (compaction 후 재로드), git으로 공유 가능
- **한계**: advisory — Claude가 "읽고 따르려 노력"하지만 강제 아님
- **Overmind 활용**: SessionStart 훅에서 pull한 규칙을 CLAUDE.md의 특정 섹션에 기록. 핵심 채널.

### 4. systemMessage 주입 (참고 — 프롬프트 수준)

```python
# 현재 구현됨 (SessionStart, PreToolUse)
{"systemMessage": "[OVERMIND] RULES — Apply these..."}
```

- **강도**: 중. Claude가 참고하지만 유저 지시에 밀림
- **지속성**: 주입 시점에만 유효. 대화가 길어지면 잊혀짐
- **한계**: SessionStart 1회 + PreToolUse(Write/Edit 시) — 모든 프롬프트에 주입 불가
- **Overmind 활용**: 현재 주력 채널. 즉시성은 좋지만 지속성 부족

### 5. MCP Resources (수동 참조)

```python
# MCP 서버에서 resource 노출
@mcp.resource("overmind://rules/{repo_id}")
def get_rules(repo_id): ...
```

- **강도**: 약. Claude가 능동적으로 읽어야 함
- **지속성**: 참조할 때만
- **한계**: 자동 주입 불가. Claude가 "읽어볼까" 판단해야 함
- **Overmind 활용**: 보조 채널. 스킬에서 "먼저 overmind 규칙을 확인하라" 지시 가능

### 6. Auto Memory (개인 메모리)

```
~/.claude/projects/<project>/memory/MEMORY.md
```

- **강도**: 높음 (Claude 자신이 작성한 것이라 신뢰)
- **지속성**: 세션 간 지속
- **한계**: 머신 로컬, 팀 공유 불가
- **Overmind 활용**: 훅이 auto memory에 팀 규칙을 주입할 수 있으나, 개인 메모리 오염 우려

## 추천 전략: 다중 채널 동시 적용

단일 채널로는 부족하다. 레슨 타입에 따라 적합한 채널 조합을 사용해야 한다.

### 억제형 레슨 → Channel 1 + 2

```
urgent correction push
  → PreToolUse 훅: permissionDecision deny (즉시 차단)
  → settings.local.json: permissions deny 규칙 추가 (영구 차단)
```

### 규칙형 레슨 → Channel 3 + 4

```
correction/decision push
  → CLAUDE.md: "## Overmind Team Rules" 섹션에 추가
  → SessionStart systemMessage: RULES로 표시 (보조)
```

### 지식형 레슨 → Channel 4 + 5

```
discovery/change push
  → SessionStart systemMessage: CONTEXT로 표시
  → MCP resource: 필요 시 상세 조회 가능
```

## 구현 우선순위

### Phase 1.5 (즉시 — 현재 세션에서)

1. **CLAUDE.md 주입**: SessionStart 훅에서 pull한 correction/decision을
   프로젝트 CLAUDE.md의 `## Overmind Team Rules` 섹션에 자동 기록.
   - 장점: compaction 후에도 유지, 세션 전체 영향
   - 주의: 원본 CLAUDE.md를 망가뜨리지 않도록 마커 기반 섹션 관리 필요

```markdown
<!-- OVERMIND:START — auto-managed, do not edit -->
## Overmind Team Rules
- Use argon2 instead of bcrypt (correction by dev_a, 2026-03-27)
- All API endpoints must validate input (decision by dev_b, 2026-03-27)
<!-- OVERMIND:END -->
```

2. **permissions 동적 주입**: urgent correction의 scope를 파싱하여
   `.claude/settings.local.json`의 permissions.deny에 추가.

### Phase 2 (검증 후)

3. **InstructionsLoaded 훅**: CLAUDE.md 로드 시점 감지 → 팀 규칙 검증
4. **SessionEnd 개선**: 세션 중 실제 correction/decision 자동 추출 → push
5. **MCP resource**: `overmind://rules/{repo_id}` 리소스로 규칙 상세 조회

### Phase 3 (확장)

6. **Subagent 프리셋**: 높은 위험 작업(deploy, DB migration)용 제한된 서브에이전트 정의
7. **피드백 루프**: 레슨이 실제로 적용됐는지 PostToolUse에서 추적

## 설계 원칙: push는 사실 기록, pull이 판단한다

### push/pull 책임 분리

```
push 시: "나는 이런 사실을 발견/결정했다" (독립적 선행 사건)
pull 시: "이 사실이 지금 내 동작과 충돌하는가?" (맥락 기반 판단)
```

push하는 에이전트는 자기 맥락만 안다. "Button A는 결제에 사용된다"를 push할 때,
다른 에이전트가 그 버튼을 삭제하려 한다는 것은 모른다.

따라서 **deny/ask/ignore 판단은 반드시 pull 측에서** 이루어져야 한다:

| push 시 정보 | pull 시 판단 | 결과 |
|-------------|-------------|------|
| "Button A는 결제에 사용" (correction) | 현재 동작: Button A 삭제 → **충돌** | ask (유저 확인) |
| "Button A는 결제에 사용" (correction) | 현재 동작: Button B 수정 → **무관** | systemMessage (참고) |
| "bcrypt 대신 argon2" (correction) | 현재 동작: 인증 코드 작성 → **관련** | RULES (적용 유도) |

### 현재 구현의 한계

현재 PreToolUse 훅의 판단 로직:

```python
# 현재: scope 매칭 + priority 기반 (정적)
if urgent and correction and scope_matches:
    deny()  # push 시 priority에 종속
```

이것의 문제:
- push 시 `priority: urgent`를 설정한 것에 판단이 종속됨
- scope가 매칭되더라도 실제 충돌인지 알 수 없음 (같은 파일이라도 다른 부분을 수정할 수 있음)
- "이 편집의 의도"와 "레슨의 내용"이 충돌하는지 판단할 수 없음

### 해결 방향: pull 측 충돌 감지

**Phase 2 목표**: PreToolUse 훅에서 "현재 동작 vs 레슨" 충돌을 판단

```
PreToolUse 발동
  → 현재 동작 정보: tool_name, tool_input (file_path, old_string, new_string 등)
  → pull한 레슨: 해당 scope의 correction/decision 목록
  → 충돌 판단: 현재 편집이 레슨과 모순되는가?
  → 결과: deny/ask/systemMessage
```

충돌 판단에는 세 가지 접근이 가능:

1. **키워드 매칭** (가벼움, 부정확): 레슨에 "삭제 금지"가 있고 현재 동작이 "삭제"면 충돌
2. **구조적 규칙** (중간): 레슨을 `{action: "prohibit", target: "ButtonA", reason: "..."}` 형태로 구조화하여 매칭
3. **LLM 판단** (정확, 비용 큼): 레슨 + 현재 편집을 짧은 프롬프트로 보내 충돌 여부 판단

Phase 2에서는 (2) 구조적 규칙부터 시작하고, 부족하면 (3) 경량 LLM 판단을 도입한다.

## 핵심 인사이트

1. **단일 채널은 부족하다.** systemMessage만으로는 영향력이 약하고, CLAUDE.md만으로는 즉시성이 없다. 동시 적용이 필수.

2. **차단은 쉽고, 유도는 어렵다.** "하지 마라"는 PreToolUse deny로 강제 가능하지만, "이렇게 해라"는 Claude의 자발적 협조에 의존한다.

3. **CLAUDE.md가 가장 현실적인 지속 채널이다.** compaction 후 재로드되고, git으로 공유 가능하며, Claude가 시스템 지시로 인식하는 가장 강한 advisory 채널이다.

4. **permissions는 유일한 강제 채널이다.** 동적으로 생성할 수 있다면, urgent correction을 permissions deny 규칙으로 변환하는 것이 가장 확실한 차단 수단이다.

5. **Go/No-Go 기준의 재해석**: PRD의 "B의 Claude가 A의 lesson을 판단에 반영하는가"는 현재 아키텍처에서 **CLAUDE.md 주입 + PreToolUse 차단의 조합**으로 달성 가능하다. systemMessage 단독으로는 불가능하다.

6. **push는 사실, pull이 판단.** push하는 에이전트는 자기 맥락만 안다. deny/ask/ignore는 pull하는 에이전트가 "현재 동작과 충돌하는가"를 기준으로 결정해야 한다. 현재는 push 시 priority에 종속되어 있으며, Phase 2에서 pull 측 충돌 감지로 개선해야 한다.

## 근본 문제: 과정 공유가 프롬프트에 영향을 미치기 어려운 구조

### 현재 아키텍처의 구조적 한계

Overmind의 핵심 가치는 **과정 공유**(A의 시행착오가 B의 판단에 반영)인데,
현재 사용 가능한 모든 주입 채널이 각각 치명적 약점을 가진다:

| 채널 | 문제 |
|------|------|
| systemMessage | 일시적. 세션 중반에 잊힘. 유저 지시에 밀림 |
| CLAUDE.md | 지속적이지만 **망각이 어렵다**. 규칙이 누적되고 오래된 규칙을 제거하기 어렵다. 파일이 비대해지면 효과가 떨어진다 |
| permissions | 강제 차단만 가능. "이렇게 해라"는 표현 불가 |
| PreToolUse deny | 차단만 가능. 유도/제안 불가 |
| auto memory | 머신 로컬. 팀 공유 불가 |

**어느 단일 채널도 "다른 에이전트의 과정이 내 판단에 자연스럽게 녹아드는 것"을 달성하지 못한다.**

### CLAUDE.md 주입의 딜레마

CLAUDE.md는 가장 현실적인 지속 채널이지만 근본적 문제가 있다:

1. **망각 불가**: 한번 쓰면 지우기 어렵다. 오래된 레슨이 누적된다
2. **컨텍스트 오염**: 무관한 레슨이 쌓이면 Claude의 판단력이 오히려 저하된다
3. **충돌 관리**: 모순되는 레슨이 공존할 수 있다 (A: "bcrypt 사용", B: "argon2 사용")
4. **비추천 패턴**: CLAUDE.md를 동적으로 수정하는 것은 설계 의도에 맞지 않다
5. **git 충돌**: 여러 에이전트가 동시에 CLAUDE.md를 수정하면 충돌

### 필요한 것: 리모트 메모리 동기화 레이어

현재 Claude Code의 메모리 구조:

```
~/.claude/projects/<project>/memory/MEMORY.md  ← 머신 로컬, 개인용
프로젝트/CLAUDE.md                              ← git 공유, 정적 규칙용
```

필요한 것:

```
Overmind Server                    ← 팀 공유 메모리 (리모트)
  ↕ 동기화
로컬 에이전트의 컨텍스트            ← 개별 에이전트가 "자기 것처럼" 읽는 메모리
```

이것은 현재 플러그인 시스템으로는 완전히 구현할 수 없다.
플러그인이 할 수 있는 것은 **훅을 통한 간접 주입**뿐이고,
Claude의 내부 메모리 시스템을 오버라이드하거나 확장하는 것은 불가능하다.

### 접근 방식 비교

#### 방식 A: CLAUDE.md 마커 기반 주입 (현재 가능)

```markdown
<!-- OVERMIND:START -->
## Team Rules (auto-synced, last updated: 2026-03-27T12:00:00Z)
- Use argon2 instead of bcrypt (by dev_a)
- All API endpoints must validate input (by dev_b)
<!-- OVERMIND:END -->
```

- 장점: 지금 구현 가능, compaction 후 재로드
- 단점: 망각 어렵, 누적 문제, CLAUDE.md 오염, 동시 수정 충돌

#### 방식 B: 전용 메모리 파일 동기화 (현재 가능, 실험적)

```
.claude/overmind-context.md  ← 훅이 관리하는 별도 파일
```

CLAUDE.md에는 `@.claude/overmind-context.md`로 임포트만 하고,
실제 내용은 훅이 pull 시마다 갱신하는 별도 파일.

- 장점: CLAUDE.md 오염 최소화, TTL 기반 만료 가능
- 단점: `@import` 지원 여부 확인 필요, 여전히 간접 주입

#### 방식 C: MCP Resource + Skill 조합 (현재 가능, 수동)

```python
# MCP resource로 팀 메모리 노출
@mcp.resource("overmind://memory/{repo_id}")
def get_team_memory(repo_id): ...
```

스킬에서 "작업 시작 전 overmind 메모리를 확인하라" 지시.

- 장점: 최신 데이터 보장 (매번 서버에서 가져옴)
- 단점: Claude가 자발적으로 읽어야 함, 자동화 불가

#### 방식 D: 플러그인 메모리 시스템 오버라이드 (현재 불가)

Claude Code의 auto memory 시스템을 플러그인이 확장하여,
로컬 메모리 + 리모트 메모리를 통합된 하나의 메모리로 보이게 하는 것.

```
Claude가 메모리를 읽을 때:
  로컬 auto memory + Overmind 리모트 메모리 → 통합 뷰

Claude가 메모리를 쓸 때:
  로컬에 저장 + Overmind에 push → 양방향 동기화
```

- 장점: 가장 자연스러운 통합. Claude가 "자기 메모리"로 인식
- 단점: **Claude Code 플러그인 API가 이것을 지원하지 않음**. 메모리 시스템은 플러그인이 접근할 수 없는 내부 구현

### 현실적 판단

1. **방식 D가 이상적이지만 현재 불가능하다.** Claude Code가 플러그인 메모리 확장 API를 제공하기 전까지는 간접 방법에 의존해야 한다.

2. **방식 B가 가장 현실적인 차선책이다.** 전용 파일 + TTL 기반 만료로 "망각 가능한 리모트 메모리"를 근사할 수 있다.

3. **방식 A는 피해야 한다.** CLAUDE.md를 동적으로 수정하는 것은 부작용이 크다.

4. **방식 C는 보조 수단으로 유효하다.** 자동화는 안 되지만, 스킬을 통해 "필요할 때 팀 메모리를 조회"하는 패턴은 가치 있다.

### 제안: Phase 2 아키텍처

```
SessionStart 훅
  → Overmind pull
  → .claude/overmind-context.md 생성/갱신 (TTL 기반 만료 적용)
  → 만료된 레슨 자동 제거, 신규 레슨 추가
  → systemMessage로 "신규 변경사항" 알림

PreToolUse 훅 (매 편집 시)
  → scope 관련 레슨 pull
  → 충돌 감지 → deny/ask/systemMessage

SessionEnd 훅
  → 세션 중 발생한 correction/decision 자동 추출
  → Overmind push
  → .claude/overmind-context.md 정리 (소비 완료된 이벤트 제거)

CLAUDE.md
  → "@.claude/overmind-context.md" 임포트 (한 줄만)
  → Overmind이 관리하는 내용과 프로젝트 규칙이 분리됨
```

이 구조에서 `.claude/overmind-context.md`는 **"망각 가능한 리모트 메모리의 로컬 캐시"** 역할을 한다.
TTL로 오래된 레슨이 자동 만료되고, 세션마다 서버에서 최신 상태를 동기화한다.

### 장기 과제: Claude Code 플러그인 메모리 API

Overmind의 궁극적 목표를 달성하려면 Claude Code가 다음을 지원해야 한다:

1. **플러그인 메모리 확장 API**: 플러그인이 auto memory에 항목을 추가/제거할 수 있는 인터페이스
2. **메모리 소스 다중화**: 로컬 메모리 + 리모트 메모리를 하나의 통합 뷰로 제공
3. **메모리 TTL/만료**: 메모리 항목에 만료 시간을 설정하여 자동 정리

이 API가 없는 현재로서는 `.claude/overmind-context.md` + 훅 기반 동기화가 최선이다.
