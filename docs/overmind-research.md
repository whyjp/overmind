# Overmind: 독립 작업 주체 간 Claude Code 분산 메모리 동기화 아키텍처 연구

> 최종 아티팩트: **Overmind** (서버) + **Overmind Plugin** (클라이언트)

> 연구 일자: 2026-03-26
> 문서 버전: 2.3
> 대상 환경: Claude Code (Anthropic) 기반 멀티 개발자 협업

---

## 1. 연구 배경 및 동기

### 1.1 문제 정의

Claude Code는 개별 작업 주체(인간 개발자 또는 자율 에이전트)에게 강력한 AI 코딩 환경을 제공하지만, **복수의 독립 작업 주체**가 동일 프로젝트에서 병렬 작업할 때 근본적인 한계가 존재한다. 각 Claude 인스턴스는 **독립된 메모리 공간**(~/.claude/projects/\*/memory/)에서 동작하며, 다른 주체의 작업 맥락, 트러블슈팅 이력, 설계 결정 과정을 인지하지 못한다. 이 문제는 인간 개발자 간 협업에만 국한되지 않으며, 복수 자율 에이전트가 개별 태스크를 수행한 후 결론을 통합하는 구조에서도 동일하게 발생한다.

이로 인해 발생하는 실질적 문제:

- **지식 단절**: 개발자 A가 3시간 삽질 끝에 발견한 해결법을 개발자 B의 Claude는 모르고 동일한 삽질을 반복한다.
- **Intent 다형성**: PR/merge 후 코드는 하나가 되지만, 각 개발자의 Claude가 기억하는 "왜 이렇게 했는지"가 다르다. 코드 레벨에서는 conflict 없이 merge 됐더라도 intent 레벨에서는 서로 다른 설계 철학이 공존하는 상태가 된다.
- **프로젝트 메모리 일관성 붕괴**: 개인적 일관성은 유지되지만, 팀 전체로서의 프로젝트 맥락이 파편화된다.
- **Claude Code 속도에 의한 괴리 증폭**: Claude Code의 작업량과 속도는 인간 단독 작업 대비 방대하다. 이로 인해 별도 브랜치 작업이 빠르게 진행되어 장기화되거나, PR/merge가 지연되는 경우가 빈번히 발생한다. 이때 다른 개발자와의 코드베이스 괴리는 기존 Git 워크플로우보다 훨씬 빠르게 확대되며, merge 시점에서의 충돌과 맥락 불일치가 기하급수적으로 커진다.

### 1.2 Overmind 비유

StarCraft의 저그 종족에서 Overmind(초월체)는 모든 저그 개체의 의식을 하이브 마인드(Hive Mind)로 통합하는 최상위 존재다. 각 개체는 물리적으로 분리되어 있지만, 하나의 의식체가 전체를 관통한다.

본 연구에서 제안하는 Overmind 아키텍처는 이 개념을 차용한다. 각 개발자의 Claude 인스턴스는 물리적으로 별개의 개체이지만, **지속적 메모리 동기화를 통해 모든 Claude가 동일한 memory pool을 참조하는 상태를 유지**함으로써, 어떤 주체(인간 유저 또는 자율 에이전트)가 작업하든, 해당 Claude가 전체 팀의 과정과 맥락을 포함한 상태에서 사고하고 행동할 수 있도록 한다.

### 1.3 핵심 원칙

1. **각 작업 주체는 물리적으로 별개 개체다** — 인간 개발자든 자율 에이전트든, 이것은 바뀌지 않는다.
2. **sync를 통해 `자기 memory + 다른 주체의 memory × N`을 항상 유지한다** — Overmind의 본질.
3. **작업의 지시/자율 판단은 각자가 하되, 사고의 기반은 공유된다** — 지시는 로컬, 맥락은 글로벌.
4. **결과뿐 아니라 과정도 공유한다** — 시도, 실패, 이유, correction 이력 전체.
5. **다형성을 인지하고 고지한다** — 판단이 아니라 고지. 인간 유저에게 또는 에이전트 자체의 판단에 반영.

> **참고: 인간 개발자는 필수 제약이 아니다.** 이 아키텍처에서 "작업 주체"는 인간 개발자 + Claude Code 조합에 한정되지 않는다. 복수의 자율성 에이전트가 각각 독립된 작업을 수행하는 경우에도, 결론 통합 이전에 수시로 과정/lesson을 공유하고 전파하는 것은 동일하게 유효하다. Overmind의 설계는 "독립적 작업 주체 간의 과정 공유"라는 일반적 문제를 풀며, 그 주체가 인간이든 에이전트이든 구조는 동일하다.

### 1.4 적용 범위: 인간 개발자에 국한되지 않음

본 연구는 "복수 개발자"를 주요 시나리오로 서술하지만, Overmind 아키텍처의 적용 범위는 인간 개발자에 한정되지 않는다. **복수의 자율 에이전트가 독립적으로 작업하는 모든 환경**에서 동일한 가치가 발생한다.

Claude Code의 에이전트 팀(agent teams), git worktree 기반 병렬 세션, 또는 CI/CD 파이프라인에서 자율적으로 동작하는 복수의 Claude 인스턴스가 각자 브랜치에서 작업하고 최종적으로 결과를 통합하는 시나리오에서, 결론 통합 이전에 수시로 과정과 lesson을 공유/전파하면:

- 에이전트 A가 시도하고 실패한 접근법을 에이전트 B가 반복하지 않는다
- 같은 모듈에 대한 다른 전제(intent 다형성)를 통합 전에 감지한다
- 환경 설정, 의존성 제약 등 한 에이전트가 발견한 암묵지가 다른 에이전트의 사전 방어막이 된다

이 문서에서 "개발자"는 "독립적 작업 주체(인간 또는 에이전트)"로 읽을 수 있으며, "유저에게 고지"는 "작업 주체 또는 그 상위 오케스트레이터에게 고지"로 확장된다. Overmind의 핵심 가치 — 과정 흡수, 사전 차단, 다형성 감지 — 는 작업 주체가 인간이든 에이전트이든 동일하게 적용된다.

---

## 2. 기존 솔루션 분석

### 2.1 조사 대상

Claude Code 생태계에서 멀티 개발자 메모리 공유를 시도하는 프로젝트들을 조사하였다.

### 2.2 Supermemory (claude-supermemory)

- **상태**: 활성 (GitHub star 479, Pro $19/month)
- **아키텍처**: SaaS 기반 MCP 서버. containerTag로 메모리 scope 관리.
- **Team Memory 기능**: personal / team container 분리. 같은 containerTag를 공유하면 팀원 간 메모리 자동 merge.
- **기술적 특징**: ontology-aware edge 기반 커스텀 벡터 그래프 엔진, hybrid vector + keyword search (<300ms), temporal change 처리, contradiction 해소, 만료 정보 자동 삭제.
- **한계**:
  - SaaS 의존 (vendor lock-in, 구독 비용)
  - 쓰기가 세션 종료 시 auto-capture 또는 명시적 save → **비동기, 배치성**
  - 읽기가 세션 시작 시 context injection → **pull 기반**
  - 다른 개발자의 커밋/작업을 push/stream으로 받는 메커니즘 부재
  - **과정(process)이 아닌 결론(result)만 공유** — "A가 OAuth2를 선택했다"는 알지만 "왜 JWT를 기각했는지"는 모른다

### 2.3 Julep Memory Store Plugin

- **상태**: 2025년 12월 27일 archived (read-only). Star 6, fork 0.
- **평가**: 실질적 채택 없이 중단된 프로젝트. 검토 대상에서 제외.

### 2.4 Claude-Flow (ruflo) — Hive Mind Intelligence

- **상태**: 활성 (multi-agent orchestration platform)
- **아키텍처**: Queen Agent가 specialized worker agent를 조율. SQLite 기반 collective memory.
- **한계**: **한 프로젝트 내 multi-agent swarm** 개념. 한 사람이 여러 agent를 돌리는 것이지, 여러 인간 개발자의 Claude가 서로의 작업을 인지하는 구조가 아님.

### 2.5 Claude Cognitive

- **상태**: 활성 (multi-instance state sharing)
- **아키텍처**: attention 기반 파일 인젝션 + pool 디렉토리를 통한 instance 간 상태 공유. 자동 모드(5분 간격 completion/blocker 감지), 수동 모드(명시적 pool block).
- **한계**: 같은 머신 내 여러 Claude 세션 간 조율이 주 목적. 복수 개발자 × 복수 머신 시나리오 미지원.

### 2.6 Claude Sync 류 (claude-sync, claude-code-sync)

- **상태**: 활성 (디바이스 간 ~/.claude/ 동기화)
- **아키텍처**: git repo 또는 encrypted cloud를 통한 push/pull 동기화.
- **한계**: **같은 사람의 여러 머신** 동기화 문제를 풀 뿐, 팀 협업 레이어 아님.

### 2.7 Claude Code 네이티브 메모리

- **auto memory**: machine-local. 같은 git repo 내 worktree끼리 공유하지만 머신 간/클라우드 환경 간 공유 불가.
- **경로 기반 인덱싱**: 절대 경로 기반 관리. 다른 머신의 다른 username이나 mount point만 달라도 별개 프로젝트 취급.
- **CLAUDE.md**: git repo에 commit 가능하여 팀 공유 가능하지만, 수동 관리 필요.

### 2.8 분석 요약

| 솔루션 | 팀 메모리 | 과정 공유 | 실시간성 | Self-hosted | Repo-scoped |
|--------|----------|----------|---------|-------------|-------------|
| Supermemory | O (제한적) | X | X (pull) | X (SaaS) | O (containerTag) |
| Claude-Flow | X (single user) | X | O | O | O |
| Claude Cognitive | X (same machine) | 부분적 | O (5min) | O | O |
| Claude Sync | X (same person) | X | X (manual) | O | X (전역) |
| Claude 네이티브 | X | X | X | O | O |
| **Overmind (제안)** | **O** | **O** | **O (수시)** | **O** | **O** |

