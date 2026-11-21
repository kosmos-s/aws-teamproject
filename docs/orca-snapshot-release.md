# Orca 폴더 목록 수정: 배포 전 점검과 복구

기준은 `aecc3be1863c8ffc77925d0a20e71a884dd3a956`이다. 배포하는 것은 목록 파일 쓰기 경계의 개선만이다. DB, S3, IAM과 방화벽, Orca 팀원 설정, EC2/RDS 종료 예약은 이 변경의 대상이 아니다.

## 1. 승인 전에 확인

운영자가 사용할 로컬 프로젝트에 `scripts/inspect-orca-snapshot.sh`만 가져온 후 기존 AWS 프로필로 `.\scripts\remote.ps1 -ScriptPath .\scripts\inspect-orca-snapshot.sh`를 실행한다. SSM 실행 이력은 남지만 이 스크립트는 설정 변경이나 자격 증명 읽기를 하지 않는다.

- `BASELINE_MATCH`: 비교 대상 4개 파일이 검토 기준과 일치한다. 다른 운영 파일의 버전까지 확인한 결과는 아니다.
- `REVIEW_REQUIRED` 또는 `MIXED_RELEASE_REVIEW_REQUIRED`: 배포 중단. 다른 코드·설정 또는 이미 일부 반영된 파일을 덮어쓰지 않는다. 운영 원본을 비공개로 비교한 뒤 해당 기준에서 후보를 다시 만든다.
- `CANDIDATE_MATCH`: 배포에 필요한 4개 파일과 로컬 서비스 상태·권한 조건이 일치한다. DB/전체 서비스 버전과 관리자 화면 검증은 별도다.

EC2/RDS 가동 상태, 서버 종료 타이머와 AWS Scheduler의 예약, 작업 시간, 팀원 이용 여부를 확인한다. 장시간 작업이 있거나 종료 예약이 가까우면 변경을 미룬다. 스크립트는 AWS Scheduler를 조회하지 않으므로 콘솔에서 별도로 확인한다.

## 2. 실제 적용은 별도 승인 후

| 후보 파일 | 실제 대상 |
|---|---|
| `app/config.py` | `/opt/kosmos-portal/app/config.py` |
| `app/orca_admin.py` | `/opt/kosmos-portal/app/orca_admin.py` |
| `deploy/orca-link-worker.py` | `/opt/kosmos-portal/deploy/orca-link-worker.py` |
| `deploy/kosmos-orca-link.service` | `/etc/systemd/system/kosmos-orca-link.service` |

1. 운영자가 별도 승인한 시간에 preflight가 여전히 `BASELINE_MATCH`인지 확인한다. 네 파일과 속성, 타이머 및 서비스의 시작 상태를 별도 관리자 전용 위치에 백업한다. 후보는 Git에서 체크아웃한 네 파일만 사용한다.
2. Orca 연결 요청의 진행 여부를 먼저 확인한다. 작업자 타이머를 잠시 멈추고 작업이 완료돼 작업자가 유휴 상태인지 확인한다. 폴더 목록 기능은 포털 앱과 작업자가 같은 경로를 사용해야 하므로 포털을 잠시 중지하고 네 파일을 한 변경으로 교체한 뒤 systemd를 다시 읽힌다.
3. 새 작업자를 실행해 목록 파일 생성을 확인한다. 이전에 활성 상태였던 타이머와 포털을 복원한다. 사전점검의 `CANDIDATE_MATCH` 및 읽기 허용·쓰기 거부를 확인한다. 관리자 화면의 서버 폴더 목록, 일반 사용자의 프로젝트 조회, 기존 Orca 팀원 연결, 승인된 SSM 접속, 기존 종료 예약이 유지되는지 확인한다. 더미 데이터만 사용하고 파일 목록 내용·계정 정보·접속 토큰을 제출물에 담지 않는다.
4. 실패하면 연결 타이머를 다시 멈추고 작업자가 유휴 상태인지 확인한 뒤 포털을 중지한다. 네 파일을 백업 당시 경로와 속성으로 복원하고 systemd를 다시 읽힌다. 기존에 켜져 있던 포털과 타이머만 재개하고 `BASELINE_MATCH`, 포털 응답 및 기존 관리자 목록을 다시 확인한다. 기존 폴더 목록 파일, RDS와 S3의 데이터를 제거하지 않는다.

기록은 점검 시각, 전후 상태, 정상 동작과 접근 차단의 결과로 남긴다. 이는 K-ISMS의 특수 권한(2.5.5), 보안 시험(2.8.2), 변경관리(2.9.1)에 연결할 수 있다. 이 문서는 운영 결과가 아니라 적용 계획이다.
