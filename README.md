# Wellness Log

웰니스 기록 서비스 프로젝트입니다.

- 프런트엔드: GitHub Pages에 올리는 `index.html`
- 백엔드: Alibaba Function Compute에 배포하는 `app.py`
- 데이터 저장소: Alibaba TableStore
- 봇 연동: Telegram Bot

## 현재 파일

- `index.html`: 웹 화면
- `app.py`: Flask 백엔드
- `app.py.html`: 예전 HTML 저장본

## 환경변수

Alibaba Function Compute 환경변수에 아래 값을 넣어야 합니다.

- `ACCESS_KEY_ID`
- `ACCESS_KEY_SECRET`
- `INSTANCE_NAME`
- `ENDPOINT`
- `TELEGRAM_TOKEN`
- `TABLE_NAME`
- `ADMIN_DASHBOARD_KEY` 관리자 usage 대시보드 조회 키

선택 환경변수:

- `AI_INPUT_COST_PER_MTOKEN` AI 입력 100만 토큰당 USD 단가
- `AI_OUTPUT_COST_PER_MTOKEN` AI 출력 100만 토큰당 USD 단가
- `FUNCTION_REQUEST_COST_PER_MILLION` Function Compute 요청 100만 건당 USD 단가
- `TABLESTORE_WRITE_COST_PER_10K` TableStore write 1만 건당 USD 단가
- `USAGE_SYSTEM_USER_ID` usage 이벤트를 저장할 시스템 user id (기본값 `__usage__`)

기본값 메모:

- AI 입력/출력 단가는 현재 `qwen-plus`의 일반적인 짧은 요청 구간 기준값으로 잡혀 있습니다.
- Function Compute 요청 단가는 기본값이 `0`이며, 실제 내부 기준이 있으면 `FUNCTION_REQUEST_COST_PER_MILLION`에 넣어서 켭니다.

현재 사용값 메모:

- `INSTANCE_NAME = wellness-db`
- `ENDPOINT = https://wellness-db.ap-northeast-2.ots.aliyuncs.com`
- `TABLE_NAME = wellness_logs`

## 작업 원칙

앞으로는 이 폴더를 원본으로 사용합니다.

1. 로컬 파일 수정
2. GitHub에 `index.html` 반영
3. Alibaba에 `app.py` 반영
4. 실제 서비스 테스트

클라우드에서 직접 수정했다면, 로컬 파일에도 같은 내용을 꼭 반영합니다.

## GitHub 반영

보통 `index.html`을 GitHub Pages 저장소에 반영합니다.

기본 흐름:

1. GitHub 저장소 `Code` 탭 열기
2. `index.html` 수정 또는 업로드
3. `Commit changes`

## Alibaba 반영

보통 Function Compute 웹 편집기에서 `app.py`를 반영합니다.

기본 흐름:

1. Alibaba Cloud Console
2. Function Compute
3. 서비스/함수 선택
4. `app.py` 열기
5. 로컬의 `app.py` 내용 붙여넣기
6. `Save & Deploy`

## 관리자 usage / 비용 확인

- 백엔드 환경변수에 `ADMIN_DASHBOARD_KEY`를 넣습니다.
- `app.py`를 Alibaba Function Compute에 다시 `Save & Deploy` 합니다.
- GitHub Pages 쪽 `index.html`도 반영합니다.
- 관리자만 `?admin=1`을 붙여 접속합니다.
예시: `https://<your-pages-url>/?admin=1`
- 화면 하단의 Admin Usage 카드에서 관리자 키를 입력하면 최근 24시간 / 7일 / 전체 기준 사용량과 예상 비용을 볼 수 있습니다.

주의:

- AI 비용은 실제 응답 토큰 usage 기준 추정치입니다.
- Function Compute 비용은 현재 요청 수 기준 추정만 포함합니다. 실행 시간, 네트워크 등은 별도 계산이 필요할 수 있습니다.
- TableStore 비용은 `TABLESTORE_WRITE_COST_PER_10K`를 넣은 경우에만 총 비용 추정에 반영됩니다.

## 테스트 방법

### 백엔드 조회 테스트

예시:

`https://wellnesot-brain-unwrkhiccv.ap-northeast-2.fcapp.run/?user_id=내텔레그램ID`

- `[]` 이면 서버는 동작 중
- JSON 데이터가 보이면 조회 성공

### 텔레그램 테스트

1. 봇에 메시지 보내기
2. 답장 확인
3. 조회 API에서 기록 확인

### 웹 저장 테스트

1. 웹사이트 로그인
2. 아침 리포트 또는 음료 기록 저장
3. 새로고침 후 기록 유지 확인
4. 다른 브라우저에서도 보이면 서버 저장 성공

## 주의사항

- 비밀키를 코드에 직접 넣지 않기
- GitHub에 토큰/Access Key 올리지 않기
- 화면 캡처 공유 시 환경변수 값 가리기
