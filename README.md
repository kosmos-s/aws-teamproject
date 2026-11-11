# AWS Team Project — KOSMOS Cloud

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
