# 배포 기록과 재접속

작업일: 2026-11-10 KST. 계정 식별자와 인스턴스 ID는 Git에서 제외한 운영자 전용 상태 파일에만 보관한다.

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


## 공개 운영 포털 추가 배포
공개 진입 경로는 80/443이며 80은 HTTPS로 리다이렉트한다. Orca 6768과 SSH 인바운드는 열지 않았다.
`app/`, `requirements.lock`, `deploy/portal-install.sh`와 systemd 단위는 `/opt/kosmos-portal`에 배포했다. 별도 비관리자 kosmos-portal 사용자와 loopback 8000을 사용한다.
`/etc/kosmos-portal.env`는 root 0600이며 systemd EnvironmentFile로 읽는다. URL에 & 등이 포함되므로 이 파일을 셸 source로 실행하지 않는다.
승인된 첫 RDS/S3 생성 코드는 `scripts/provision-portal.py`. 실행 전 기존 운영자 전용 상태 파일과 AWS 자원을 반드시 확인한다. 부분 생성 후 무작정 재실행하지 않는다.
서버 초기 설정은 `deploy/portal-configure.py`, 실제 데이터 검증은 `deploy/verify-portal.py`. 초기 설정은 새 DB 전용으로, 운영 중 반복 실행하지 않는다. DB 초기화용 SSM 읽기 권한은 설치 후 제거했다.
Nginx 설정은 deploy/portal-nginx.conf의 도메인을 대체해 사용하고 Certbot으로 인증서를 적용했다. 최초 webroot 인증은 전환 시점의 challenge 경로 404로 실패했으며, 명시적 challenge 경로와 Nginx 플러그인 적용 후 발급·외부 HTTPS 검증에 성공했다.
서비스 재시작 후 RDS·S3 유지와 별도 복구 검증을 재실행했다. 포털 계정 정보는 공개 Git에 올리지 않는다. 운영 명령과 복구는 docs/portal-operations.md를 따른다.


## Orca·Webmin 통합 후속 작업
[연결 검증 기록](orca-access-verification.md)에 실제 확인 범위, 미검증 항목과 로컬 준비 변경을 구분했다. 기존 종료 예약을 유지하며 사용자 요청으로 서버는 재시작하지 않는다.


## 팀 운영 추가 기능 (2026-11-11, 로컬)
[팀 운영 절차](team-operations.md)에 적용 순서와 미적용 항목을 기록했다. 추가 유료 AWS 자원이나 알림 서비스를 생성하지 않았다. 로컬 구현·검증은 운영 배포/메일 발송/2FA 등록과 구분한다.

## 2026-11-11 배포 갱신
사용자 승인에 따라 기존 EC2/RDS를 재가동하고 091ca9c 릴리스를 적용했다. DB 시작을 기다리는 동안 앱을 멈추고, RDS available 확인 뒤 테이블 반영과 서비스 시작을 수행했다. 초기 자원 생성 스크립트나 DB 초기화는 재실행하지 않았다. EIP 1개를 기존 EC2에 연결했고 DNS A 레코드 변경은 운영자에게 전달했다. EIP 상태/주소는 운영자 전용 상태 파일에 보관한다. 재실행 전 이 파일과 AWS describe-addresses를 먼저 확인해 중복 할당하지 않는다.
승인된 종료 시각은 2026-11-11 13:47:23 KST다. EC2/RDS 각각 AWS Scheduler와 서버 타이머를 확인했으며 운영 시간을 늘리지 않았다. DNS를 우회한 TLS 검증과 일반 DNS 접속 성공은 구분한다.

## 2026-11-11 강의 시연 추가 검증
사용자 추가 승인으로 ALB와 CloudFront/별도 비공개 S3 OAC를 실제 배포했다. ALB healthy·/health 200, CloudFront Deployed·HTTPS 200, S3 원본 403을 확인했다. 정상 DNS로 포털/Orca 연결, 공개 Orca 터미널 실행과 파일 저장·원본 복구, 로그아웃 후 활성 WebSocket 1008 종료(0.02초)를 검증했다. ALB/CloudFront 시연 자원은 오늘 13:47 종료 후 정리한다. [구성·검증·정리 범위](course-demo.md)

