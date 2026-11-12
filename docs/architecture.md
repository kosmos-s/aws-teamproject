# 현재 구성 안내

2026-11-11 현재 공개 HTTPS Orca·Webmin, 고정 EIP, RDS/S3와 한시 ALB·CloudFront 시연은 [최신 실제 구성도](course-demo.md)를 따른다. 아래는 초기 단계에서 최신 포털로 확장한 기록이다.

# 초기 Orca 배포 구조 (아래 최신 포털 구성 참고)

```mermaid
flowchart LR
    B[사용자 브라우저] -->|localhost:6768| P[공식 SSM 플러그인]
    P -->|AWS IAM 인증 / TLS| S[AWS Systems Manager]
    S -->|EC2가 연 outbound 채널| A[Ubuntu 24.04 SSM Agent]
    subgraph EC2 한 대
        A --> O[Orca 1.4.255 / 비관리자 orca 사용자]
        O --> R[프로젝트와 세션 / 암호화 gp3 20 GiB]
        T[절대 시각 systemd 타이머] -->|승인된 24시간 후| STOP[OS shutdown → EC2 stop]
    end
```

서울 기본 VPC의 공용 서브넷을 재사용한다. 공인 IPv4는 패키지 다운로드와 SSM outbound 연결용이다. 보안 그룹 인바운드는 0개이며 SSH 키도 생성하지 않는다. Orca 1.4.255의 `pair`는 네트워크 노출을 요구하여 명시적 loopback bind에서는 `network_exposure_failed`로 거절했다. 따라서 최종 Orca 리스너는 0.0.0.0:6768이며 `--refuse-public`을 사용한다. AWS 보안 그룹에서 모든 인바운드를 차단하고, SSM Agent가 loopback으로 전달하는 경로로만 접속한다. `--pairing-address 127.0.0.1`은 SSM 로컬 포워딩 클라이언트에게 안내할 주소다.

원격 서버는 [Orca 공식 문서](https://www.onorca.dev/docs/remote-servers)에서 베타로 안내한다. 공인 포트를 직접 공개하지 않으며, 계정별 격리나 실시간 공동 편집을 지원한다고 주장하지 않는다.

SSM 터널은 계정의 권한 있는 사용자만 연결한다. 팀원 접속을 위해서는 별도 최소권한 IAM 접속 권한 또는 승인된 사설 네트워크 구성이 추가로 필요하다. 현재의 로컬 URL을 공개 인터넷 URL이라고 표현하지 않는다. 외부 포털과 HTTPS는 다음 구현 단계다.

## 초기 계획 (구현 전 기록)
FastAPI + HTML/CSS/JS + SQLite 운영 포털, 고정 대상 상태조회, 프로젝트·메모·운영 기록, 백업/실제 복원 검증. 현재 문서의 구성도에는 아직 구현하지 않은 요소를 배포 완료로 표시하지 않는다.


## 최신 운영 구성
```mermaid
flowchart LR
    U[외부 팀원] -->|HTTPS 443| N[Nginx]
    subgraph EC2 한 대
        N -->|loopback 8000| P[FastAPI 운영 포털]
        O[Orca / 6768]
        M[매분 고정 대상 점검] --> O
        M --> P
        B[매일 논리 백업]
    end
    P -->|TLS / 비공개 3306| R[RDS MySQL]
    P -->|EC2 역할| S[S3 비공개 첨부]
    B --> R
    B --> S
    A[승인된 사용자] -->|IAM SSM + 페어링| O
```
웹 인바운드는 80/443만 허용한다. RDS SG는 EC2 SG의 3306만 허용하고 공개 접근을 끈다. S3는 공개 차단·암호화와 지정 prefix 권한을 사용한다.
EC2/RDS는 각각 기존 승인 시각의 자동 중지 타이머를 둔다. 다중 서버나 고가용성 구성은 아니다. 복구는 논리 데이터와 첨부를 별도 빈 SQLite/폴더에 검증한 범위다.
