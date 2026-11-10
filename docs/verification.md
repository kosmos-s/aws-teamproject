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
