# DevCompass Airflow Docker 배포 전달서

## 1. 배포 목표

DevCompass의 두 Airflow DAG를 로컬 맥북이 아닌 AWS 내부에서 실행한다.

```text
ATS Public API
      |
      v
ATS Collection DAG
      |
      v
RDS PostgreSQL
      |
      v
Enrichment DAG
      |
      +-- title -> LinearSVC -> job_role
      |
      +-- description -> skill_alias matcher -> job_skill
```

운영 컨테이너는 VPC 내부에서 RDS에 직접 연결한다. SSH 터널은 개발자가
로컬에서 RDS를 점검할 때만 사용하며, Fargate 실행 경로에는 포함하지 않는다.

## 2. 구현된 Airflow DAG

### ATS Collection DAG

- DAG ID: `devcompass_public_ats_collection`
- 파일: `dags/devcompass_collection.py`
- Greenhouse, Lever, Ashby 공개 API에서 채용공고를 수집한다.
- 신규, 변경, 유지, 마감 상태를 판정한다.
- API 호출에 실패한 보드는 공고 마감 판정을 수행하지 않는다.
- 결과를 `job_posting`, `job_posting_history` 등에 저장한다.

### Enrichment DAG

- DAG ID: `devcompass_job_enrichment`
- 파일: `dags/devcompass_enrichment.py`
- `job_posting_history`를 기준으로 처리한다.
- `classify_job_role`과 `extract_skills`를 병렬로 실행한다.
- 직무 모델 버전: `job-role-svc-v1`
- 기술 추출기 버전: `tech-dictionary-v1`

```text
select_targets
       |
prepare_enrichment
       |
       +-------------------+
       |                   |
classify_job_role     extract_skills
       |                   |
       +---------+---------+
                 |
       finalize_enrichment
```

현재 Enrichment DAG의 `schedule`은 `None`이다. 운영 스케줄과 Collection DAG
완료 후 실행 방식은 배포 단계에서 확정해야 한다.

## 3. Docker 이미지에 포함할 파일

```text
dags/
  devcompass_collection.py
  devcompass_enrichment.py

src/devcompass/
  __init__.py
  models.py
  text.py
  service.py
  storage.py
  enrichment.py
  collectors/
    __init__.py
    base.py
    greenhouse.py
    lever.py
    ashby.py

experiment/
  job_role_svc_v1.joblib

pyproject.toml
requirements-airflow.txt
```

`src/devcompass` 패키지는 이미지 빌드 과정에서 설치해야 한다.

```bash
pip install --no-cache-dir -r requirements-airflow.txt
pip install --no-cache-dir .
```

## 4. 이미지에 포함하지 않을 파일

```text
.venv/
.airflow/
docs/
tests/
*.ipynb
*.egg-info/
*.pem
.env
.env.*
logs/
*.csv
*.parquet
.DS_Store
ERD.rtf
scripts/airflow_env.sh
```

`scripts/airflow_env.sh`는 로컬 맥북 절대 경로와 로컬 PostgreSQL 주소가 들어간
개발 전용 파일이므로 운영 이미지에서 사용하지 않는다.

## 5. 컨테이너 내부 권장 경로

```text
/opt/airflow/devcompass/
  dags/
  src/
  experiment/job_role_svc_v1.joblib
  pyproject.toml
  requirements-airflow.txt
```

Airflow DAG 폴더는 다음 경로로 지정한다.

```text
AIRFLOW__CORE__DAGS_FOLDER=/opt/airflow/devcompass/dags
```

## 6. 필요한 환경변수

일반 환경변수:

```text
DEVCOMPASS_ROLE_MODEL_VERSION=job-role-svc-v1
DEVCOMPASS_SKILL_EXTRACTOR_VERSION=tech-dictionary-v1
DEVCOMPASS_ROLE_MODEL_PATH=/opt/airflow/devcompass/experiment/job_role_svc_v1.joblib
DEVCOMPASS_ROLE_BATCH_SIZE=250
AIRFLOW__CORE__LOAD_EXAMPLES=False
AIRFLOW__CORE__DAGS_FOLDER=/opt/airflow/devcompass/dags
```

Secret으로 주입할 값:

```text
DEVCOMPASS_DSN
AIRFLOW__DATABASE__SQL_ALCHEMY_CONN
AIRFLOW 인증 및 암호화 관련 Secret
```

예시 형식만 참고한다. 실제 비밀번호를 GitHub, Dockerfile, Task Definition의
일반 환경변수에 직접 기록하지 않는다.

