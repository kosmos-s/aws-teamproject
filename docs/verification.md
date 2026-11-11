# 실제 검증 결과 — 2026-11-10 KST

| 항목 | 결과 | 근거와 한계 |
|---|---|---|
| AWS 인증 | 통과 | STS 성공. 최초 sandbox 내 endpoint 실패와 구분 |
| 플랜/크레딧 | 통과 | Free Tier API FREE/ACTIVE, 비공개 로컬 비용 기록 참조. 최종 재조회도 동일; 반영 지연 가능 |
| 새 EC2 | 통과 | 서울 t3.small 한 대, 상태 검사 system/instance ok |
| EBS/메타데이터 | 통과 | 20 GiB gp3 encrypted=true, IMDSv2 required |
| 패키지 | 통과 | Orca 1.4.255, 공식 release SHA-256 검증 |
| 자동 시작 | 통과 | orca user unit live, lingering=yes |
| 웹 번들 | 통과 | 서버 내부 및 SSM 포워딩 HTTP 200, 실제 Orca Web UI |
| 브라우저 페어링 | 통과 | 사용자 승인 후 현재 PC Chrome에 등록, URL에서 비밀값 제거된 UI 확인 |
| 웹 편집/저장 | 통과 | 웹 편집기로 main.py 수정, SSM에서 저장된 파일 내용 직접 확인 |
| Orca 터미널 실행 | 통과 | `python3 main.py` → `KOSMOS: edited in Orca Web on AWS EC2` |
| 공인 포트 차단 | 통과 | SG ingress=[], EC2 공인 주소:6768 TCP 연결 3초 시간 초과 |
| 무자격 요청 | 제한적 통과 | WS에서 무자격 runtime.status 요청을 보냈고 4001 Invalid e2ee_hello로 종료. 전체 인증·프로토콜 보안 감사는 아님 |
| 파일 보존 | 통과 | main.py 재부팅 전후 SHA-256 동일 |
| 종료 예약 유지 | 통과 | NextElapseUSecRealtime 재부팅 전후 동일 |
| 기존 브라우저 재접속 | 통과 | SSM 터널 재개·브라우저 reload 후 별도 페어링 없이 접속 |
| 터미널 재사용 | 통과 | 워크스페이스 선택 후 기존 AWS Demo 탭 복원, 새 입력으로 Python 재실행 |
| 실행 중인 프로세스의 OS 재부팅 생존 | 주장하지 않음 | 탭/작업 경로 복원과 기존 프로세스의 생존은 다른 사항 |
| 실제 자동 중지 발생 | 미검증 | 11/11 10:38:47 KST 미래 예약 |
| 실제 AI 작업 | 보류 | Codex 설치만 완료, 사용자 요청으로 로그인 나중에 진행 |
| 3인 접속/성능 | 미검증 | 현재 PC 브라우저 한 대만 검증 |
| 포털/DB/백업·복원 | 미구현 | 다음 단계 |

## 재부팅 비교
- main.py SHA-256: `cc9521e56750abead4e874ac891e89e808818b73bc17f012fb8844444456e800` (전후 동일).
- 예약: `승인된 UTC 시각` (전후 동일).
- 재부팅은 SSM 터널 연결을 끊는다. 터널을 다시 열고 브라우저를 새로고침한 뒤 워크스페이스를 선택했다.
- 재부팅 직후 브라우저 선택 전 CLI의 terminal list는 비어 있었다. 워크스페이스에 다시 연결한 뒤 기존 탭이 복원됐다. 즉 모든 세션이 사용자 개입 없이 완전 복원된다고 주장하지 않는다.

## 관찰한 제약과 수정
1. Windows 샌드박스 네트워크: 읽기 전용 AWS 조회가 실패했으나 승인된 sandbox 외부 실행으로 성공.
2. Orca explicit loopback bind: 공식 `pair`가 network_exposure_failed로 거절. 최종 wildcard bind + refuse-public + 인바운드 없는 SG + SSM 접속 사용.
3. service install 직후 CLI 호출: runtime_unavailable 발생. live/HTTP 200 확인 후 1회 재시도해 성공.
4. 한국어 Windows의 AWS CLI 출력 인코딩: cp949가 원격 Unicode 문자를 출력하지 못함. AWS_CLI_OUTPUT_ENCODING=utf-8 및 AWS_CLI_FILE_ENCODING=utf-8로 해결, 같은 기존 SSM 결과 조회 성공.
5. SSM Run Command stdout은 약 24,000자로 제한된다. 가이드 전체 JSON을 읽던 출력은 잘렸으며, 필요한 가이드 부분을 범위 제한하여 읽었다. 파일/백업 전송 경로로 이 출력을 사용하지 않는다.

## 시연 이미지
시연 이미지는 자원 정보가 보일 수 있어 비공개 로컬 검증 자료로 보관합니다.
시연 이미지는 자원 정보가 보일 수 있어 비공개 로컬 검증 자료로 보관합니다.

## 로컬 검사
모든 PowerShell 스크립트 Parser 오류 0개, 배포/검증/데모/Codex 설치 셸 `bash -n` 통과. 이는 실제 AWS/브라우저 검증과 별도로 실행했다.


