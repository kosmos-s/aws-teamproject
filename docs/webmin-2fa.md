# Webmin 2단계 인증 적용 절차

현재는 로컬 준비 단계다. 서버 재시작·계정의 TOTP 등록·설정 변경은 실행하지 않았다. 본인이 인증 앱을 등록하고 새 브라우저에서 확인하기 전에는 활성화 완료로 표시하지 않는다.

## 사전 확인
서버 사용을 다시 승인한 뒤 운영자가 `sudo python3 scripts/webmin-2fa-preflight.py`를 실행한다. 이 스크립트는 버전·loopback 바인딩만 읽으며 QR/시드/복구 코드를 읽거나 출력하지 않는다.
이전에 설치한 버전은 2.670이다. 실제 적용 시 다시 버전을 확인한다. 공식 보안 공지 GHSA-qpww-fff2-6fgv의 Basic 인증 우회 수정 버전은 2.640이다.

## 등록
1. 포털 관리자 로그인과 Webmin 별도 로그인을 유지한다. 비상 복구용 AWS SSM 접속 가능 여부를 먼저 확인한다.
2. 운영자가 Webmin Configuration / Two-Factor Authentication에서 Google Authenticator(TOTP) 제공자를 선택한다. 기존 제한된 관리 계정에 Webmin Configuration·Webmin Users 모듈 권한이 없으므로, 등록 가능한 관리자 권한을 별도 승인·구성해야 한다. 일반 팀원에게 부여하지 않는다.
3. Webmin Users에서 본인 계정의 Two-Factor Authentication을 열고 Enroll을 진행한다. QR을 본인 인증 앱으로 직접 등록한다. QR·시드·일회용 코드를 채팅, Git, 로그나 스크린샷에 남기지 않는다.
4. 기존 관리 세션은 유지한 채 시크릿 창에서 포털 → Webmin 로그인. 비밀번호만으로 들어갈 수 없고 올바른 TOTP가 추가로 필요한지 확인한다.
5. 잘못된 코드·만료 코드의 거절을 확인하고 완료 기록을 남긴다. 복구 정보는 사용자가 비공개로 보관한다.

## 복구
기기를 잃었을 때는 승인된 SSM 관리 경로로 Webmin 공식 CLI의 `disable-twofactor --help`를 먼저 확인하고 본인 계정에 한해 복구한다. 긴급 복구 명령을 자동 타이머나 웹 API로 만들지 않는다. 복구 후 새 기기로 재등록하고 다시 검증한다.

공식 출처: [설정과 등록](https://webmin.com/docs/modules/webmin-configuration/#two-factor-authentication), [보안 수정](https://github.com/webmin/webmin/security/advisories/GHSA-qpww-fff2-6fgv), [Webmin CLI](https://webmin.com/docs/reference/webmin-command-line/).
