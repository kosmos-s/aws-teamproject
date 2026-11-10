# 비용 확인 — 2026-11-10 (한국 시간)

## 계정에서 직접 확인
- AWS CLI 2.39.3, 프로필 `kosmos-cloud`, 리전 `ap-northeast-2`.
- STS 성공. 인증 파일과 세션 토큰은 저장소에서 제외함.
- Free Tier API: 플랜 FREE / ACTIVE, 잔여 크레딧 **비공개 로컬 비용 기록 참조**.
- 플랜 만료: **비공개 로컬 비용 기록 참조**. API가 반환한 것은 플랜 만료이며 별도 프로모션별 크레딧 만료까지 확인한 것은 아님.
- 기존 서울 기본 VPC·서브넷·인터넷 게이트웨이 재사용. 기존 보안 그룹은 변경하지 않음.

## 승인한 초기 구성
사용자 답변: **우선 24시간 배포 후 자동 중지**.

| 항목 | 단가 | 24시간 예산 계산 | 730시간 월 환산 |
|---|---:|---:|---:|
| Linux t3.small, 2 vCPU/2 GiB | $0.026/시간 | $0.624 | $18.98 |
| 공인 IPv4 1개, 자동 할당 | $0.005/시간 | $0.12 | $3.65 |
| 암호화 gp3 20 GiB, 기본 성능 | $0.0912/GiB·월 | 약 $0.060 | $1.824 |
| 합계 | | 약 **$0.81** | 약 **$24.45** |

EC2/EBS 단가는 AWS Price List API에서 조회. IPv4 단가는 [AWS VPC 가격](https://aws.amazon.com/vpc/pricing/) 확인.
위 금액은 크레딧 차감 전 정가의 계산이며 청구 확정액이나 강제 지출 상한이 아니다. 데이터 전송·추가 서비스·세금·AI 제공자 사용료는 포함하지 않았다.
추가 유료 CPU 크레딧을 막기 위해 t3를 **standard**로 생성했다. CPU 크레딧 소진 시 성능이 제한될 수 있다.

## 자동 중지와 남는 비용
- 최초 승인 종료: **승인된 시각(로컬 배포 설정 참조)**.
- systemd 절대 시각 타이머 `kosmos-auto-stop.timer`, `Persistent=true`.
- 종료 동작: `shutdown -h now` → EC2의 `InstanceInitiatedShutdownBehavior=stop`.
- 재부팅으로 승인 시간을 연장하지 않는다. 종료 시각을 지난 뒤 다시 부팅하면 타이머가 즉시 중지할 수 있으므로 재사용 때 새 운영 시간 승인이 필요하다.
- 중지 후 t3 실행료와 자동 할당 IPv4 사용료는 멈추지만, **20 GiB EBS 약 $1.82/월은 계속 남는다**.
- 종료/삭제는 별도 사용자 지시 전에는 수행하지 않는다. Terminate는 루트 EBS를 삭제하도록 설정되어 있으므로 백업 없이 실행하지 않는다.
- Free plan을 Paid plan으로 전환하지 않았다. RDS/ALB/NAT/추가 EC2/Elastic IP를 생성하지 않았다.

## 확인 범위
크레딧/사용량 반영은 실시간이 아니므로 설치 직후 차감액을 확정하지 않는다. 다른 리전의 EBS·ELB·RDS 등 전체 자원 비용 감사는 아직 수행하지 않았다.

공식 참고: [Free Tier 플랜 API](https://docs.aws.amazon.com/cli/latest/reference/freetier/get-account-plan-state.html), [EC2 Free Tier](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-free-tier-usage.html), [EC2 정지/시작](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/Stop_Start.html).
