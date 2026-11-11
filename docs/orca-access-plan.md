# Orca 포털 통합 실행 계획
사용자가 승인한 계획을 현재 기능 브랜치에 이어서 실행한다. 기존 24시간 종료·AI 로그인 보류·데이터 절감은 유지한다.
1. 기존 버전의 웹 자산 상대 경로·페어링 endpoint·WebSocket 지원을 읽기 전용 확인. 외부 DNS 추가 없이 /orca/ 사용을 우선 검증.
2. tests/test_orca_access.py: 익명/교차 Origin/CSRF 거부, 승인된 프로젝트 매핑, 세션 만료·폐기 후 WS 차단과 활성 연결 종료를 먼저 실패 테스트로 작성.
3. app/orca_gateway.py: 고정 loopback WS만 중계하고 원래 Orca E2EE 프레임 유지. DB 세션 2초 재확인. app/orca_broker.py: 별도 Orca 사용자 UNIX socket에서 고정 pair 명령만 실행, 로그에 자격증명 없음.
4. Nginx 보호 경로 /orca/와 내부 auth subrequest, 프로젝트별 개발환경 열기 버튼. 브라우저 페어링 fragment는 native Orca가 소비하며 portal 사용자에게 공유 서버 전체 제어 권한임을 명시.
5. 로컬 테스트·ECC 검토 후 기존 EC2에 배포. 실제 브라우저에서 파일 수정·터미널 실행·재접속·로그아웃 시 활성 WS 종료 확인. GitHub 서버 쓰기 인증은 기존 토큰 복사 없이 별도 준비.
6. Git 코드와 포함 범위가 고정된 프로젝트 파일 복구를 Orca에서 다시 열고 실행해 확인. 최신 검증/한계·발표 자료 반영.
Review focus: active WS survives logout; public asset/WS bypass; arbitrary shell/endpoint injection; credential logging; shared user isolation claims. No extra paid resource or public port.