**핵심 Gap**: 기존 솔루션 중 어떤 것도 "복수 독립 작업 주체(인간/에이전트) × 각자의 로컬 작업 공간 × 과정 포함 실시간 메모리 동기화 × 다형성 감지"를 동시에 충족하지 못한다.

### 2.9 Simple 접근법과의 비교: MEMORY.md push → project auto-memory 치환

Overmind의 본격적인 아키텍처를 논하기 전에, 가장 단순한 대안과의 정직한 비교가 필요하다.

**Simple 접근법**: 각 개발자의 MEMORY.md를 git push하고, 다른 개발자의 session start 시 skill이 이를 pull하여 project auto-memory로 치환하는 방식. 새로운 개념이나 인프라가 전혀 필요 없으며, Claude Code의 기존 메커니즘만으로 구현 가능하다.

**Simple이 달성하는 것 (Overmind 목표의 70~80%)**:

- Claude의 auto-memory는 이미 우수한 지식 압축기로, 세션 중 correction, 패턴, 해결법을 자동 기록한다.
- 이를 git으로 공유하면 "A가 뭘 알게 됐는지"는 충분히 전달된다.
- 2~3명 소규모 팀에서 모듈 겹침이 적다면, 이것만으로 지식 단절의 대부분이 해결된다.

**Simple에서 구조적으로 손실되는 것**:

1. **과정의 손실**: auto-memory는 Claude가 자체 판단으로 결론 위주로 압축한다. "CORS는 vite proxy로 해결"은 기록되지만, "먼저 nginx를 시도했는데 WebSocket 호환 문제로 실패, 다음 CORS 헤더 직접 설정했는데 preflight 캐싱 이슈 발생, 최종적으로 vite proxy로 갔다"는 기록되지 않는다. B의 Claude가 같은 문제를 만났을 때 "vite proxy가 답"은 알지만 "nginx를 왜 쓰면 안 되는지"는 모른다.
2. **실시간성 부재**: MEMORY.md push는 session end에 일어나므로, A가 auth 모듈을 리팩토링하는 중에 B가 같은 영역 작업을 시작해도 인지 불가.
3. **다형성 감지 불가**: 두 개발자의 MEMORY.md를 합쳐서 주입할 뿐, "A는 보안, B는 성능 관점으로 같은 모듈을 다루고 있다"는 능동적 감지/고지가 없다.
4. **Attribution 모호성**: 합쳐진 memory에서 "이 지식이 누구의 어떤 맥락에서 나온 건지" 추적 불가.

**결론: Simple은 Overmind의 "충분히 좋은 v0"다.** 실제 시작점은 MEMORY.md push/pull + skill 치환이 맞다. Overmind의 가치는 이 Simple 위에 과정 기록, 다형성 감지, 실시간 signal을 **점진적으로 쌓아올릴 수 있는 확장 경로가 설계되어 있다**는 데 있다.

---

## 3. Overmind 아키텍처 설계

### 3.1 설계 철학

**각 작업 주체(인간의 로컬 Claude이든 자율 에이전트이든)가 서로 다른 개체이지만, local memory + others memory × N을 계속적으로 sync함으로써, 마치 단일 Claude가 사고를 종합해 답변/분석/과정/결론을 도출할 수 있도록 한다.**

이것은 아키텍처의 변경이 아니라 **sync의 빈도와 범위**에 대한 운영 조건이다. 각 Claude는 물리적으로 별개이되, 동일한 memory pool을 참조하는 상태를 유지한다.

### 3.2 핵심 차별점: 결론 흡수가 아닌 과정 흡수

Overmind가 기존 접근법(Simple 포함)과 결정적으로 다른 지점은, **백그라운드에서 결정된 결론을 흡수하는 것이 아니라 의사결정 과정 전체를 흡수하는 것**이 목표라는 점이다.

기존 접근법은 "A가 OAuth2를 선택했다"라는 결론만 B에게 전달한다. Overmind는 "A가 먼저 JWT refresh token rotation을 시도했고, 복잡도 과다로 기각했고, 세션 기반을 검토했지만 stateless 요구사항과 충돌해서 기각했고, 최종적으로 OAuth2 + PKCE를 채택했다"라는 **사고 과정 전체**를 B의 Claude가 보유하도록 한다.

이 과정이 B에게 도달해야 하는 이유: B의 Claude가 "캐시 레이어를 auth에 추가하자"는 지시를 받았을 때, A의 과정을 알고 있는 Claude만이 "A가 stateless 요구사항 때문에 세션 기반을 기각한 전적이 있는데, 캐시 레이어가 사실상 세션 상태를 만드는 것과 같으니 이 부분을 먼저 확인하는 게 좋겠다"고 사전에 고지할 수 있다. **결론만 알았다면 이 판단은 불가능하다.**

### 3.3 특수 케이스: Claude Code 속도에 의한 브랜치 괴리

Claude Code의 작업 속도와 볼륨은 인간 단독 개발 대비 방대하다. 이것이 팀 협업에서 새로운 유형의 문제를 만든다.

**시나리오**: 개발자 A가 feature-auth 브랜치에서 Claude Code로 인증 시스템 전체 리팩토링을 진행한다. Claude의 속도 덕분에 하루 만에 수십 개 파일이 변경되고, 관련 테스트, 마이그레이션 스크립트, 문서까지 생성된다. 동시에 개발자 B는 feature-cache 브랜치에서 성능 최적화를 진행 중이다.

**기존 Git 워크플로우의 한계**: 양쪽 브랜치 모두 Claude가 빠르게 작업을 진행하므로, 코드베이스 괴리가 기존 인간 페이스보다 훨씬 빠르게 확대된다. merge가 1~2일만 지연되어도, 충돌 지점이 기하급수적으로 늘어난다. 더 중요한 것은 **코드 충돌보다 맥락 충돌**이다 — A의 Claude는 "인증은 이제 OAuth2 기반"이라는 전제로 사고하고, B의 Claude는 "인증은 여전히 JWT 기반"이라는 전제로 캐시 레이어를 설계하고 있을 수 있다.

**Overmind가 이 문제를 완화하는 방식**:

- Signal axis를 통해 A의 브랜치 작업 내용(파일 변경, intent, 과정)이 수시로 B의 Claude에게 전달된다. B의 Claude는 "A가 인증 체계를 전면 교체하고 있다"는 사실을 **merge 전에 이미 인지**한다.
- B의 Claude가 캐시 레이어 설계 시 "A의 OAuth2 전환이 진행 중이므로, JWT 전제의 캐시 키 구조가 곧 무효화될 수 있다"고 유저에게 선제적으로 고지한다.
- merge 시점이 아닌 **작업 중에** 괴리를 감지하므로, 큰 충돌을 사전에 방지하거나 최소화할 수 있다.

이것은 Claude Code의 속도가 만들어낸 문제를 Claude의 인지 능력으로 해결하는 구조다. 인간 개발자 간의 구두 소통("나 지금 auth 건드리고 있어")을 Claude가 자동으로 대행하는 것이며, Claude Code 특유의 방대한 작업량 환경에서만 발생하는 문제에 대한 해법이다.

### 3.4 핵심 해자(Moat): 문제 발생 이전의 사전 차단

Overmind의 가장 결정적인 가치는 **문제가 발생하기 전에 사전 차단**할 수 있다는 점이다. 이것이 단순한 지식 공유를 넘어서는 핵심 해자다.

**대표 시나리오: 환경 설정 문제의 사전 차단**

프로젝트의 백엔드 서비스 A-B-C 간 설정값 처리가 main에 미처 반영되어 있지 않거나, `.env` 로컬 설정을 개별 유저가 직접 해야 하는 상황을 가정한다. 이런 문제는 코드 리뷰에서도 잡히지 않고, 문서화도 누락되기 쉬우며, 각 개발자가 독립적으로 부딪히고 독립적으로 해결하는 패턴이 반복된다.

기존 워크플로우에서의 흐름:

1. 유저 B가 서비스 B를 로컬에서 띄울 때 연결 오류 발생
2. B의 Claude Code로 디버깅 시작 — 로그 분석, 설정 파일 탐색, 시도/실패 반복
3. 30분~1시간 후 원인 발견: `.env`에 `SERVICE_A_INTERNAL_URL` 설정이 필요했음
4. B의 auto-memory에 해결법 기록, push
5. **다음 날 유저 A가 동일한 문제를 마주침 → 같은 삽질 반복**

Overmind 워크플로우에서의 흐름:

1. 유저 B가 문제를 마주치고, Claude Code로 해결. 과정(시도한 것, 실패 원인, 최종 해결법)이 memory에 기록되고 push
2. **유저 A가 해당 문제를 마주치기 이전에**, 관련 작업을 위한 프롬프팅 과정에서 sync가 발생
3. A의 Claude는 B의 memory를 이미 보유하고 있으므로, A가 서비스 B 관련 작업을 시작하는 순간 — 에러가 발생하기 전에 — **"서비스 B 로컬 실행 시 `.env`에 `SERVICE_A_INTERNAL_URL` 설정이 필요합니다. B 개발자가 이전에 이 이슈를 해결한 이력이 있습니다."** 라고 사전 고지

핵심 차이는 **타이밍**이다. 기존 방식은 "문제 발생 → 검색/기억 → 해결"이지만, Overmind는 "sync된 memory 기반 → 관련 작업 진입 시 사전 체크 → 문제 발생 자체를 방지"한다. A는 에러 메시지를 한 번도 보지 않고 설정을 완료한다.

