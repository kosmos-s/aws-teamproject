# AWS Team Project — KOSMOS Cloud

대학 과제용 AWS EC2 한 대에 Orca를 실제 배포하는 프로젝트.

**현재: Orca AWS 배포·브라우저 파일 편집/실행·재부팅 복구 검증 완료. 포털/DB/모니터링/백업은 다음 단계.**

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

저장소: [kosmos-s/aws-teamproject](https://github.com/kosmos-s/aws-teamproject). 공개 포털과 RDS·S3 연동은 구현 중이며, 설치된 Orca를 자체 개발한 것으로 주장하지 않는다. 현재의 localhost URL은 SSM 터널 주소로, 외부 공유 URL은 아직 제공하지 않는다.