```text
DEVCOMPASS_DSN=postgresql://devcompass:<PASSWORD>@<RDS_HOST>:5432/devcompass?sslmode=require
AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:<PASSWORD>@<HOST>:5432/airflow_meta
```

AWS Secrets Manager 또는 동등한 Secret 저장소에서 ECS Task Definition으로
주입한다.

## 7. PostgreSQL 분리 원칙

채용공고 DW와 Airflow Metadata DB를 논리적으로 분리한다.

```text
RDS PostgreSQL
  devcompass    # 채용공고 DW
  airflow_meta  # Airflow 자체 실행 상태
```

- `devcompass`의 테이블은 `db/schema.sql`이 관리한다.
- `airflow_meta`의 테이블은 `airflow db migrate`가 관리한다.
- Airflow Metadata 테이블을 `devcompass`의 `public` 스키마에 섞지 않는다.
- DDL과 Seed는 컨테이너가 시작될 때마다 실행하지 않는다.

RDS에는 다음 파일이 이미 적용된 상태다.

```text
db/schema.sql
db/seed_reference_data.sql
db/seed_ats_boards.sql
```

향후 스키마 변경은 별도의 일회성 Migration Task로 수행한다.

## 8. 네트워크 및 보안

```text
ECS/Fargate Task Security Group
             |
             | TCP 5432
             v
RDS Security Group
```

확인 사항:

- ECS/Fargate Task와 RDS가 통신 가능한 VPC 및 Subnet에 있어야 한다.
- RDS Security Group은 ECS Task Security Group에서 오는 `5432`만 허용한다.
- RDS를 인터넷에 공개하지 않는다.
- 컨테이너에서 EC2 SSH 터널을 생성하지 않는다.
- ATS 공개 API 호출을 위한 HTTPS `443` Outbound 경로가 필요하다.
- 컨테이너 로그는 CloudWatch Logs로 전송한다.
- ECS Task Role과 Task Execution Role은 최소 권한으로 분리한다.

## 9. Airflow 실행 구성

Self-managed Airflow를 Fargate에 배포한다면 최소한 다음 구성요소가 필요하다.

```text
Airflow API Server
Airflow Scheduler
Airflow DAG Processor
Airflow Metadata DB
CloudWatch Logs
```

모든 구성요소는 동일한 버전의 DAG, Python 패키지, 모델 파일을 사용해야 한다.
하나의 공통 이미지를 사용하고 컨테이너별 실행 명령만 구분하는 방식을 권장한다.

현재 로컬 검증 버전:

```text
Apache Airflow 3.0.6
scikit-learn 1.6.1
joblib 1.5.3
PostgreSQL 16
```

운영 이미지의 Python 및 scikit-learn 버전이 변경되면
`job_role_svc_v1.joblib` 로딩과 예측을 반드시 이미지 내부에서 검증한다.

## 10. DAG 실행 순서

```text
1. devcompass_public_ats_collection 실행
2. Collection DAG 성공 또는 허용 가능한 partial_success 확인
3. devcompass_job_enrichment 실행
4. RDS 적재 결과 검증
```

두 DAG 연결 방식 후보:

- Collection DAG 성공 후 Enrichment DAG Trigger
- 두 DAG에 별도 스케줄을 주되 Enrichment를 충분히 늦게 실행
- Airflow Dataset/Event 기반 연결

초기 운영에서는 명시적 DAG Trigger 방식을 권장한다.

`airflow dags test`는 로컬 검증 명령이며 운영 스케줄 실행 명령으로 사용하지
않는다.

## 11. 이미지 빌드 및 배포 흐름

```text
GitHub Push
    |
    v
Docker Build
    |
    v
Unit Test + DAG Import Test + Model Smoke Test
    |
    v
Amazon ECR Push
    |
    v
ECS Task Definition Revision
    |
    v
ECS Service Deployment
```

권장 이미지 태그:

```text
devcompass-airflow:<git-commit-sha>
devcompass-airflow:<release-version>
```

운영 배포에서는 `latest` 태그만 의존하지 않고 커밋 SHA 또는 고정 Release
버전으로 어떤 코드가 실행되었는지 추적 가능하게 한다.


## 12. 로컬 검증 완료 결과

```text
job_posting_history 처리: 5,757건
직무 분류 성공: 5,757건
기술 추출 성공: 5,757건
job_skill: 11,547행
실패: 0건
중복: 0건
orphan FK: 0건
재실행 대상: 0건
```