이 패턴은 환경 설정에만 국한되지 않는다. 특정 API의 숨겨진 제약사항, 특정 라이브러리의 버전 호환 이슈, 특정 배포 환경의 주의점 등 — **한 명이 삽질로 발견한 모든 암묵지가 팀 전체의 사전 방어막**이 된다. 이것이 "결론 공유"로는 불가능하고 "과정 공유"여야만 가능한 이유다. 결론("`.env`에 이 값을 넣어라")만 있으면 Claude가 사전 고지의 적절한 타이밍을 판단할 맥락이 부족하지만, 과정("서비스 B 실행 시 연결 오류가 났고, 원인이 이 설정 누락이었다")까지 있으면 Claude가 "지금 유저가 서비스 B를 다루려 하고 있으니, 이 시점에 알려야 한다"고 판단할 수 있다.

### 3.5 적용 범위: 인간 개발자에서 자율 에이전트까지

본 문서의 시나리오는 주로 "인간 개발자 A, B"를 기준으로 서술하고 있으나, 이는 설명의 편의를 위한 것이며 아키텍처의 제약 조건이 아니다.

**복수 자율 에이전트 시나리오:**

Claude Code의 agent teams, subagent, 또는 외부 오케스트레이션(Claude-Flow 등)에서 복수 에이전트가 각각 독립된 task를 수행하는 경우를 가정한다. 예: Agent-A가 백엔드 API 구현, Agent-B가 프론트엔드 통합, Agent-C가 테스트 작성을 각각 독립적으로 진행.

이 경우에도 Overmind의 핵심 가치는 동일하게 적용된다:

- **과정 공유**: Agent-A가 API 스키마를 3번 변경한 과정을 Agent-B가 알면, 프론트엔드 연동 시 최종 스키마뿐 아니라 "왜 이전 스키마가 기각됐는지"를 인지할 수 있다.
- **사전 차단**: Agent-C가 테스트 작성 중 특정 엔드포인트의 인증 요구사항을 발견하면, Agent-B가 같은 엔드포인트를 호출하기 전에 lesson이 전파된다.
- **다형성 감지**: Agent-A와 Agent-B가 같은 데이터 모델에 대해 서로 다른 전제로 작업하고 있을 때, 결론 통합(merge) 이전에 괴리를 감지.

**인간과 에이전트의 차이:**

| 측면 | 인간 개발자 | 자율 에이전트 |
|------|-----------|-------------|
| 지시 | 유저가 프롬프트로 지시 | 오케스트레이터 또는 자체 판단 |
| 고지 대상 | 인간 유저에게 자연어로 고지 | 에이전트 자체의 context에 injection |
| 세션 패턴 | 장시간 대화형 세션 | 짧은 task 단위 실행, 빈번한 세션 |
| Push 빈도 | SessionEnd 위주 | Task 완료마다 (더 빈번) |
| Pull 타이밍 | Session start + Hook | Task 시작마다 (더 빈번) |

에이전트 시나리오에서는 push/pull 빈도가 높아지므로, Overmind 서버의 서머리/lesson 추출 역할이 더 중요해진다. 에이전트는 context window 효율성에 민감하므로, raw JSONL보다 lesson 수준의 압축된 전달이 기본이 된다.

### 3.6 2-Axis 설계

Overmind의 동기화는 두 축으로 구성된다.

두 축 모두 **JSONL 이벤트**로 통합 전송되며, `type` 필드로 구분된다.

**Axis 1: Signal (실시간 작업 이벤트)**

- type: `change`, `correction` (진행 중)
- 특성: 실시간, 휘발적
- 목적: "지금 뭘 하고 있는지" 교환
- 내용: 작업 중인 파일, 변경 intent, 에러 발생, 시도/실패/correction 과정

**Axis 2: Knowledge (누적 지식)**

- type: `decision`, `discovery`, `correction` (완료)
- 특성: 수시 동기화, 누적적
- 목적: "뭘 배웠는지" 동기화
- 내용: 트러블슈팅 기록, 패턴 발견, 설계 결정 과정과 이유

두 축의 구분은 서버 저장 구조가 아닌 **클라이언트 측 해석 시 적용**된다. 서버에는 모두 동일한 JSONL 형태로 저장되며, pull하는 클라이언트가 자기 맥락에서 "이건 지금 당장 관련된 signal인가, 배경 knowledge인가"를 판단한다.

### 3.7 Relay의 실체: Overmind Server

**Overmind server는 로컬 또는 사내에서 직접 구동하는 HTTP(MCP) 서버다.** 외부 SaaS가 아닌, 팀의 작업 집약을 위한 자체 운영 서버.

**아키텍처:**

```
Overmind Server (로컬/사내)
├── REST API / MCP endpoint
├── JSONL Store (file-based 또는 SQLite)
│   ├── events/                    # 전체 이벤트 로그
│   │   ├── dev_a/*.jsonl
│   │   └── dev_b/*.jsonl
│   └── index/                     # scope 기반 인덱스 (빠른 pull용)
└── Housekeeping (경량: TTL, 중복 제거, 인덱싱)

클라이언트 (각 로컬 Claude Code)
├── Hook → push (JSONL 이벤트 생성 → 서버로 전송)
├── Hook/Skill → pull (서버에서 JSONL 수신)
└── 로컬 Claude → 수신 JSONL 해석 → 자기 memory로 정제
    (가치 판단, 다형성 감지, 사전 차단 모두 여기서 수행)
```

**Push 내용: JSONL (프롬프트/인터랙션 로그)**

Push되는 내용은 MEMORY.md(이미 가공된 결론)가 아니라 **JSONL 형태의 원시 프롬프트/인터랙션 로그**에 가깝다. 가치 있는 메모리로 정제하는 것은 각 클라이언트의 몫이므로, 서버에는 가공되지 않은 구조화된 로그를 push한다.

이 설계의 핵심: **로직을 최대한 클라이언트로 위임한다.** 서버는 raw data store이고, 지능은 edge(각 로컬 Claude)에 집중된다.

Push 트리거:

- SessionEnd: 세션 중 발생한 주요 인터랙션 로그를 push
- Correction 감지: 트러블슈팅 과정 전체를 즉시 push
- 주요 파일 구조 변경: 모듈 추가/삭제/리팩토링 시

```jsonl
{"id":"evt_001","user":"dev_a","ts":"2026-03-26T14:30:22+09:00","type":"correction","prompt":"서비스B 연결 오류 해결","files":["src/config/env.ts"],"process":["nginx proxy 시도→WebSocket 미지원","CORS 헤더 직접 설정→preflight 캐싱 이슈","vite proxy 설정으로 해결"],"result":"vite.config.ts에 proxy 추가"}
{"id":"evt_002","user":"dev_a","ts":"2026-03-26T15:12:00+09:00","type":"decision","prompt":"인증 방식 전환","files":["src/auth/oauth2.ts","src/auth/jwt.ts"],"process":["JWT refresh rotation 검토→복잡도 과다","세션 기반→stateless 충돌","OAuth2+PKCE 채택"],"result":"OAuth2 기반으로 전환"}
{"id":"evt_003","user":"dev_a","ts":"2026-03-26T15:45:00+09:00","type":"discovery","prompt":".env 설정 누락 발견","files":[".env.example"],"process":["서비스B 실행 시 ECONNREFUSED","SERVICE_A_INTERNAL_URL 미설정 확인"],"result":".env에 SERVICE_A_INTERNAL_URL 필요"}
```

```
POST /api/memory/push
Content-Type: application/x-ndjson

(JSONL body — 복수 이벤트를 한 번에 push)
```

**Pull 흐름 (서버 → 클라이언트):**

다른 Claude Code 클라이언트가 Overmind server로부터 JSONL 로그를 pull하는 시점:

1. **요청 프롬프트가 다른 변경사항에 영향을 받을 때**: 유저의 프롬프트가 기존 코드 수정/연동에 해당하면, Hook(PreToolUse)에서 관련 영역의 타 유저 로그를 pull
2. **Session start**: 세션 시작 시 마지막 pull 이후의 전체 변경분을 pull
3. **Hook 트리거**: 특정 파일 영역 작업 진입 시, 해당 영역의 타 유저 로그를 선택적 pull

```
GET /api/memory/pull?since=2026-03-26T10:00:00&scope=src/auth/*
→ JSONL 응답: 해당 scope 관련, since 이후의 모든 유저 이벤트 로그
```

**Pull 후 클라이언트 측 처리 (핵심):**

수신된 JSONL을 **로컬 Claude가 해석하여 자기 memory로 정제**한다. 이것이 "로직을 클라이언트로 위임"의 실체다.

- JSONL의 각 이벤트를 읽고, 현재 작업 맥락과의 관련성을 판단
- 관련성 높은 이벤트는 local auto-memory에 흡수 (Claude의 memory 정리 스킬 활용)
- 다형성 감지: 같은 scope에 다른 intent의 이벤트가 있으면 유저에게 고지
- 사전 차단: 현재 작업 영역에 대한 correction/discovery 이벤트가 있으면 선제 고지

서버가 "이건 중요하다"고 판단하는 것이 아니라, **각 클라이언트의 Claude가 자기 맥락에서 중요도를 판단**한다. 같은 JSONL을 받아도 A의 Claude와 B의 Claude가 다른 항목을 중요하게 여길 수 있으며, 이것이 정상이다.

**서버 측 Housekeeping (경량):**

서버의 역할은 raw JSONL의 **일시적 보관**과 경량 관리에 한정된다. Overmind server는 데이터를 장기 보관할 필요가 없다. 가치 있는 memory로의 정제와 보존은 각 클라이언트의 몫이며, 서버는 클라이언트 간 이벤트가 전달될 때까지의 중간 버퍼에 가깝다.

