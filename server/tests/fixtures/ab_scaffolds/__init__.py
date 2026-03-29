"""Scaffold registry for A/B tests.

Each scaffold module exposes:
  SCAFFOLD_FILES: dict[str, str]
  SHARED_PROMPT: str
  PIONEER_PROMPT: str  (optional — smarter prompt for pioneer agent)
  REPO_NAME: str
  REPO_ID: str
  MAX_TURNS: int
  create_scaffold(base_dir: Path) -> Path

Scaffold design criteria (새 scaffold 추가 시 필수 충족):
  - Overmind 효과를 정량 측정할 수 있어야 함
  - misleading error: 에러 메시지 ≠ 실제 원인
  - cross-file 의존성: 단일 파일 수정으로 해결 불가
  - 누적 수정: A→B→C 순서 의존 또는 상호 배타 제약
  - 단순 반복 패턴 금지: LLM이 혼자 풀 수 있는 문제는 가치 없음
"""
from . import nightmare, branch_conflict

# Active scaffolds — Overmind 효과 측정 가능
SCAFFOLDS: dict = {
    "nightmare": nightmare,
    "branch_conflict": branch_conflict,
}

# Deprecated scaffolds — Overmind 효과 없음, 참고용으로만 보존
# from . import simple, multistage
# from . import complex as complex_
# DEPRECATED_SCAFFOLDS = {"simple": simple, "multistage": multistage, "complex": complex_}