## 2026-11-10 공개 포털·RDS·S3 검증
- Nginx와 Let’s Encrypt HTTPS: 외부 agent-browser에서 인증서 오류 없이 로그인 화면·인증된 대시보드 확인. 인증서 만료 2027-02-08, Certbot 갱신 타이머 설정.
- Windows 프로젝트 가상환경과 Ubuntu EC2에서 전체 unittest 17/17 통과. 테스트 클라이언트의 httpx 사용에 Starlette deprecation warning 1종이 있으며 테스트 실패는 아니다.
- 실제 RDS MySQL 8.4.13에 프로젝트/메모 저장·재조회, 포털 서비스 재시작 후 유지 확인. TLS CA·호스트 검증, 전용 앱 DB 계정 사용.
- S3 첨부 업로드·인증 다운로드 바이트 일치. 포털 익명 접근 401, S3 직접 익명 GET 403. 공개 차단 옵션 4개 모두 true.
- 실제 백업 748바이트: 프로젝트·메모·첨부 각각 1개를 별도 빈 SQLite/폴더에 복원하고 새 계정으로 복구 앱에 로그인·다운로드 비교 성공. 운영 RDS 덮어쓰기나 PITR 시험은 하지 않았다.
- 실제 Orca 서비스를 잠시 중지 → 점검 failed 기록 → EXIT 복구와 재시작 → 점검 ok 회복을 외부 HTTPS API에서 확인했다. 포털은 계속 응답했다.
- 매분 점검, 매일 UTC 00:00 백업, 3일 보관 설정. 전체 S3 저장량 확인 시 객체 4개 2,288바이트. 첨부는 44바이트다.
- 포털/nginx 활성, 자동 시작 설정 확인. 기존 EC2 자동 중지 예약 유지. RDS는 47초 먼저 중지 요청 예약. 실제 미래 종료는 미검증.
- 계정 전달용 임시 IAM 쓰기 권한과 DB 초기화 비밀번호 읽기 권한 제거를 API로 확인했다.
- 미검증: 실제 AI 요청, 3인 동시 접속, RDS 스냅샷/PITR 복원, 자동 종료 시각의 실제 발생.

![공개 로그인 화면](public-evidence/portal-login.png)
![인증된 운영 대시보드](public-evidence/portal-dashboard.png)


## Orca·Webmin 통합 후속 작업
[연결 검증 기록](orca-access-verification.md)에 실제 확인 범위, 미검증 항목과 로컬 준비 변경을 구분했다. 기존 종료 예약을 유지하며 사용자 요청으로 서버는 재시작하지 않는다.


## 팀 운영 추가 기능 (2026-11-11, 로컬)
[팀 운영 절차](team-operations.md)에 적용 순서와 미적용 항목을 기록했다. 추가 유료 AWS 자원이나 알림 서비스를 생성하지 않았다. 로컬 구현·검증은 운영 배포/메일 발송/2FA 등록과 구분한다.

## 2026-11-11 최신 배포 검증
GitHub 기능 브랜치 091ca9c push 후 [CI 실행](https://github.com/kosmos-s/aws-teamproject/actions/runs/42955132431)이 성공했다. EC2에 같은 릴리스를 배포하고 39개 테스트를 실행했다. RDS available 이후 서비스 4개가 active, /health가 ok임을 확인했다.
탄력적 IP를 기존 EC2에 연결했고 조회 결과의 연결 대상이 일치했다. DNS 변경 전 고정 IP로 해석을 제한하되 HTTPS 호스트 이름과 인증서 검증을 유지해 /health 200, 비인증 관리자 API 401, 인증 후 세션/프로젝트/관리자 사용자/운영 현황 200, Orca 정적 화면/Webmin 로그인 화면 200, 로그아웃 후 프로젝트 API 401을 확인했다. 이는 일반 DNS 접속이나 Orca 편집·터미널 실행 성공을 뜻하지 않는다.
서버 타이머는 EC2 13:47:23 KST/RDS 13:46:30 KST이며, 같은 시각의 AWS 일회성 종료 예약이 enabled임을 확인했다. 이 기록 시점에 미래 종료 발생 자체는 미검증이다.

## 2026-11-11 강의 시연 추가 검증
사용자 추가 승인으로 ALB와 CloudFront/별도 비공개 S3 OAC를 실제 배포했다. ALB healthy·/health 200, CloudFront Deployed·HTTPS 200, S3 원본 403을 확인했다. 정상 DNS로 포털/Orca 연결, 공개 Orca 터미널 실행과 파일 저장·원본 복구, 로그아웃 후 활성 WebSocket 1008 종료(0.02초)를 검증했다. ALB/CloudFront 시연 자원은 오늘 13:47 종료 후 정리한다. [구성·검증·정리 범위](course-demo.md)

EC2에서 새 코드 백업 명령으로 Git HEAD를 백업하고 별도의 빈 /var/tmp 복원 대상으로 복구했다. 복원 README가 원본 커밋 blob과 바이트 단위로 같고 운영 README의 기존 미커밋 변경이 유지됨을 확인했다. 이 검증은 코드 파일 복원이며 서버 전체 복구나 AI 작업 재개를 의미하지 않는다.