- 일시 저장: O — JSONL 이벤트를 수신하여 TTL 기간 동안 보관
- 인덱싱: O — scope(파일 경로) 기반 인덱스로 pull 시 빠른 필터링
- TTL 관리: O — 오래된 이벤트의 자동 만료 (기본값 예: 7~14일)
- 중복 제거: O — 동일 event id의 중복 push 방지
- 서머리 생성: O — pull 요청 시 lesson/summary 수준의 요약 제공 (경량 LLM 또는 추출 로직)
- 장기 보관: X — 불필요. 가치 있는 지식은 이미 각 클라이언트의 local memory에 흡수됨
- 고도 판단: X — 설계 결정, 코드 판단, 가치 평가는 클라이언트 Claude의 몫

**단계적 데이터 전략과 서버 측 서머리:**

Overmind의 데이터 전략은 두 방향으로 진화한다.

**Push 측 (클라이언트 → 서버): 전부 보낸다.**
클라이언트는 JSONL 이벤트를 가공 없이 전부 push한다. 필터링이나 요약은 push 시점에서 하지 않는다. raw 데이터가 서버에 있어야 다양한 pull 요청에 대응할 수 있기 때문이다.

**Pull 측 (서버 → 클라이언트): 서머리/핵심만 전달한다.**
다른 클라이언트가 pull할 때, 서버가 raw JSONL을 그대로 내려주는 것이 아니라 **서머리 또는 핵심(lesson)만 추출하여 전달**한다. 이 서머리 생성에 고도의 LLM은 불필요하다 — 경량 모델이나 간단한 추출 로직으로 충분하며, 이것이 Overmind 서버에 위임하기 적합한 이유다.

```
클라이언트 A → push (raw JSONL 전체)
                    ↓
            Overmind Server
            ├── raw 저장 (TTL 기간)
            └── 서머리 생성 (경량 LLM / 추출 로직)
                    ↓
클라이언트 B ← pull (서머리 + 핵심 lesson)
```

**초기 운영 시**: lesson 수준의 고수준 확정 데이터만 relay하는 것으로 시작한다. "이 설정이 필요하다", "이 방식은 안 된다", "이걸로 결정했다" 같은 소규모 확정 결론. 이것만으로도 사전 차단 해자의 핵심 가치는 확보된다.

**점진적 확대**: 운영하면서 lesson → process(과정 포함 서머리) → full context(필요시 raw 접근)으로 pull 응답의 상세도를 확대한다.

```
GET /api/memory/pull?scope=src/auth/*&detail=lesson
→ 핵심 결론만: "인증은 OAuth2+PKCE로 전환됨. JWT는 기각됨."

GET /api/memory/pull?scope=src/auth/*&detail=summary
→ 과정 포함 서머리: "JWT→세션→OAuth2 순서로 검토. stateless 요구사항이 핵심 제약."

GET /api/memory/pull?scope=src/auth/*&detail=full
→ raw JSONL 전체
```

**이 방식의 이점:**

- `claude mcp add overmind http://내부서버/mcp`로 각 클라이언트에서 즉시 연결 가능
- 기존 Claude Code의 MCP 생태계와 자연스럽게 통합
- 로컬/사내 네트워크에서만 접근 가능하므로 보안이 자연스럽게 확보
- git repo에 `.overmind/` 디렉토리를 넣을 필요 없이, 서버가 memory의 single source of truth

### 3.8 Memory 병합과 Conflict-free 설계

**Conflict는 구조적으로 발생할 수 없다.** 이것은 설계 결정이다.

각 개발자의 계정/세션 기반 memory pull을 최대한 유지하면서 병합하되, 유효한 내용을 남기는 처리는 **로컬 Claude의 memory 정리 스킬을 그대로 활용**한다. 이 방식에서 conflict가 발생하지 않는 이유:

1. **Memory는 코드가 아니다.** 코드는 같은 줄을 두 사람이 다르게 수정하면 conflict가 발생하지만, memory는 "A가 알게 된 것"과 "B가 알게 된 것"이 동시에 존재할 수 있다. 서로 모순되더라도 그것은 conflict가 아니라 다형성이다.
2. **병합의 주체가 Claude다.** git merge처럼 텍스트 레벨에서 기계적으로 합치는 것이 아니라, Claude가 두 memory를 읽고 의미를 이해한 후 정리한다. "A는 nginx가 안 된다고 했고, B는 nginx로 해결했다"가 동시에 들어오면, Claude는 이를 충돌로 처리하는 것이 아니라 "환경/조건에 따라 다를 수 있는 지식"으로 병합하고, 필요시 유저에게 다형성으로 고지한다.
3. **각 유저의 memory는 개별 파일로 존재한다.** `memory-sync/user_a/`와 `memory-sync/user_b/`는 물리적으로 별개이므로 파일 레벨 conflict 자체가 불가능하다. 통합 `project-memory/`로의 병합은 Claude의 memory 정리 스킬이 수행하며, 이 과정은 append + deduplicate + summarize이지 two-way merge가 아니다.

### 3.9 Scope: Repo-scoped

Overmind는 개별 사용자의 Claude 전역 내용을 통합하는 것이 **아니다.** 특정 프로젝트 repo 단위의 연결을 지향한다.

- `.overmind/` 디렉토리가 프로젝트 repo 안에 존재
- 해당 repo에서 작업하는 개발자들의 Claude 인스턴스만 연결
- 다른 프로젝트의 메모리와는 완전히 격리

### 3.10 저장 구조

**Overmind server 측 (JSONL Store):**

```
overmind-server/
├── data/
│   ├── events/
│   │   ├── dev_a/
│   │   │   ├── 2026-03-26.jsonl    # A의 일별 이벤트 로그
│   │   │   └── 2026-03-27.jsonl
│   │   └── dev_b/
│   │       ├── 2026-03-26.jsonl
│   │       └── 2026-03-27.jsonl
│   │
│   └── index/
│       └── scope.json              # 파일 경로 → 이벤트 ID 매핑
│
├── server.js (또는 server.py)      # REST/MCP endpoint
└── config.json                     # 프로젝트 scope, 유저 목록, TTL 설정
```

**클라이언트 측 (각 개발자의 로컬):**

```
project-repo/
├── .claude/                        # 기존 Claude Code 구조 (변경 없음)
│   ├── settings.json
│   ├── settings.local.json         # overmind MCP 서버 연결 설정
│   └── rules/
│
├── CLAUDE.md                       # 기존 프로젝트 지침 (변경 없음)
└── src/
```

git repo에는 `.overmind/` 디렉토리가 존재하지 않는다. Memory의 single source of truth는 Overmind server이며, 각 클라이언트는 MCP를 통해 접근한다.

### 3.11 멀티 에이전트 통신 패턴과 Overmind의 위치

현재 멀티 에이전트 시스템에서 사용되는 주요 통신 패턴은 4가지다:

| 패턴 | 방식 | 대표 사례 | 특성 |
|------|------|----------|------|
| Message Passing | 에이전트 간 직접 메시징 | Claude Code Agent Teams (inbox JSONL) | 명시적, 추적 가능, 발신자가 수신자를 지정 |
| Blackboard | 공유 칠판에 게시, 관련 에이전트가 자율적 참여 | LbMAS, Hearsay-II | 비동기, 탈중앙, 에이전트가 자기 관련성 판단 |
| Shared File System | 파일 읽기/쓰기로 간접 조율 | Claude Code subagent (디스크 task 파일) | 단순, 기존 인프라 활용, 실시간성 부족 |
| Event-Driven (pub/sub) | 이벤트 발행/구독 | Kafka 기반 MAS, Webhook | 비동기, 느슨한 결합, 확장 용이 |

**Overmind의 현재 위치**: Blackboard(서버에 이벤트 게시, 클라이언트가 pull로 자율 소비) + Event-Driven(Hook 기반 자동 push)의 하이브리드.

**빠진 것**: Message Passing. Hook 기반 push는 "자동 이벤트 발행"이지, "A가 B에게 긴급히 알려야 할 것"을 의도적으로 보내는 채널이 아니다.

### 3.12 명시적 공유 Push (Explicit Broadcast)

Hook에 의한 자동 push 외에 **의도적으로 lesson/변경사항을 공유하는 명시적 push 기능**이 필요하다.

**필요한 시나리오:**

1. **마스터 에이전트의 설계 변경 전파**: 마스터가 API 스키마를 변경했는데, 이미 이전 스키마 기준으로 구현 중인 프론트엔드/백엔드 에이전트에게 즉시 알려야 함
2. **구현 중 발견한 긴급 수정사항**: 프론트엔드 에이전트가 인증 엔드포인트의 미문서화된 제약을 발견, 같은 엔드포인트를 사용하는 백엔드 에이전트에게 바로 공유해야 함
3. **인간 개발자의 의도적 지식 공유**: "이 삽질 결과를 팀 전체가 알아야 해"라고 판단하여 명시적으로 push

**구현 방식:**

Hook 기반 자동 push와 동일한 JSONL 포맷을 사용하되, `type`에 `broadcast` 또는 `urgent` 필드를 추가:

```jsonl
{"id":"evt_010","user":"master_agent","ts":"...","type":"broadcast","priority":"urgent","scope":"src/api/*","message":"API 스키마 v2로 변경됨. user_id가 uuid에서 string으로 변경. 이전 스키마 기준 구현은 수정 필요.","related_files":["src/api/schema.ts"]}
```

**클라이언트 측 수신:**

- `priority: urgent`인 broadcast는 일반 lesson보다 높은 우선순위로 다음 pull 시 최상단에 포함
- 활성 세션이 있는 클라이언트에게는 SSE/polling으로 즉시 전달 (Phase 3)
- 수신한 Claude가 현재 작업 맥락과 대조하여 즉시 유저/에이전트에게 고지

**MCP tool 노출:**

```
POST /api/memory/broadcast
{
  "user": "master_agent",
  "priority": "urgent",
  "scope": "src/api/*",
  "message": "API 스키마 v2로 변경. user_id: uuid → string",
  "related_files": ["src/api/schema.ts"]
}
```

