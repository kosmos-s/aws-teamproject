# GitHub 저장소를 Orca에서 사용하기

대상: https://github.com/kosmos-s/aws-teamproject

## 에이전트 작업 지침
루트 `AGENTS.md`에 프로젝트 목표·현재 상태·개발/보안 규칙·검증 기준을 둔다. Codex는 작업 경로의 AGENTS.md를 읽는다. `CLAUDE.md`는 Claude Code 호환을 위해 같은 파일을 import한다. 새 worktree에도 Git으로 함께 전달된다.

- Codex 공식: https://learn.chatgpt.com/docs/agent-configuration/agents-md
- Claude Code 공식: https://code.claude.com/docs/en/memory

이 파일들은 API 키·GitHub 권한·AI 로그인 자체를 대신하지 않는다. 기존 세션에서는 새 지침을 다시 읽게 하거나 저장소 루트에서 새 세션을 시작한다.

## Linux 원격 Orca에 등록
Orca를 실행하는 일반 사용자로 실행한다. 설치된 버전의 CLI 가이드를 먼저 확인한다.

```bash
orca-ide skills get orca-cli --json
git clone https://github.com/kosmos-s/aws-teamproject.git "$HOME/projects/aws-teamproject"
cd "$HOME/projects/aws-teamproject"
orca-ide repo add --path "$PWD" --json
git remote -v
git status --short --branch
```

이미 폴더가 있으면 덮어쓰지 말고 원격과 수정 상태부터 확인한다. `scripts/register-orca-project.sh`는 기존 체크아웃을 보존하며 등록한다. 공개 HTTPS clone에는 GitHub 토큰이 필요 없다.

Orca 사이드바의 **aws-teamproject**에서 기본 worktree를 선택한다. 새 기능은 별도 worktree/브랜치로 작업한다. 기존 `kosmos-demo`는 설치 검증용 예제다.

## 첫 작업 프롬프트
```text
AGENTS.md, README.md, STATUS.md, docs/course-review.md를 읽고 프로젝트를 이어서 진행해.
git status와 실제 파일부터 확인하고 진행 중인 작업을 보존해.
주제는 EC2 한 대의 Orca 기반 팀 개발환경과 공개 운영 포털이야.
미완료인 포털/API/DB/스토리지를 작은 단위로 구현하고 테스트해.
기존 AWS 배포와 새로운 공개 웹 서비스의 완료 상태를 구분해.
추가 비용·인증·권한이 필요한 단계는 실제 변경안과 비용을 준비한 뒤 알려줘.
AI 로그인은 사용자 요청 전까지 보류해.
```

## 인증 상태 구분
공개 clone/프로젝트 등록, GitHub push, AI 에이전트 로그인은 별도다. 서버에서 push하려면 사용자 본인이 해당 서버의 새 GitHub 인증을 완료해야 한다. PC의 기존 토큰은 복사하지 않는다. 저장소와 가이드 추가만으로 쓰기 권한이나 AI 인증이 생기는 것은 아니다.

실제 프로필·자원 식별자는 Git 제외 로컬 설정에서 관리한다. 다른 PC에서 이 파일이 없다고 기존 인증 파일을 가져오지 않는다.
