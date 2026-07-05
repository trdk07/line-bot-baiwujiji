"""測試共用設定：在載入 app 模組前先給定必要的環境變數。"""

import os

os.environ.setdefault("LINE_CHANNEL_SECRET", "test-secret")
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test-token")