이를 Claude Code의 MCP tool로 노출하면, 에이전트나 인간 유저가 자연어로 "이 변경사항을 팀에 알려줘"라고 지시하여 명시적 broadcast를 트리거할 수 있다.

**Hook push vs Explicit push 비교:**

| 구분 | Hook 기반 자동 push | 명시적 broadcast |
|------|-------------------|-----------------|
| 트리거 | Hook 이벤트 (SessionEnd, PostToolUse 등) | 유저/에이전트의 의도적 지시 |
| 내용 | 자동 캡처된 이벤트 로그 | 의도적으로 구성한 메시지 |
| 우선순위 | 일반 | urgent 가능 |
| 용도 | 과정/결론의 자동 기록 | 긴급 변경사항, 설계 결정 전파 |
| 수신 타이밍 | 다음 pull 시 | 다음 pull 시 최상단 (urgent 우선 정렬) |

두 종류의 push가 동일한 JSONL 포맷으로 Overmind 서버에 저장되므로, 서버 측 처리는 동일하다. 차이는 `type`과 `priority` 필드뿐이며, 클라이언트가 pull 시 priority 기반 정렬로 urgent를 먼저 처리한다.

**구현 가능성: Claude Code 플러그인 조합으로 완전히 구현 가능**

Overmind의 전체 push/pull/broadcast 파이프라인은 Claude Code의 기존 확장 메커니즘(Hook + Skill + MCP + Plugin)의 조합으로 구현할 수 있다.

```
overmind-plugin/
├── .claude-plugin/
│   └── plugin.json
├── .mcp.json                  # Overmind MCP 서버 연결 설정
├── hooks/
│   └── hooks.json             # 자동 push (SessionEnd) / pull (SessionStart, PreToolUse)
├── skills/
│   └── overmind-broadcast/    # 명시적 broadcast — Claude가 자동 매칭
│       └── SKILL.md
└── commands/
    └── broadcast.md           # /overmind:broadcast 슬래시 커맨드
```

각 컴포넌트의 역할:

- **MCP 서버** (`.mcp.json`): Overmind 서버의 `push`, `pull`, `broadcast` 도구를 Claude의 tool로 노출. 실제 데이터 전송 채널.
- **Hook** (`hooks.json`): `SessionStart`에서 자동 pull, `SessionEnd`에서 자동 push, `PreToolUse`(Write/Edit 매칭)에서 관련 영역 pull. Hook 반환값의 `systemMessage`로 urgent broadcast를 Claude context에 직접 injection 가능.
- **Skill** (`overmind-broadcast/SKILL.md`): description에 "팀에 공유", "변경사항 알림", "긴급 전파" 등의 키워드를 설정하면, 유저가 "이 변경사항을 팀에 알려줘"라고 말할 때 Claude가 자동으로 skill을 로드하고 MCP `broadcast` tool을 호출.
- **Slash Command** (`broadcast.md`): `/overmind:broadcast "API 스키마 v2로 변경"` 같은 명시적 트리거.

**비동기 실시간 수신(SSE/WebSocket)은 불필요하다.** Claude Code 자체가 세션 간 실시간 push를 네이티브로 지원하지 않으므로, Hook 트리거 시점(SessionStart, PreToolUse 등)에서의 pull이 수신의 자연스러운 타이밍이다. "다음 Hook 발생 시 urgent 우선 수신"이면 실용적으로 충분하며, SSE/polling 레이어를 추가하는 복잡성 대비 이점이 없다.

### 3.13 Signal 설계

#### 캡처 대상 (Hook 기반)

Claude Code hook이 잡을 수 있는 이벤트 중 실질적으로 의미있는 signal:

| Hook Event | 캡처 대상 | 예시 |
|------------|----------|------|
| PreToolUse (Write/Edit) | 파일 구조 변경 | 새 모듈 추가, 디렉토리 재구성 |
| PostToolUse | 작업 결과 + 과정 | 시도 → 실패 → correction → 최종 선택 |
| Notification (commit) | 설계 결정 intent | commit message에서 추출한 intent |
| Error/Correction 감지 | 트러블슈팅 이력 | "wrong", "error", "failed" 감지 시 |
| SessionStart/End | 세션 맥락 | 시작/종료 시 상태 스냅샷 |

#### JSONL 이벤트 구조

```jsonl
{"id":"evt_001","user":"dev_a","ts":"2026-03-26T14:30:22+09:00","type":"decision","prompt":"인증 방식 전환","files":["src/auth/oauth2.ts","src/auth/jwt.ts"],"process":["JWT refresh rotation 검토→복잡도 과다로 기각","세션 기반 검토→stateless 충돌로 기각","OAuth2+PKCE 채택"],"result":"OAuth2 기반으로 전환"}
{"id":"evt_002","user":"dev_a","ts":"2026-03-26T15:45:00+09:00","type":"correction","prompt":"서비스B 연결 오류","files":["src/config/env.ts",".env.example"],"process":["ECONNREFUSED 발생","SERVICE_A_INTERNAL_URL 미설정 확인"],"result":".env에 SERVICE_A_INTERNAL_URL 필요"}
{"id":"evt_003","user":"dev_a","ts":"2026-03-26T16:10:00+09:00","type":"discovery","prompt":"CORS 이슈 해결","files":["vite.config.ts"],"process":["nginx proxy→WebSocket 미지원","CORS 헤더 직접 설정→preflight 캐싱","vite proxy로 해결"],"result":"vite.config.ts proxy 설정 추가"}
```

각 줄이 독립 이벤트이며, `type` 필드로 분류된다:

- `decision`: 설계 결정 (대안 검토 후 선택)
- `correction`: 에러 발생 → 해결 과정
- `discovery`: 새로 발견한 사실/제약사항
- `change`: 파일 구조 변경 (모듈 추가/삭제)

### 3.14 클라이언트 측 수신 처리

서버에서 pull한 JSONL 이벤트를 **로컬 Claude가 자기 맥락에서 해석하여 처리**하는 것이 Overmind 지능의 핵심이다. 서버는 raw data를 제공하고, 가치 판단은 전적으로 클라이언트에서 수행한다.

#### 처리 분류

각 로컬 Claude가 수신한 JSONL 이벤트를 현재 작업 맥락과 대조하여 분류:

1. **즉시 관련 — 사전 차단 대상**: 현재 작업 영역과 직접 관련된 correction/discovery 이벤트 → 유저에게 즉시 고지
   - 예: "서비스 B 관련 작업 시작 → 다른 유저의 `.env` 설정 누락 해결 이벤트 발견 → 사전 고지"
2. **배경 지식 — local memory 흡수**: 직접 관련은 아니지만 유용한 지식 → auto-memory에 반영
   - 예: "A가 발견한 CORS 해결법 → 나중에 필요할 수 있으므로 memory에 기록"
3. **다형성 감지 — 고지 대상**: 같은 scope에 다른 intent의 이벤트 → 유저에게 다형성 고지
   - 예: "같은 모듈에 대해 A는 보안, 나는 성능 관점으로 접근 → 검토 제안"
4. **무관 — 무시**: 현재 맥락과 관련 없는 이벤트 → 처리하지 않음

이 판단의 주체가 로컬 Claude라는 것이 핵심이다. 같은 JSONL을 받아도 현재 `src/auth/`를 작업 중인 Claude와 `src/api/`를 작업 중인 Claude는 다른 이벤트를 중요하게 여기며, 이것이 정상이다.

### 3.15 다형성(Polymorphism) 감지 및 Reconciliation

#### 트리거 조건

"같은 파일 경로 또는 같은 모듈에 대해 서로 다른 user의 signal이 존재하는데, intent가 의미적으로 다를 때"

이는 받는 쪽 Claude가 signal을 ingestion하면서 자연어 비교 판단으로 수행할 수 있다 — 벡터 유사도 같은 무거운 인프라 없이도 가능하다.

#### Claude의 역할: 판단이 아니라 고지

다형성을 감지했을 때 Claude가 "A 방식이 맞다"는 판정을 내리지 않는다. 대신:

- "같은 영역에 대해 서로 다른 맥락이 존재한다"는 사실을 유저에게 알린다
- 충돌 가능 지점을 구체적으로 제시한다
- 함께 reconcile할 기회를 제공한다

#### 고지 예시

> "auth 모듈에 대해 A 개발자는 보안 강화 관점(JWT → OAuth2 전환)으로 작업했고, 현재 세션에서는 성능 최적화 관점(세션 캐시 레이어 추가)으로 접근하고 있습니다. A가 stateless 요구사항 때문에 세션 기반을 기각한 전적이 있는데, 캐시 레이어가 사실상 세션 상태를 만드는 것과 유사합니다. 이 부분을 먼저 확인하는 게 좋겠습니다."

이런 수준의 고지는 **결론만 알았다면 불가능**하다. A의 과정(JWT 검토 → 세션 기반 검토 → 기각 이유 → OAuth2 선택)을 알고 있기 때문에 가능한 판단이다.

---

## 4. 구현 전략

### 4.1 Phase 1: Overmind MCP Server PoC

경량 MCP 서버를 로컬/사내에 구동하고, 2인 개발 환경에서 기본 push/pull 사이클을 검증.

**구현 요소:**

- Overmind MCP 서버 (Node.js 또는 Python, 단일 파일 수준)
- REST API: `POST /api/memory/push`, `GET /api/memory/pull`
- Memory Store: file-based JSON (SQLite는 Phase 2에서 검토)
- Claude Code plugin: Hook(SessionStart/SessionEnd/PostToolUse)에서 push/pull 호출
- Skill 1개: pull한 memory를 현재 세션 컨텍스트에 injection + 다형성 감지
- 각 클라이언트: `claude mcp add overmind http://localhost:PORT/mcp`

