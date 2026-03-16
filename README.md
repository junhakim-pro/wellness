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
