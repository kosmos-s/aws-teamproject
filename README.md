# AWS Team Project — KOSMOS Cloud

**운영 기록 갱신: 2026-11-11 추가 승인으로 EC2·RDS를 재기동했습니다. 이번 EC2 종료는 15:02:07 KST, RDS 중지 요청은 15:01:14 KST입니다. 이 시각 이후의 실시간 상태를 이 문서만으로 판단하지 마세요. 한시 ALB·CloudFront·정적 S3 시연 자원은 삭제 상태를 유지합니다.**

대학 과제용 AWS EC2 한 대에 Orca를 실제 배포하는 프로젝트.

**현재: 공개 HTTPS 포털·RDS·S3·모니터링·논리 백업/복구를 AWS에서 검증했습니다. AI 로그인과 3인 동시 접속은 미검증입니다.**

- [진행 상태](STATUS.md)
- [실제 검증과 시연 화면](docs/verification.md)
- [접속·배포 가이드](docs/deployment.md)
- [비용과 24시간 자동 중지](docs/costs.md)
- [구성도](docs/architecture.md)
- [출처와 기여](docs/contributions.md)
- [에이전트 작업 지침](AGENTS.md)
- [Orca에서 GitHub 프로젝트 사용하기](docs/orca-workflow.md)
- [강의 자료 검토와 보완안](docs/course-review.md)

프로젝트 폴더에서 `.\scripts\connect.ps1` 실행 후 브라우저 `http://127.0.0.1:6768/` 접속. 현재 PC의 승인된 페어링은 브라우저에 저장되어 있다.

**자동 중지: 승인된 시각(로컬 배포 설정 참조).** 중지 후 EBS는 보존되어 약 $1.82/월이 남는다.

`.local/`, `vendor/`, 데이터·인증정보는 소스 제출 ZIP이나 Git에 포함하지 않는다. 실제 자원 ID/프로필은 Git 제외 로컬 설정에 보관한다.

저장소: [kosmos-s/aws-teamproject](https://github.com/kosmos-s/aws-teamproject). 공개 포털과 RDS·S3 연동을 검증했습니다. 설치된 Orca와 자체 구현한 포털·운영 코드를 구분합니다. localhost는 Orca용 SSM 주소이고 공개 HTTPS 포털은 별도 서비스입니다. 운영 URL과 계정은 운영자가 전달합니다.

- [포털 운영·복구](docs/portal-operations.md)
- [데이터 모델](docs/data-model.md)
- [발표 시연 순서](docs/demo-script.md)

로컬 검증: Python 3.12 이상에서 가상환경 생성, `pip install -r requirements.lock`, `python -m unittest discover -s tests -v`.

## Orca와 서버 관리 통합
포털 프로젝트의 **Orca에서 개발환경 열기**로 공유 Orca에 연결하고, 사이드바에서 aws-teamproject를 선택한다. 관리자는 **서버 관리 → Webmin**에서 별도 계정으로 서비스·로그를 확인한다. 현재 구현·실제 검증·미검증 범위는 [연결 검증 기록](docs/orca-access-verification.md)을 따른다. 서버 GitHub 쓰기 인증과 AI 로그인은 아직 완료되지 않았다.

## 팀 운영 기능
계정·역할·접속 회수, GitHub 자동 테스트, Git 코드 백업/복구, 외부 장애 알림과 비용·자원 현황을 추가했다. [사용·적용 절차](docs/team-operations.md)와 [Webmin 2FA 등록](docs/webmin-2fa.md)을 참고한다. 서버 배포·원격 CI와 공개 Orca 편집/실행을 검증했다. 실제 메일 발송·TOTP 등록은 미완료다.

## 2026-11-11 실제 배포 갱신
팀 운영 기능을 AWS에 적용하고 관리자 API·운영 스냅샷·로그아웃 접근 회수를 확인했다. GitHub 기능 브랜치 push와 CI 실행이 성공했다. 강의 2장의 탄력적 IP를 기존 EC2에 연결했다. DNS가 고정 IP를 가리키며 정상 DNS·TLS 접속을 검증했다. AI 로그인·3인 동시 접속·실제 메일/TOTP 등록은 미완료다.

## 2026-11-11 강의 시연 추가 검증
사용자 추가 승인으로 ALB와 CloudFront/별도 비공개 S3 OAC를 실제 배포했다. ALB healthy·/health 200, CloudFront Deployed·HTTPS 200, S3 원본 403을 확인했다. 정상 DNS로 포털/Orca 연결, 공개 Orca 터미널 실행과 파일 저장·원본 복구, 로그아웃 후 활성 WebSocket 1008 종료(0.02초)를 검증했다. ALB/CloudFront 시연 자원은 오늘 13:47 종료 후 정리한다. [구성·검증·정리 범위](docs/course-demo.md)

## 발표·제출 준비
발표자: 김건보·강태영·박찬욱. 팀명 없음. [발표 대본과 근거](docs/presentation-script.md), [3인 최종 시연 절차](docs/final-rehearsal.md), [제출 점검표](docs/submission-checklist.md)를 참고한다. 개인별 기여는 실제 기록으로 작성한다.