**초기 전략**: lesson 수준(확정된 고수준 결론)만 relay하는 것으로 시작. 서머리 없이 핵심 결론만 pull 응답에 포함.
**장점**: MCP 생태계 자연 통합, git repo 오염 없음, 최소 데이터로 사전 차단 해자 검증
**검증 목표**: 2인이 동일 프로젝트 작업 시, B가 A의 lesson을 사전에 인지하는지 확인

**Phase 1 Go/No-Go 판정 기준:**

Phase 1의 성공 여부는 기술적 구현 완료가 아니라 다음 두 가지 조건의 충족으로 판단한다:

1. **의도적 lesson 전파가 실제로 이루어지는가**: A가 push한 lesson이 B의 작업 맥락에서 실제로 표면화되는지. "push는 됐는데 B가 pull해도 Claude가 무시한다"면 전파가 이루어진 것이 아니다. 전파의 정의는 B의 Claude가 A의 lesson을 인지하고 유저에게 고지하거나, 자기 판단에 반영하는 것까지를 포함한다.
2. **피드백 점수가 확보되는가**: 전파된 lesson에 대해 relevance_score 또는 prevented_error 등의 피드백 신호가 실제로 기록되는지. 피드백 없이는 Overmind가 "전달은 했는데 유용했는지 모르는" 상태에서 벗어날 수 없으며, 선순환 구조(서머리 품질 ↑ → relevance ↑ → 사전 차단 ↑)가 작동하지 않는다.

두 조건이 모두 충족되면 Phase 2로 진행. 하나라도 미충족 시, 해당 조건의 실패 원인을 분석하여 설계를 수정한 후 Phase 1을 재실행한다.

### 4.2 Phase 2: Housekeeping + 과정 캡처 강화

Phase 1의 기본 push/pull이 검증된 후, 서버 측 memory 정리와 과정 캡처 메커니즘을 강화.

**구현 요소:**

- 서버 측 서머리 생성: push된 raw JSONL에서 lesson/summary를 자동 추출 (경량 LLM 위임)
- Pull 응답에 `?detail=lesson|summary|full` 파라미터 지원
- 과정 캡처: Hook(PostToolUse)에서 correction 감지 시 process_log 포함 JSONL push
- CLAUDE.md 또는 .claude/rules/에 "과정을 상세히 기록" 지시 추가로 이벤트 품질 향상
- SQLite로 JSONL Store 이관 (scope 인덱싱, TTL 관리)

**장점**: 사전 차단 해자 본격 활성화, context window 효율화
**검증 목표**: 과정 기록이 실제로 사전 고지 품질을 높이는지 확인

### 4.3 Phase 3: Broadcast + 다형성 감지 + 자기평가 고도화

명시적 broadcast 기능과 서버 측 다형성 사전 탐지, 피드백 루프를 본격 가동.

**구현 요소:**

- 명시적 broadcast: MCP tool + Skill + Slash Command로 urgent 전파
- 다형성 감지 로직 고도화: 서버 측에서 "같은 scope, 다른 intent" 사전 탐지 → pull 응답에 경고 포함
- 자기평가: 피드백 점수(relevance_score, prevented_error) 축적 → 메타 리포트 자동 생성
- 팀 규모 확장 테스트 (3인 이상, 또는 복수 자율 에이전트)

**장점**: Hook 기반 자동 sync + 의도적 broadcast의 이중 채널 확보
**비동기 실시간(SSE/WebSocket)은 불필요** — Hook 트리거 시점의 pull로 실용적으로 충분

### 4.4 구현 우선순위

| 우선순위 | 항목 | 이유 |
|---------|------|------|
| P0 | Signal JSON 스키마 정의 | 모든 후속 작업의 기반 |
| P0 | SessionEnd memory diff push | 가장 기본적인 Knowledge sync |
| P1 | SessionStart pull + context injection | 수신 측 기본 동작 |
| P1 | 다형성 감지 로직 (자연어 비교) | Overmind의 핵심 가치 |
| P2 | 수시 signal push (PostToolUse hook) | Signal axis 활성화 |
| P2 | Correction 감지 시 즉시 push | 트러블슈팅 공유 가속 |
| P3 | MCP 서버 구현 | 실시간성 강화 |
| P3 | Project-memory auto-merge | 팀 공유 지식 자동 축적 |

---

## 5. 테스트, 자기평가, 가시성

### 5.1 로컬 테스트 및 목업 전략

Overmind MCP 서버를 실제 복수 개발자 없이도 로컬에서 단독 테스트할 수 있어야 한다. 현재 MCP 생태계는 이를 위한 도구를 이미 제공하고 있다.

**단위 테스트: FastMCP in-memory client**

Python FastMCP(v2.0+)의 `Client(server)` 패턴으로 네트워크/프로세스 오버헤드 없이 in-memory 클라이언트-서버 연결이 가능하다. 핵심은 **동일 서버에 복수 Client 인스턴스를 연결하여 복수 개발자를 시뮬레이션**할 수 있다는 점이다.

```python
async with Client(overmind_server) as dev_a, Client(overmind_server) as dev_b:
    # A가 트러블슈팅 결과를 push
    await dev_a.call_tool("push", {"user": "dev_a", "type": "correction", ...})
    # B가 관련 영역 pull → A의 lesson이 포함되는지 검증
    result = await dev_b.call_tool("pull", {"scope": "src/auth/*"})
    assert "SERVICE_A_INTERNAL_URL" in result
```

`asyncio.gather`로 동시 push/pull의 race condition도 테스트 가능.

**대화형 디버깅: MCP Inspector**

`npx @modelcontextprotocol/inspector node ./server.js`로 React 기반 웹 UI(localhost:6274)를 띄워, push/pull 도구를 수동으로 호출하고 JSON-RPC 응답을 실시간 확인. CI/CD 파이프라인에서는 CLI 모드(`--method tools/list`, `--tool-name`)로 스크립트 기반 assertion 가능.

**Plugin 테스트: --plugin-dir 플래그**

`claude --plugin-dir ./overmind-plugin`으로 marketplace 설치 없이 플러그인을 로컬 로딩. `/reload-plugins` 명령으로 hot-reload. Claude Agent SDK에서는 `plugins: [{ type: "local", path: "./my-plugin" }]`로 프로그래밍 방식 테스트도 가능.

**Hook 단독 테스트**

Claude Code의 shell 기반 Hook은 stdin으로 JSON을 받고 exit code로 통신하므로, 테스트 데이터를 직접 pipe하여 단독 실행 가능:

```bash
echo '{"tool_name":"Write","tool_input":{"file_path":"src/auth/oauth2.ts"}}' | ./overmind-push-hook.sh
```

Agent SDK의 프로그래밍 방식 Hook은 일반 async 함수이므로, SDK 런타임 없이 직접 호출하여 단위 테스트 가능.

**목업 시나리오 설계**

1인 개발 환경에서 Overmind의 핵심 가치를 검증하는 목업 시나리오:

1. **사전 차단 시나리오**: dev_a가 `.env` 설정 문제 해결 이벤트를 push → dev_b 클라이언트가 해당 서비스 영역 pull → lesson에 설정 정보가 포함되는지 확인
2. **다형성 감지 시나리오**: dev_a가 "보안 관점" intent로 auth 변경 push → dev_b가 "성능 관점" intent로 같은 scope pull → 서버 응답에 다형성 경고가 포함되는지 확인
3. **서머리 품질 시나리오**: raw JSONL 5개를 push → `?detail=lesson`과 `?detail=summary`로 각각 pull → 서머리가 핵심을 정확히 추출하는지 비교

### 5.2 Push/Pull 데이터의 가치 자기평가

**의도적 lesson 전파가 잘 이루어지고 피드백 점수가 확보되는지가 Overmind의 핵심 성공 기준이다.**

"전파"란 단순히 서버에 데이터가 도착한 것이 아니라, 다른 클라이언트의 Claude가 해당 lesson을 **실제로 인지하고 반영**하는 것까지를 의미한다. 그리고 그 반영이 유용했는지의 피드백이 기록되어야 시스템이 개선될 수 있다. 이 두 가지가 없으면 Overmind는 "뭔가 전달은 했는데 도움이 됐는지 모르는" 블랙박스에 머문다.

피드백 루프의 구체적 구현:

**동기적 관련성 체크 (Pull 직후)**

`PostToolUse` Hook에서 pull된 memory를 수신한 직후, 경량 모델로 관련성을 1~5점으로 평가:

```jsonl
{"event":"pull_eval","ts":"...","scope":"src/auth/*","pulled_count":3,"relevance_score":4,"used_in_task":true}
```

이 평가 결과를 다시 Overmind 서버로 push하면, 서버는 어떤 이벤트가 실제로 유용했는지의 통계를 축적할 수 있다.

**회고적 품질 평가 (Session End)**

`SessionEnd` Hook(또는 `Stop` 이벤트)에서 세션 전체를 회고하여, 주입된 공유 memory 중 실제로 참조된 항목과 무시된 항목을 분류:

```jsonl
{"event":"session_retrospective","ts":"...","pulled_items":["evt_001","evt_002","evt_003"],"actually_used":["evt_001"],"ignored":["evt_002","evt_003"],"prevented_error":true}
```

`prevented_error: true`는 사전 차단이 실제로 발생했음을 의미하며, Overmind의 핵심 해자를 정량적으로 측정하는 지표가 된다.

**피드백 반영 루프**

Self-RAG 패턴에서 착안: 각 이벤트에 `relevance_score`가 누적되면, pull 응답 시 높은 점수의 이벤트를 우선 포함하고 낮은 점수의 이벤트는 후순위로 밀거나 TTL을 단축할 수 있다. Mem0의 criteria retrieval 방식처럼 `code_relevance`, `recency`, `task_specificity` 등의 가중치 차원을 정의하여 검색 점수를 조정하는 것도 가능.

