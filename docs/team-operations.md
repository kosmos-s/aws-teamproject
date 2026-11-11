# 팀 운영 기능

이 변경은 로컬에서 구현·검증했다. AWS 배포, GitHub push/Actions 실행, 외부 메일 발송, Webmin TOTP 등록은 아직 하지 않았다.

## 팀 계정과 접속 회수
포털 관리자 화면에서 새 계정과 초기 비밀번호를 입력한다. 비밀번호는 별도 안전한 경로로 전달하고 공유 계정 대신 각자 계정을 사용한다.
admin은 계정·운영 기록과 Webmin, member는 프로젝트 쓰기·Orca, viewer는 조회만 허용한다. 공유 Orca 런타임에서 파일·터미널의 사용자별 격리를 제공한다는 뜻은 아니다.
계정의 역할/접속 허용을 적용하면 모든 기존 세션을 폐기한다. 비활성화된 계정은 로그인할 수 없고, 열린 Orca WS는 즉시 취소 또는 주기 검사에서 차단한다. 자기 관리자 계정과 마지막 활성 관리자 제거를 거절한다. 감사 기록에 비밀번호·토큰은 포함하지 않는다.
기존 users 테이블 열은 바꾸지 않고 blocked_users 테이블을 추가한다. `create_all`로 새 테이블 생성 후 배포한다. 계정 생성 CLI도 `--role viewer`를 지원한다.

## GitHub 자동 테스트
.github/workflows/tests.yml은 push·PR·수동 실행에 대해 Python 3.12, 고정 의존성, 전체 unittest, Python/셸 문법을 검사한다. Actions는 공식 저장소에서 존재를 확인한 커밋으로 고정했고 token은 contents:read만 허용한다. PR 코드를 실제 운영 서버에 자동 배포하거나 AWS 비밀값을 제공하지 않는다. 현재 로컬 파일이므로 원격 실행은 미검증이다.

## 프로젝트 코드 백업·복구
운영자 터미널에서 저장소 루트 기준:
```
python -m app.code_backup backup /approved/project /private/code-snapshot.json
python -m app.code_backup restore /private/code-snapshot.json /new/empty-recovery
```
backup에 `--s3`를 명시하면 현재 S3_BUCKET과 인스턴스 역할로 backups/ 경로에 추가 업로드한다. 명시하지 않으면 로컬 파일만 만든다. S3 객체 키와 백업 파일은 비공개 운영 기록에 보관한다. S3 사용을 실제 검증하기 전에는 원격 백업 성공으로 설명하지 않는다.
Git HEAD의 추적 파일만 포함한다. 미커밋·추적 안 된 파일은 제외하며, 추적된 비밀/생성 경로와 symlink/submodule은 거절한다. 파일당 1MiB, 원문 합계 8MiB, 아카이브 16MiB 제한. 새 폴더로만 복원하고 경로·중복·체크섬을 전부 검사한 뒤 파일을 생성한다.
로컬 테스트는 복구된 Python 예제를 실제로 실행하고 원본 Git blob과 바이트를 비교한다. AWS Orca에서 복구 프로젝트 재실행은 별도 검증으로 남긴다. 복구 과정 자체는 코드를 자동 실행하지 않는다.

## 외부 장애 알림
감시 대상 EC2 밖의 상시 켜진 PC/호스트에서 실행한다. deploy/external-monitor.env.example을 참고해 HTTPS /health와 새로 승인된 시작·종료 시각, SMTP 수신처를 환경에 넣는다. 이 파일에는 실제 자격증명을 커밋하지 않는다.
`python -m app.external_monitor --state /private/monitor-state.json`을 1분마다 실행한다. 별도 Linux 호스트에는 제공한 systemd service/timer를 설치할 수 있다. WorkingDirectory와 EnvironmentFile 경로를 실제 설치 위치에 맞춘 뒤 운영자가 활성화한다. 현재 타이머 설치·활성화는 하지 않았다.
3회 연속 실패 시 장애, 2회 연속 성공 시 복구 메일을 한 번 보낸다. 동일 상태에서는 반복 발송하지 않는다. 메일 실패는 다음 검사에서 재시도한다. SMTP 미설정이면 unconfigured 상태이며 전송 성공으로 기록하지 않는다. TLS STARTTLS를 사용한다.
승인 운영 시간 밖에는 HTTP 점검/메일 발송을 억제하며 planned-stop으로 기록한다. SMTP 장애를 별도로 전달하는 이중 감시나 감시 호스트 장애 감지는 구현하지 않았다.

## 비용·자원 정리 현황
운영자가 실제 AWS를 읽기 전용 확인한 뒤 deploy/operations.example.json 형식으로 DATA_DIR/operations.json을 갱신한다. captured_at은 실제 확인 시각, stop_at은 승인 종료 시각으로 기록한다. 오래된 예약 시각을 새 승인으로 해석하지 않는다.
예제는 과거 시각·unknown 상태이므로 실제 상태처럼 표시되지 않는다. 스냅샷이 없거나 잘못되면 unknown, 1시간 초과면 stale. 표시한 월 비용은 단가 기준 견적이며 실청구/크레딧 잔액이 아니다. S3·트래픽 등 별도 비용과 중지 후 저장 비용을 함께 고려한다. RDS의 7일 후 자동 재시작은 별도 확인한다.
이 화면은 자원 삭제·서버 시작·운영 시간 연장 기능을 제공하지 않는다. 정리 상태는 운영자가 pending/retained/deleted/unknown으로 기록한다.

## Webmin 2FA
[등록·복구 절차](webmin-2fa.md)를 따른다. 실제 인증 앱 등록은 사용자 작업이 필요하다. 로컬 준비를 활성화 완료라고 표현하지 않는다.

EC2에서 새 코드 백업 명령으로 Git HEAD를 백업하고 별도의 빈 /var/tmp 복원 대상으로 복구했다. 복원 README가 원본 커밋 blob과 바이트 단위로 같고 운영 README의 기존 미커밋 변경이 유지됨을 확인했다. 이 검증은 코드 파일 복원이며 서버 전체 복구나 AI 작업 재개를 의미하지 않는다.
