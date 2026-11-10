# 포털 운영과 복구

## 실행
Python 3.12 이상. `python -m venv .venv` 후 가상환경에서 `pip install -r requirements.txt`.
환경 변수는 `.env.example` 참고. 앱은 dotenv를 자동으로 읽지 않으므로 운영에서는 systemd EnvironmentFile을 사용한다.
로컬 HTTP 테스트만 `SECURE_COOKIES=false`, `PORTAL_ORIGIN=http://127.0.0.1:8000`.
`python -m app.cli create-user owner --role admin`으로 비밀번호를 직접 입력한다. 비밀번호를 명령 인수나 Git에 저장하지 않는다.
`uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000`.

## 운영 구성
Nginx HTTPS → loopback FastAPI 단일 worker → 포털 DB. 포털 역할은 팀 공동 프로젝트의 읽기/작성을 허용하며, admin도 웹 셸이나 서버 명령 실행 기능을 갖지 않는다.
세션은 DB에 토큰 해시로 저장하고 8시간 후 만료한다. 로그아웃은 DB 세션을 폐기한다. 쓰기 요청은 정확한 Origin과 CSRF 토큰을 요구한다.
로그인 제한은 단일 프로세스 메모리에서 IP별 5회 실패/5분. 재시작 시 초기화되며 다중 worker/다중 서버용 분산 제한은 구현하지 않는다.
RDS 운영 URL은 `mysql+pymysql://.../kosmos?charset=utf8mb4&ssl_ca=/opt/kosmos-portal/rds-ca.pem&ssl_check_hostname=true` 형태로 TLS 호스트 검증을 사용한다.
RDS SG는 EC2 SG에서 들어오는 3306만 허용하고 PubliclyAccessible=false. 장기 AWS 키 없이 EC2 역할로 비공개 S3 경로만 접근한다.

## 점검
`python -m app.cli monitor`: Orca loopback 고정 TCP 포트, CPU/RAM/disk, DB 기록 확인. TCP 연결은 Orca 로그인이나 AI 동작을 증명하지 않는다.
`kosmos-monitor.timer` 매분, 포털은 마지막 기록이 180초보다 오래되면 stale로 표시한다. 웹 앱이나 DB 자체가 내려가면 포털도 응답할 수 없으므로 외부 /health와 systemd 로그로 별도 확인한다.
운영 점검 기록은 3일. 시스템 로그는 OS 정책을 따른다.

## 백업과 복구
`python -m app.cli backup`: projects/work_notes/attachments 논리 덤프와 첨부 바이트 및 SHA-256을 하나의 JSON 객체에 저장한다. 16MiB 과제 한도다.
사용자 비밀번호·세션·AI/GitHub 토큰·Orca 내부 DB는 포함하지 않는다. 포털 계정은 복구 후 별도 재생성한다. Orca 프로젝트 코드는 Git을 기본 복구 경로로 사용한다.
운영에서는 매일 UTC 00:00, S3 backups/ 경로는 3일 만료 정책을 적용한다. 첨부에는 자동 만료를 적용하지 않는다.
**복구는 빈 대상 DB와 별도 데이터 폴더에서만** 실행한다. 운영 DB를 덮어쓰지 않는다.
1. 비공개 백업 객체를 관리 경로로 내려받고 권한을 0600으로 제한한다.
2. 별도 `DATABASE_URL`, `DATA_DIR`, 빈 `S3_BUCKET` 환경을 지정한다.
3. `python -m app.cli restore /private/recovery.json` 실행.
4. 프로젝트·메모 수와 내용을 조회하고 첨부 SHA-256/실제 다운로드를 비교한다.
5. 계정을 새로 생성한 뒤 복구 앱 접속까지 확인한다. 원본 DB 전환은 별도 검토한다.

EC2 자동 중지는 RDS·S3 저장 비용을 멈추지 않는다. RDS 중지도 저장 비용은 남고 7일 뒤 자동 재시작될 수 있다. 자원 삭제는 별도 사용자 승인 후 수행한다.