이 피드백 루프의 핵심: **서머리 품질이 좋아지면 relevance_score가 올라가고, 올라가면 더 자주 전달되고, 그러면 더 많은 사전 차단이 발생하는 선순환 구조.**

### 5.3 Overmind의 자기평가와 가시성 확보

Overmind 서버가 "레포의 정신 공유 과정"에서 자기 효과성을 스스로 평가하고, 그 결과를 가시적으로 남겨야 한다.

**메타 리포트: Overmind의 자기평가**

서버가 주기적으로(예: 일 1회, 또는 요청 시) 자기평가 리포트를 생성:

```json
{
  "report_date": "2026-03-26",
  "period": "24h",
  "metrics": {
    "total_pushes": 47,
    "total_pulls": 23,
    "unique_users": 3,
    "context_hit_rate": 0.78,
    "avg_relevance_score": 3.8,
    "prevented_errors": 5,
    "polymorphism_detected": 2,
    "summary_accuracy": 0.85,
    "events_expired_by_ttl": 12,
    "events_never_pulled": 8
  },
  "insights": [
    "src/auth/ 영역에 가장 많은 cross-user 이벤트 집중 (18건)",
    "dev_b의 correction 이벤트가 가장 높은 reuse율 (4.2회/건)",
    "dev_c가 push한 이벤트의 35%가 한 번도 pull되지 않음 → noise 가능성"
  ]
}
```

**핵심 KPI**

| KPI | 정의 | 목표 |
|-----|------|------|
| Context hit rate | pull 요청 중 유용한 이벤트가 포함된 비율 | >80% |
| Sync latency | 이벤트 생성 → 다른 클라이언트 수신까지 시간 | <5분 |
| Prevented error rate | 사전 차단이 발생한 세션 비율 | 추적 (baseline 확보) |
| Knowledge reuse ratio | 복수 클라이언트가 소비한 이벤트 / 전체 이벤트 | >50% |
| Events never pulled | TTL 만료까지 한 번도 pull되지 않은 이벤트 비율 | <30% |
| Summary accuracy | 서머리가 원본의 핵심을 정확히 포함하는 비율 | >85% |
| Polymorphism detection rate | 실제 다형성이 감지되어 고지된 횟수 | 추적 |

**가시성 확보 방법**

- **Overmind dashboard**: 서버에 `/api/report` 엔드포인트를 두어, 브라우저에서 메타 리포트 확인. 간단한 HTML 페이지로 충분.
- **Overmind MCP tool**: `overmind-report`를 MCP tool로 노출하면, 각 개발자의 Claude Code 세션에서 "Overmind 현황 보여줘"로 직접 조회 가능.
- **자동 경고**: events_never_pulled 비율이 임계치를 넘으면, 다음 pull 응답에 "최근 push된 이벤트의 35%가 활용되지 않고 있습니다. push 기준을 조정할 필요가 있을 수 있습니다." 같은 메타 메시지를 포함.
- **OpenTelemetry 연동**: push/pull 각 operation을 OTEL span으로 기록하면, Langfuse 또는 Arize Phoenix 같은 오픈소스 LLM observability 플랫폼으로 트레이싱 가능. 자체 구현 부담 없이 기존 인프라 활용.

**자기평가의 궁극적 가치**: Overmind가 자기 효과성을 측정하고 기록함으로써, "이 시스템이 실제로 팀의 coordination tax를 줄이고 있는가?"라는 질문에 데이터로 답할 수 있게 된다. coordination tax — 명시적 동기화 활동(메시지, 맥락 수집, 중복 작업 발견)에 소요되는 시간 — 가 감소하면 Overmind가 작동하고 있는 것이고, 감소하지 않으면 어떤 observability 인프라도 의미 없다.

---

## 6. 해결해야 할 과제


### 6.1 Relay의 분석 역할 — 해결됨

~~현재 설계에서 relay는 순수 중계만 수행한다.~~ → **v1.3에서 해결**: relay가 로컬 Claude의 memory 정리 스킬과 동일한 방식으로 memory housekeeping을 수행하는 것으로 결정. 중복 제거, 요약, 유효성 판단을 relay 단에서 처리하여, 각 로컬 Claude는 이미 정리된 memory를 수신한다. (§3.6 참조)

### 6.2 Conflict Resolution — 해결됨 (구조적으로 발생 불가)

~~동일 시점에 여러 개발자의 Claude가 project-memory를 수정할 경우의 merge 전략.~~ → **v1.3에서 해결**: memory는 코드가 아니므로 conflict 개념 자체가 적용되지 않는다. 각 유저의 memory는 개별 파일로 격리되어 파일 레벨 conflict이 불가능하며, project-memory로의 통합은 Claude의 memory 정리 스킬(append + deduplicate + summarize)이 수행한다. 모순되는 내용은 conflict가 아닌 다형성으로 처리한다. (§3.7 참조)

### 6.3 Noise vs. Signal — 부분 해결

~~어떤 이벤트가 팀에게 의미있는 signal인지를 서버가 판별해야 한다.~~ → **v1.5에서 부분 해결**: 로직을 클라이언트로 위임한 설계에서, noise 판별의 주체가 서버가 아닌 **pull하는 클라이언트의 Claude**가 되었다. 서버는 raw JSONL을 보관하고, 각 클라이언트가 자기 맥락에서 관련 없는 이벤트를 무시한다.

잔여 과제: push 시점의 필터링은 여전히 필요하다. 모든 keystroke를 push할 수는 없으므로, Hook 단에서 "이벤트로 만들 가치가 있는 인터랙션인지"의 최소 기준은 클라이언트 측 Hook/Skill에서 판단해야 한다. 초기에는 보수적으로 correction, decision, discovery, broadcast, 주요 change만 push하고 운영하며 조정.

### 6.4 Context Window 압박 — 부분 해결

~~팀원이 많아질수록 주입해야 할 memory가 늘어난다.~~ → **v1.5에서 부분 해결**: scope 기반 pull(`?scope=src/auth/*`)로 관련 영역의 이벤트만 수신하고, 수신 후에도 클라이언트 Claude가 현재 맥락과의 관련성을 판단하여 무관한 이벤트는 무시한다.

잔여 과제: 관련 scope 내에서도 이벤트 양이 context window를 초과할 수 있다. TTL로 오래된 이벤트를 만료시키고, 클라이언트 측에서 최근 N개만 처리하는 등의 추가 전략이 필요할 수 있다. PoC에서 실측 후 조정.

### 6.5 보안 및 프라이버시 — 부분 해결

~~`.overmind/` 디렉토리가 git repo에 포함되므로~~ → **v1.4에서 부분 해결**: Overmind server 방식으로 전환됨에 따라 git repo 오염 문제는 해소. 단, push 시 민감 정보(API key, 개인 설정 등)가 memory에 포함되지 않도록 클라이언트 측 필터링은 여전히 필요. 사내 네트워크에서만 접근 가능한 서버이므로 외부 노출 위험은 자연적으로 차단.

---

## 7. 결론

### 7.1 핵심 기여

본 연구는 Claude Code 환경에서 **복수의 독립적 작업 주체(인간 개발자 또는 자율 에이전트) 간 메모리 동기화**라는 미개척 영역에 대해, 기존 솔루션의 한계를 분석하고 Overmind라는 실현 가능한 아키텍처를 제안하였다. Overmind의 구조는 인간 개발자 협업에 국한되지 않으며, 복수 에이전트가 독립 작업 후 결론을 통합하는 모든 시나리오에 동일하게 적용된다.

Overmind의 본질은 아키텍처의 복잡성이 아니라 **sync의 빈도와 범위**에 있다. 각 Claude는 물리적으로 별개 개체이되, `자기 memory + 팀원 memory × N`을 지속적으로 동기화함으로써, 어떤 유저가 질문하든 해당 Claude가 전체 팀의 과정과 맥락을 포함한 상태에서 사고하고 답변한다.

### 7.2 핵심 차별점: 과정 흡수

기존 모든 접근법(Supermemory, Claude Sync, 나아가 MEMORY.md push/pull Simple 접근법 포함)은 **백그라운드에서 결정된 결론을 흡수**하는 모델이다. Overmind의 결정적 차이는 **의사결정 과정 전체를 흡수**하는 것이 목표라는 점이다. 결론만 알면 "뭘 해야 하는지"는 알지만 "뭘 하면 안 되는지"는 모른다. 과정을 알면 둘 다 안다.

### 7.3 특수 가치: Claude Code 속도 환경

Claude Code의 방대한 작업량과 속도는 기존 Git 워크플로우에서 예상하지 못한 유형의 문제를 만든다. 별도 브랜치 작업이 인간 페이스보다 훨씬 빠르게 진행되어 코드베이스 괴리가 기하급수적으로 확대되며, merge 시점이 아닌 작업 중에 맥락 충돌을 감지해야 할 필요성이 커진다. Overmind는 Claude Code의 속도가 만들어낸 문제를 Claude의 인지 능력으로 해결하는 구조다. 인간 개발자 간의 구두 소통("나 지금 auth 건드리고 있어")을 Claude가 자동으로 대행한다.

### 7.4 핵심 해자: 사전 차단

Overmind의 가장 결정적인 해자는 **문제 발생 이전의 사전 차단**이다. 한 개발자가 삽질로 발견한 암묵지(환경 설정 이슈, API 제약사항, 라이브러리 호환 문제 등)가 과정 포함으로 공유되면, 다른 개발자의 Claude는 관련 작업 진입 시점에 에러가 발생하기 전에 선제적으로 고지할 수 있다. 기존 방식이 "문제 발생 → 검색 → 해결"인 반면, Overmind는 "sync된 memory → 관련 작업 진입 시 사전 체크 → 문제 발생 자체를 방지"한다. 이것은 결론만 공유해서는 불가능하고, 과정(어떤 상황에서 어떤 에러가 났는지)까지 공유되어야만 Claude가 사전 고지의 적절한 타이밍을 판단할 수 있다.