## 최종 확인 — 2026-11-11 13:51 KST
- 승인된 종료 시각에 EC2 stopped 확인, RDS도 stopped 확인. 운영 시간을 연장하지 않았다. 현재 공개 포털/Orca/Webmin은 중지 상태다.
- EC2 중지 후에도 EIP 연결과 동일 주소가 유지됨을 AWS에서 확인했다. 중지 후 재시작 시험까지 추가 수행하지는 않았다.
- 시연 ALB, target group, 전용 SG, CloudFront distribution, OAC, 별도 정적 S3 버킷은 각각 명시적인 NotFound/404 응답으로 삭제 확인했다. 기존 RDS/EBS/첨부·백업 S3/EIP는 보존했다.
- 일회성 Scheduler 예약은 실행 후 모두 사라졌고, 이번에 만든 두 임시 Scheduler IAM 역할과 인라인 정책도 제거했다.
- RDS 자동 재시작 예정은 2026-11-18 13:50:51 KST로 조회됐다. 중지 상태에서도 저장 비용이 남으며, 재시작 이후에는 컴퓨팅 비용이 다시 발생한다. 최종 삭제나 운영 연장은 별도 결정이 필요하다.
- EIP는 중지 중에도 $0.005/시간(30일 약 $3.60)이 남는다. EBS/RDS 저장·기존 S3도 별도다. 최종 청구액이나 크레딧 잔액은 실시간 추정과 구분한다.

## 이력 UI 갱신
app/templates/index.html, app/static/app.js, app/static/style.css만 체크섬 검증 후 교체했다. 교체 전 서버의 해당 파일을 별도 보존했다. 템플릿과 정적 파일은 요청 시 읽으므로 서버 서비스 재시작 없이 반영했다. CSS/JS URL에 변경 버전을 붙여 기존 캐시가 남지 않도록 했다. 기존 운영 종료 예약과 DB는 변경하지 않았다.


## 2026-11-11 오후 배포 방식 (핫 배포)
변경된 파일만 묶어 SSM으로 보낸다. 서버의 기존 파일이 마지막 배포 커밋과 같은지 해시로 먼저 확인하고(다르면 중단), 백업 후 교체 → `python -c "import app.main"` → `systemctl restart kosmos-portal` → `/health` 확인. 실패하면 백업으로 자동 복구한다. 새 테이블은 포털 시작 시 `create_all`로 생기며 기존 테이블은 `ALTER` 하지 않는다.
관리자 Orca 연결은 `deploy/kosmos-orca-link.service/.timer`(20초)가 `deploy/orca-link-worker.py`를 root로 실행해 처리한다. 웹은 요청만 기록한다.

## 2026-11-12 개선안 배포 준비
새 테이블 9개와 채팅 복합 인덱스 2개를 추가한다. 기존 파일과 LF 기준 체크섬을 먼저 비교하고 다른 사람의 원격 변경이 있으면 중단한다. 배포 전 코드 백업, 신규 릴리스 의존성 확인, 서비스 계정으로 키 생성/스키마 이전, 분리된 복구 검증, /health 및 HTTPS 인증 거부 확인을 수행한다. TOTP 이전 때문에 파일만 되돌리는 롤백은 허용하지 않는다. 세부 조건은 [개선안](review-hardening.md)의 롤백 절차를 따른다. 서버 배포·main 병합·AWS 변경은 현재 사용자의 별도 확인 후 진행한다.

## PR #6 실제 반영과 재발 방지
사용자의 단계별 승인을 받고 main `37855ed`를 기존 서버에 반영했다. 앱 파일 전체 체크섬과 실제 백업/별도 복구를 검증했다. 새 패키지 설치에는 서비스 계정이 읽을 수 있는 022 umask를 사용해야 하며, 비밀 환경·키·백업은 0600을 유지한다. 스테이징 공개 코드 경로는 0755/0644로 설정한다. 셸 함수 내부 실패도 롤백으로 전파되도록 `set -E`를 사용한다. [실제 검증](verification.md)을 참고한다.

## 프로젝트 소유자·Deploy key 배포 준비 (2026-11-14)

현재 기능 브랜치에서만 준비했다. main 병합·서버 배포·AWS 변경은 각각 사용자 확인 후 진행한다. 새 유료 서비스 없이 기존 root Orca 연결 타이머를 재사용한다. 승인 후 앱 코드와 `deploy/orca-link-worker.py`, `app/repository_worker.py`, `deploy/kosmos-orca-link.service`를 함께 설치하고 서비스 유닛 변경을 다시 읽어야 한다. 앱 시작의 create_all이 새 메타데이터 테이블 4개를 추가한다. 기존 테이블 ALTER는 없다.

작업자는 고정 경로 잠금으로 중복 실행을 막고, Git/Orca를 공유 orca 계정의 제한된 환경에서 실행한다. 키 파일은 orca 전용 경로 0600, SSH 호스트 키는 공식 값으로 고정한다. 작업자 제한시간은 600초, 중단된 running 작업은 12분 후 실패 처리한다. GitHub 공개키 등록과 실제 push는 별도 수동 검증이다. 롤백 시 새 작업자 타이머부터 중지해 미처리 키 작업을 검토하고 이전 앱·작업자·유닛을 함께 복구한다. 키와 폴더를 자동 삭제하지 않는다. 새 백업 v4는 구버전 앱에서 바로 복원하지 말고 v4 지원 코드로 별도 빈 대상에 복원한다.

자세한 권한, 키 폐기, 복원 경계: [운영 안내](project-ownership.md).
