# PC를 꺼도 감시하기: GitHub Actions 방식

현재 로컬 실행은 PC가 꺼지면 멈춥니다. PC를 꺼도 감시하려면 이 폴더 내용을 GitHub 저장소에 올리고, GitHub Actions가 5분마다 실행하게 하면 됩니다.

## 1. GitHub 저장소 만들기

1. GitHub에 로그인합니다.
2. 새 저장소를 만듭니다. 예: `kodex-telegram-monitor`
3. 저장소는 `Private`로 만드는 것을 권장합니다.

## 2. 파일 올리기

이 폴더 안의 파일들을 저장소 최상단에 올립니다.

필수 파일:

- `monitor.py`
- `config.github.json`
- `.github/workflows/kodex-telegram-monitor.yml`

`config.json`은 올리지 마세요. 텔레그램 토큰이 들어 있으므로 로컬 PC에만 두는 편이 좋습니다.

## 3. GitHub Secrets 등록

저장소에서:

1. `Settings`
2. `Secrets and variables`
3. `Actions`
4. `New repository secret`

아래 두 개를 만듭니다.

- `TELEGRAM_BOT_TOKEN`: 텔레그램 봇 토큰
- `TELEGRAM_CHAT_ID`: 내 채팅 ID

## 4. 첫 실행

저장소에서:

1. `Actions`
2. `Kodex Telegram Monitor`
3. `Run workflow`

첫 실행은 현재 검색 결과를 `state.json`에 저장합니다. 기존 글은 알림이 안 오는 것이 정상입니다.

## 5. 이후 동작

GitHub가 약 5분마다 실행합니다.

- 새 글 없음: 알림 없음
- 새 글 있음: 텔레그램 알림 전송
- 알림 보낸 글 ID는 `state.json`에 저장되어 중복 알림 방지

GitHub Actions의 예약 실행은 무료 플랜에서도 대체로 잘 동작하지만, 정확히 5분 정각마다 즉시 실행된다고 보장되지는 않습니다.
