# 협업 도구 비교와 다음 개선 후보

2026-11-12 공식 도움말을 확인했다. 기능 선택을 위한 비교이며 외부 서비스 가입·유료 플랜 도입 제안은 아니다.

| 참고 서비스 | 공식 기능 | 이번 포털에 적용/추천 |
|---|---|---|
| [Slack Activity](https://slack.com/intl/en-gb/help/articles/19693583638803-Get-your-work-done-from-the-Activity-view), [미확인 메시지](https://slack.com/help/articles/226410907-View-all-your-unread-messages) | 미확인 알림을 한곳에서 확인하고 처리 | 지속되는 대시보드 변경사항·계정별 확인 상태를 구현. 다음 후보는 종류·기간·프로젝트 필터와 일별 묶음 보기 |
| [Discord 알림](https://support.discord.com/hc/en-us/articles/215253258-Notifications-Settings-101) | 전체/멘션 중심 알림과 음소거 설정 | 계정별 전체/멘션만/끄기 구현. 다음 후보는 방별 음소거·방해 금지 시간 |
| [GitHub Projects](https://docs.github.com/en/issues/planning-and-tracking-with-projects/customizing-views-in-your-project/managing-your-views) | 상태·담당·목표 날짜 등에 따른 저장된 보기 | 기존 칸반을 유지. 다음 후보는 내 할 일·지연 항목·담당자별 필터와 우선순위 |
| [GitHub Projects Insights](https://docs.github.com/en/issues/planning-and-tracking-with-projects/viewing-insights-from-your-project/about-insights-for-projects) | 업무 데이터 기반 차트 | 작은 팀에서는 간단한 완료/지연 집계부터 추가하는 편이 구현·발표에 유용 |

추천 순서는 변경 알림 필터 → 내 할 일/지연 필터 → 방별 음소거 → 프로젝트별 활동 통계다. 기존 EC2·RDS에서 직접 구현하면 별도 서비스 고정비는 추가하지 않아도 되지만 DB·저장·트래픽 사용량은 증가할 수 있다. 이번 사용자 요청 없이 후보 기능을 추가 구현하지 않았다.

파일 버전 비교·대용량 검색·실시간 공동 편집·음성 통화·외부 AI 요약은 운영 부담이 크다. 특히 AI 로그인과 추가 유료 서비스는 현재 합의 범위 밖이다. 소유자 관리와 GitHub 주소/Deploy key는 별도 인계의 설계·승인 절차로 다룬다.