### 7.5 기존 시도들과의 차이

1. **과정 공유**: 결론만이 아닌 시도 → 실패 → correction → 선택의 전체 과정을 공유한다.
2. **다형성 인지**: merge 후 코드는 하나이지만 intent가 다를 수 있음을 Claude가 감지하고, 유저에게 고지하며, 함께 reconcile할 기회를 제공한다.
3. **Self-hosted / Repo-scoped**: SaaS 의존 없이 프로젝트 repo 단위로 동작한다.
4. **Conflict-free + 지능 분산 설계**: push는 raw JSONL 전체, pull 시 서버가 서머리/핵심을 추출하여 전달 (경량 LLM). 고도 판단(다형성 감지, 사전 차단)은 클라이언트 Claude가 수행. 서버와 클라이언트가 역할을 분담.
5. **점진적 확장 경로**: Simple(MEMORY.md push/pull)에서 시작하여 과정 기록 → 다형성 감지 → 실시간 signal로 점진적으로 확장 가능한 설계.
6. **인간/에이전트 불문**: 인간 개발자 간 협업뿐 아니라, 복수 자율 에이전트의 병렬 작업 + 결론 통합 구조에서도 동일하게 작동하는 범용 설계.

### 7.6 최종 아티팩트 정의

본 프로젝트의 산출물은 **두 개의 독립 아티팩트**로 구성된다.

---

#### Artifact 1: Overmind (서버)

프로젝트 단위 메모리 중계 및 관리를 수행하는 self-hosted HTTP/MCP 서버.

**책임 범위:**

- JSONL 이벤트 수신(push) 및 일시 저장
- Scope 기반 인덱싱, TTL 관리, 중복 제거
- Pull 요청 시 서머리/lesson 추출 (`?detail=lesson|summary|full`)
- Broadcast 이벤트의 priority 기반 관리
- 메타 리포트 생성 (자기평가 KPI)
- `/api/report` 대시보드 엔드포인트

**기술 스택 (초기):**

- Node.js 또는 Python 단일 서버
- MCP 프로토콜 endpoint
- JSONL file-based store (Phase 2에서 SQLite 이관)
- 경량 LLM 또는 추출 로직 (서머리 생성용)

**인터페이스:**

```
POST /api/memory/push          # JSONL 이벤트 수신
GET  /api/memory/pull           # scope/detail/since 기반 조회
POST /api/memory/broadcast      # urgent 전파
GET  /api/report                # 메타 리포트 / 대시보드
MCP  endpoint                   # Claude Code에서 tool로 직접 호출
```

**배포:** 로컬 또는 사내 네트워크. `claude mcp add overmind http://HOST:PORT/mcp`로 클라이언트 연결.

---

#### Artifact 2: Overmind Plugin (클라이언트)

각 Claude Code 인스턴스에 설치되어, Overmind 서버와의 push/pull/broadcast를 자동화하는 Claude Code 플러그인.

**책임 범위:**

- Hook 기반 자동 push (SessionEnd, PostToolUse/correction 감지)
- Hook 기반 자동 pull (SessionStart, PreToolUse — 관련 영역 진입 시)
- Pull된 JSONL/lesson의 로컬 해석 → local memory 흡수, 다형성 감지, 사전 차단 고지
- 명시적 broadcast (Skill 자동 매칭 + Slash Command)
- 피드백 점수 기록 (relevance_score, prevented_error) → 서버로 재push
- Overmind 현황 조회 (MCP tool `overmind-report`)

**구조:**

```
overmind-plugin/
├── .claude-plugin/
│   └── plugin.json              # 플러그인 메타데이터
├── .mcp.json                    # Overmind 서버 MCP 연결
├── hooks/
│   └── hooks.json               # SessionStart/End, PreToolUse 훅
├── skills/
│   ├── overmind-broadcast/      # "팀에 알려줘" 자동 매칭
│   │   └── SKILL.md
│   ├── overmind-pull/           # 관련 영역 memory 조회
│   │   └── SKILL.md
│   └── overmind-report/         # 현황 리포트 조회
│       └── SKILL.md
├── commands/
│   └── broadcast.md             # /overmind:broadcast
├── scripts/
│   ├── push.sh                  # Hook에서 호출하는 push 스크립트
│   └── pull.sh                  # Hook에서 호출하는 pull 스크립트
└── README.md
```

**설치:**

```bash
# 마켓플레이스에서 설치
/plugin marketplace add overmind/overmind-plugin
/plugin install overmind-plugin

# 또는 로컬 테스트
claude --plugin-dir ./overmind-plugin
```

---

#### 두 아티팩트의 관계

```
Overmind Plugin (클라이언트)          Overmind (서버)
┌─────────────────────┐            ┌──────────────────────┐
│ Hook → push.sh ─────┼── POST ──→│ /api/memory/push     │
│                      │            │   JSONL store        │
│ Hook → pull.sh ←────┼── GET ───←│ /api/memory/pull     │
│   → Claude 해석     │            │   서머리/lesson 추출  │
│   → local memory    │            │                      │
│                      │            │                      │
│ Skill → broadcast ──┼── POST ──→│ /api/memory/broadcast│
│ /overmind:broadcast  │            │   priority 관리      │
│                      │            │                      │
│ MCP tool ←──────────┼── MCP ───→│ MCP endpoint         │
└─────────────────────┘            └──────────────────────┘
각 Claude Code 인스턴스에 1개씩       프로젝트당 1개 (공유)
```

**Go/No-Go 기준**: (1) 의도적 lesson 전파가 실제로 이루어지는가 (2) 피드백 점수가 확보되는가. 두 조건이 모두 충족되어야 Phase 2로 진행.

---

## 부록 A: 용어 정의

| 용어 | 정의 |
|------|------|
| Overmind | 본 연구에서 제안하는 분산 메모리 동기화 아키텍처의 코드명 |
| Signal (JSONL Event) | Axis 1에 해당하는 실시간 작업 이벤트. JSONL 형태의 구조화된 로그로 push (Hook 기반) |
| Knowledge | Axis 2에 해당하는 auto-memory diff (누적적 지식) |
| Relay (Overmind Server) | 로컬/사내에서 직접 구동하는 HTTP(MCP) 서버. Memory의 single source of truth. Push/pull API 제공 + Claude 기반 housekeeping 수행 |
| 다형성 (Polymorphism) | 같은 코드 영역에 대해 서로 다른 intent가 공존하는 상태 |
| Reconciliation | 다형성을 감지한 후 유저와 함께 해소하는 과정 |
| Process log | 결론뿐 아니라 시도, 실패, 이유를 포함한 작업 과정 기록 |
| 사전 차단 (Preemptive Block) | 한 작업 주체의 과정 memory를 기반으로, 다른 작업 주체가 동일 문제를 마주치기 전에 선제적으로 고지하는 패턴. Overmind의 핵심 해자. |
| 작업 주체 (Agent) | Overmind에서 독립적으로 작업하는 단위. 인간 개발자 또는 자율 에이전트(Claude Code 세션, CI/CD 에이전트 등). 문서에서 "개발자"는 이 개념으로 확장 가능. |

## 부록 B: 장기 비전 — Overmind의 이름값

현재 Overmind server는 JSONL 중계소에 가깝다. 저장은 일시적이고, 지능은 edge(클라이언트)에 집중되어 있으며, 서버 자체는 "사고"하지 않는다. 이것은 PoC와 초기 운영에 적합한 설계이지만, Overmind라는 이름에 걸맞으려면 최종적으로 서버가 중앙 집중적 분석(centralized analysis) 능력을 가져야 한다.

**장기 과제: Overmind의 중앙 분석 레이어**

- **Repo-level analysis**: Overmind server가 프로젝트 repo를 직접 분석하여, 각 클라이언트가 push한 JSONL과 실제 코드 변경을 대조. 코드와 memory 간의 괴리 감지, 아키텍처 수준의 패턴 추출, 프로젝트 전체의 기술 부채 추적.
- **Cross-user insight**: 개별 클라이언트가 자기 맥락에서만 판단하는 현재 구조의 한계를 보완. 서버가 전체 유저의 이벤트를 종합하여 "팀 전체적으로 이 영역에 혼란이 집중되고 있다", "이 모듈에 대해 3명의 개발자가 서로 다른 전제로 작업하고 있다" 같은 팀 레벨 인사이트를 도출.
- **Proactive guidance**: 현재는 클라이언트가 pull해야 정보를 받지만, 서버가 중앙 분석을 통해 "이 유저는 지금 이 정보를 알아야 한다"고 판단하여 능동적으로 push하는 구조. 진정한 Overmind — 하이브 마인드의 중추가 되는 것.

이것은 현재 설계의 확장이지 대체가 아니다. 클라이언트 위임 모델은 그대로 유지하되, 서버 측에 분석 레이어를 점진적으로 추가하는 방향. JSONL이 이미 구조화되어 흐르고 있으므로, 이 위에 분석을 올리는 것은 자연스러운 진화다.

---

## 부록 C: 참조 프로젝트

| 프로젝트 | URL | 비고 |
|---------|-----|------|
| Supermemory | github.com/supermemoryai/supermemory | Team memory 참조 |
| Claude-Flow (ruflo) | github.com/ruvnet/ruflo | Hive Mind 패턴 참조 |
| Claude Cognitive | github.com/GMaN1911/claude-cognitive | Multi-instance 상태 공유 참조 |
| Claude Sync | github.com/renefichtmueller/claude-sync | 디바이스 간 동기화 참조 |
| Claude Code Memory Docs | code.claude.com/docs/en/memory | 네이티브 메모리 구조 참조 |
| Anthropic Memory Tool API | platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool | 공식 메모리 도구 참조 |
