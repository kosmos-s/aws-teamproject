# 배포 기록과 재접속

작업일: 2026-11-10 KST. 계정 식별자와 인스턴스 ID는 Git에서 제외한 `.local/deployment.json`에만 보관한다.

## 소프트웨어
- Ubuntu Server 24.04 LTS, x86_64, Canonical 공식 AMI.
- Orca `1.4.255`, [고정 릴리스](https://github.com/stablyai/orca/releases/tag/v1.4.255).
- amd64 deb SHA-256: `6df53f4f6c919fd1f10dfe3511940934acc940a7754eb1b0e896d2c62e4add5a`.
- 설치 시 다운로드 파일을 GitHub Release API의 digest와 대조한다. 직접 소스 빌드나 무검증 최신 설치 스크립트는 사용하지 않는다.
- 공식 Windows Session Manager plugin 1.2.896.0, Amazon Web Services 서명 Valid 확인. 프로젝트의 `vendor/` 내부에만 풀고 시스템 서비스나 전역 PATH는 변경하지 않았다.

## 설치
```powershell
.\scripts\provision.ps1
```
먼저 같은 Project 태그의 EC2 존재와 계정 FREE/ACTIVE 및 크레딧을 확인한다. 이미 배포된 상태에서 다시 실행하면 중복 EC2 생성 전 중단한다. 부분 실패 시에는 `.local`의 요청과 기존 프로젝트 역할/보안 그룹부터 조사하고, 무작정 재실행하지 않는다.

실행한 설치 코드는 `deploy/bootstrap.sh`. 자동 중지 타이머를 제일 먼저 설정한 뒤 시스템 패키지·2 GiB swap·Orca를 설치한다. 전용 `orca` 사용자의 lingering과 공식 `orca-ide serve service install`로 로그인 없이 구동한다. `--no-pairing`을 사용하는 서비스는 페어링 링크를 로그에 출력하지 않는다. 최초 loopback 바인드의 페어링 거절을 확인하고, 공식 지원 구성인 `--bind 0.0.0.0 --refuse-public`으로 변경했다. SG 인바운드 0개와 SSM 터널을 계속 유지한다.

## 접속
프로젝트 폴더의 PowerShell에서:
```powershell
.\scripts\connect.ps1
```
터미널을 유지한 채 브라우저에서 `http://127.0.0.1:6768/`에 접속한다. 이는 EC2의 원격 서비스에 대한 SSM 터널이며 로컬 시제품이 아니다. SSM/IAM 인증과 Orca 클라이언트 페어링은 별도 계층이다.

AWS 로그인이 만료된 경우 사용자가 직접:
```powershell
aws login --profile kosmos-cloud
```
계정 비밀번호·키·세션을 소스에 복사하지 않는다. 다른 PC에서의 로그인은 해당 PC에서 별도 수행한다.

EC2 재부팅 또는 PC/SSM 연결 종료 후에는 `connect.ps1`을 다시 실행하고 웹 페이지를 새로고침한 뒤 기존 프로젝트를 선택한다. 이번 재부팅 시험에서는 재페어링 없이 기존 터미널 탭이 복원되고 새 명령을 실행했다. OS 재부팅 전의 실행 중 프로세스 자체가 계속 살아 있다는 뜻은 아니다.

## AI 인증 보류
Codex CLI 0.167.0을 서버에 공식 고정 릴리스로 설치하고 SHA-256을 검증했다. **사용자가 AI 로그인은 나중에 진행하기로 했으므로 현재 로그인이나 AI 요청을 시작하지 않았다.** 추후 본인이 서버의 `orca` 사용자에서 `orca-ide account add --agent codex`를 실행하고 새 브라우저 인증을 완료한다. [공식 헤드리스 인증 안내](https://learn.chatgpt.com/docs/auth)의 device authorization 방식이며, 장치 코드를 채팅으로 공유하지 않는다. 팀원의 계정/사용 정책은 별도 확인한다.

## 읽기 전용 상태 조회
```powershell
.\scripts\remote.ps1 -ScriptPath .\scripts\inspect-runtime.sh
```
`remote.ps1`은 신뢰한 로컬 운영자 스크립트를 AWS SSM Run Command로 실행하는 관리 도구다. 웹 API가 아니며 웹 입력을 받아 실행하지 않는다. SSM 명령/출력은 AWS 관리 기록에 남을 수 있으므로 비밀값을 명령 인수나 출력에 넣지 않는다. 페어링 결과 등은 `-SaveOutput`을 사용하여 Git 제외 경로에만 저장한다.

## 제한
Orca 서비스 활성, 브라우저 사용, 실제 AI 요청, 3인 접속, 재부팅 복구는 각각 검증한다. 클라이언트의 AI 로그인은 서버에 자동 적용되지 않는다. 서버용 AI 인증을 새로 진행해야 하며 사용자 PC/SER8의 토큰은 복사하지 않는다.
