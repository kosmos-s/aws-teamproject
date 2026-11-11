# 최신 검증 안내 — 2026-11-11

아래는 초기 통합 시점의 기록이다. 후속 AWS 실행에서 공개 Orca 파일 저장·터미널 실행, 원본 복구, 실제 활성 WebSocket 로그아웃 종료(1008)를 검증했다. 새 Git 코드 백업도 서버의 별도 폴더에 복원해 커밋 원문과 비교했다. 상세 근거는 [강의 시연](course-demo.md)과 [최신 검증 기록](verification.md)을 우선한다. AI 로그인·실제 3인 동시 접속·서버 GitHub 쓰기 인증은 미완료다. 현재 운영 창은 STATUS.md를 확인한다.

## 초기 기록 (후속 검증 전)

# Orca·Webmin 연결 상태와 검증

2026-11-11 재개: 사용자 선택에 따라 서버 재시작 없이 로컬 작업만 수행한다. AWS 세션 만료로 현재 EC2/RDS 중지 상태는 미확인이다. 기존 자동 중지 예약은 변경하지 않았다.

## 이전 AWS 실행에서 확인한 결과
- 포털 인증 후 /orca/web-index.html에서 Orca 네이티브 UI 연결 성공, 팀 저장소 파일 탐색·README 소스 편집기 열기 확인.
- 익명 /orca/web-index.html은 401. Native E2EE 프레임은 변경하지 않고 고정 loopback WS로만 전달한다.
- 페어링 회전은 사용하지 않는다. 공식 CLI의 기존 미사용 offer를 재사용한다. 브로커의 Electron sandbox 오류는 NoNewPrivileges를 유지하고 설치된 Node/CLI 진입점 사용으로 해결했다.
- Webmin 2.670 공식 파일 SHA-256 검증·설치, 127.0.0.1:10000 바인딩 확인. 포털 관리자 검사와 Webmin 자체 로그인 필요.
- 별도 Webmin 계정으로 실제 HTTPS 로그인, sid 발급과 서비스 모듈 HTTP 200 확인. 서비스/프로세스/로그/설정 백업 모듈만 허용한다. Linux 비밀번호는 변경하지 않았다.
- Webmin 계정은 기존 Git 제외 로그인 파일에 추가해 암호화 전달했다. 전달용 임시 IAM 권한 제거를 확인했다.

## 로컬 검증
24개 통합 테스트: 인증·CSRF, 승인된 매핑, 익명/다른 Origin WS 거부, 활성 WS 로그아웃 종료, 지연된 upstream handshake 중 2초 이내 종료, Webmin 관리자 전용 검사 포함.
ECC 검토의 연결 초기화 중 로그아웃 지연 문제는 실패 회귀 테스트 후 수정했다. 현재는 로그아웃 이벤트로 즉시 취소하고, 0.5초 주기·조회 1초 제한으로 만료/DB 장애 시 차단한다. 단일 worker 구성이다.

## 아직 완료로 표시하지 않는 항목
- 공개 Orca에서 파일 편집 저장·실제 명령 출력 검증. 마지막 시도는 사용량 한도로 승인 검토가 중단되어 실행되지 않았다. 이전 편집 표시가 서버에 저장됐다는 근거는 없다. raw keyboard 입력으로 재검증하고 README의 검증용 공백·표시는 사용자 변경을 보존하며 정리해야 한다.
- 실제 배포 환경에서 로그아웃 후 이미 열린 Orca 연결 종료·다중 브라우저 동시 사용.
- Orca 프로젝트 코드의 S3 백업 → 별도 폴더 복구 → Orca에서 재실행. 기존 RDS/S3 논리 데이터 복구와 구분한다.
- 서버 GitHub 쓰기 인증/실제 push, AI 로그인, 3인 동시 접속.
- Webmin SID Secure/HttpOnly/SameSite 보완과 고정 설치 스크립트는 로컬 준비이며 마지막 AWS 검증 이후 추가 배포하지 않았다.

## 사용 동선
포털 로그인 → 등록된 프로젝트의 개발환경 열기 → Orca 사이드바에서 aws-teamproject 선택 → 기존 편집기·터미널 사용. 프로젝트 버튼은 공유 Orca 런타임을 열며 특정 프로젝트로 자동 선택하거나 프로젝트별 권한을 격리하지 않는다.
관리자는 포털의 서버 관리 → Webmin 열기 → 별도 Webmin 계정 로그인 → 서비스/로그 관리.
새로 등록한 포털 프로젝트는 운영자가 Orca 매핑을 등록하기 전까지 실행 버튼을 제공하지 않는다. 사용자 입력으로 셸 명령이나 임의 경로를 실행하지 않는다.

## 재현·운영
웹소켓과 자산 경로는 deploy/orca-nginx-locations.conf를 기존 HTTPS server에 include한다. /orca/runtime만 세션 재검증 중계를 통과하며 다른 Orca 경로의 websocket upgrade는 거절한다.
app/orca_broker.py는 Orca 소유 사용자로 실행, UNIX 소켓 그룹만 포털 사용자에게 허용한다. UID는 배포 시 실제 orca 사용자 값으로 치환한다. broker 서비스에 sudo나 root 권한은 주지 않는다.
Webmin 설치는 deploy/webmin-install.sh. 기존 포털 설치와 root 0600 로그인 파일이 선행돼야 한다. 파일은 새 암호만 추가하고 출력하지 않는다. 검증된 설정 요소를 합친 스크립트 전체 재실행은 미검증이며 검토 후 운영자가 적용한다.
공식 근거: https://www.onorca.dev/docs/remote-servers 와 https://webmin.com/docs/tutorials/proxying-to-webmin-with-nginx/ .
