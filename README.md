# 🤖 顏色分揀機械手臂 - Color Sorting Robot Arm

使用 OpenCV 顏色偵測 + ESP32 UDP 控制的顏色分揀機械手臂 Demo 專題。

---

## 系統概覽

攝影機拍到工作區畫面後，Python 端偵測紅、綠、藍色物品，並在物品進入畫面中央準心區域且穩定一定幀數後，透過 UDP 傳送 `PICK:RED / PICK:GREEN / PICK:BLUE` 指令給 ESP32，ESP32 再驅動四顆伺服馬達自動完成夾取與放置。

```
攝影機畫面
   ↓
test_version_2-2.py   → 顏色辨識、狀態機、UDP 自動發現 + 傳送指令
   ↓ UDP Port 8888
sketch_may19a.ino     → 接收指令、驅動四顆伺服馬達、回傳 ACK
```

---

## 硬體需求

| 零件 | 說明 |
|---|---|
| ESP32 開發板 | 接收 UDP 指令，驅動伺服馬達 |
| 伺服馬達 × 4 | M1 底座旋轉、M2 肩關節、M3 肘關節、M4 夾爪 |
| 攝影機 | 筆電內建或 USB webcam |
| 熱點 | 電腦 Wi-Fi 共享 或 **手機 2.4GHz 熱點** |

> ⚠️ **ESP32 只支援 2.4GHz Wi-Fi**，手機熱點請確保開啟 2.4GHz 頻段。

---

## Python 端：`test_version_2-2.py`

### 整體架構

這支程式把所有功能整合在單一檔案，分成幾個獨立區塊：

```
UDP 網路設定
攝影機設定
系統控制參數
HSV 顏色範圍設定
狀態機全域變數
建立 UDP Socket
主迴圈（影像處理 + 狀態機 + 鍵盤控制）
```

---

### 網路模組：UDP 自動發現 + ACK 確認

這版的最大特點是 **不需要手動填寫 ESP32 的 IP**。

啟動時會向廣播位址 `255.255.255.255:8888` 送出 `DISCOVER_ESP32` 封包，同一網段內的 ESP32 收到後會回傳 `ESP32_HERE|IP=...|PORT=...|RSSI=...`，Python 端從回覆封包的來源位址自動記錄 ESP32 的 IP。

```python
ESP_PORT        = 8888          # ESP32 監聽的 UDP Port
LOCAL_PORT      = 8890          # Python 接收 ACK 用的 Port
BROADCAST_IP    = "255.255.255.255"
DISCOVERY_MESSAGE      = "DISCOVER_ESP32"
DISCOVERY_REPLY_PREFIX = "ESP32_HERE"
MANUAL_ESP_IP   = None          # 若不想用自動發現，可改成字串固定 IP
COMMAND_RETRIES = 2             # 送指令失敗後的重試次數
COMMAND_TIMEOUT = 1.0           # 等待 ACK 的逾時秒數
```

**三個核心網路函式：**

| 函式 | 說明 |
|---|---|
| `discover_esp32(force)` | 送廣播封包，自動取得 ESP32 IP，最多重試 3 次 |
| `ensure_esp32_ready()` | 若尚未發現 ESP32 則呼叫 `discover_esp32`，確保 IP 已知 |
| `send_cmd(cmd, expect_reply)` | 送指令給 ESP32，等待 ACK，失敗則重試，最多 `COMMAND_RETRIES` 次 |

**ACK 回傳格式範例：**

| 送出指令 | 收到 ACK |
|---|---|
| `PING` | `PONG\|IP=192.168.x.x\|RSSI=-55` |
| `STATUS` | `STATUS\|IP=...\|GW=...\|RSSI=...\|BUSY=0\|M1=90\|M2=90\|M3=90\|M4=110` |
| `HOME` | `OK\|HOME` |
| `PICK:RED` | `ACK\|PICK_START\|RED` → 動作完成後 `DONE\|PICK\|RED` |
| `M2:45` | `OK\|M2=45` |

---

### 顏色偵測模組

每一幀先做高斯模糊，再轉 HSV，對三個顏色各自建立遮罩，找最大輪廓並取最小外接圓。

```python
# 紅色需要兩段遮罩合併（HSV 環形邊界）
mask_r = cv2.inRange(hsv, lower_red1, upper_red1) + cv2.inRange(hsv, lower_red2, upper_red2)
mask_g = cv2.inRange(hsv, lower_green, upper_green)
mask_b = cv2.inRange(hsv, lower_blue, upper_blue)
```

**可調整的 HSV 範圍：**

| 顏色 | H 範圍 | S 範圍 | V 範圍 |
|---|---|---|---|
| 紅（低段） | 0 ~ 10 | 120 ~ 255 | 70 ~ 255 |
| 紅（高段） | 170 ~ 180 | 120 ~ 255 | 70 ~ 255 |
| 綠 | 40 ~ 80 | 50 ~ 255 | 50 ~ 255 |
| 藍 | 100 ~ 130 | 50 ~ 255 | 50 ~ 255 |

遮罩先做 erode（2次）再 dilate（2次）去除雜訊，輪廓面積小於 `MIN_AREA=250` 或半徑小於 `MIN_RADIUS=12` 的偵測結果直接丟棄。

---

### 狀態機模組

狀態機決定「目前應該做什麼」，共有三個狀態：

```
SEARCH
  ├─ 無目標  → 穩定計數歸零
  ├─ 目標在準心框外 → 顯示 "Place object on cross"
  └─ 目標在準心框內且穩定 LOCK_FRAMES=12 幀
       └─ AUTO_RUN=True → 送 PICK:COLOR → 進入 WAIT_PICK

WAIT_PICK
  └─ 倒數 PICK_WAIT_SECONDS=4.5 秒（等 ESP32 完成動作）
       └─ 進入 WAIT_CLEAR

WAIT_CLEAR
  └─ 等物品離開準心框 CLEAR_FRAMES_REQUIRED=8 幀
       └─ 回到 SEARCH
```

**可調整參數：**

| 參數 | 預設值 | 說明 |
|---|---|---|
| `LOCK_FRAMES` | 12 | 觸發夾取所需的連續穩定幀數 |
| `PICK_WAIT_SECONDS` | 4.5 | 等 ESP32 完成動作的時間（秒） |
| `CLEAR_FRAMES_REQUIRED` | 8 | 確認物品已被移走所需的幀數 |
| `TARGET_ZONE_HALF_W` | 35 | 準心夾取框半寬（像素） |
| `TARGET_ZONE_HALF_H` | 35 | 準心夾取框半高（像素） |
| `TARGET_STABLE_DIST` | 18 | 前後幀判定為「同一目標」的最大位移（像素） |

---

### HUD 顯示

畫面左上角會即時顯示以下資訊：

```
ESP32 IP  : 192.168.x.x
NET       : ACK_OK
State     : LOCKING 8/12
Color     : RED
Zone      : IN
Stable    : 8/12
Clear     : 0/8
AUTO_RUN  : True
LAST CMD  : PICK:RED
LAST ACK  : ACK|PICK_START|RED
```

---

### 鍵盤控制

| 按鍵 | 功能 |
|---|---|
| `q` | 離開程式 |
| `s` | 切換 AUTO_RUN 開/關 |
| `d` | 重新搜尋 ESP32 |
| `p` | PING（測試 ESP32 是否在線） |
| `u` | STATUS（查詢 ESP32 狀態） |
| `h` | HOME（手臂回原點） |
| `o` | OPEN（夾爪打開） |
| `c` | CLOSE（夾爪關閉） |
| `r` / `g` / `b` | 手動觸發紅 / 綠 / 藍夾取 |
| `1` / `2` / `3` / `4` | 手動測試單顆伺服馬達回 90° / 90° / 90° / 110° |
| `z` / `x` | M1 底座微調（BASE:80 / BASE:100） |

---

## ESP32 端：`sketch_may19a.ino`

### 整體架構

```
Wi-Fi 設定（SSID / Password）
UDP 設定（Port 8888）
Servo 角度常數定義
工具函式（isNumericString / replyUdp / getStatusString）
Wi-Fi 連線與斷線重連（connectWiFiDHCP / ensureWiFi）
Servo 動作函式（slowMove / openGripper / closeGripper / goHome / pickAndPlace）
指令處理（handleCommand）
setup / loop
```

---

### Wi-Fi 設定

ESP32 使用 **DHCP 自動取得 IP**，不需要在程式裡寫死固定 IP。

```cpp
const char* ssid     = "你的熱點名稱";
const char* password = "你的熱點密碼";
```

`connectWiFiDHCP()` 連線時會在 Serial Monitor 印出實際取得的 IP、Gateway、Subnet、RSSI，連線逾時（60次重試）後自動重啟連線流程。

`ensureWiFi()` 每 3000 ms 檢查一次 Wi-Fi 狀態，若斷線則自動重連並重新 `Udp.begin(8888)`，整個主迴圈不需要處理斷線問題。

---

### UDP 設定

```cpp
const uint16_t localPort = 8888;        // 監聽 Port
const char* DISCOVERY_MESSAGE = "DISCOVER_ESP32";  // 自動發現觸發字
```

ESP32 在 `loop()` 裡每次呼叫 `Udp.parsePacket()`，收到封包後交給 `handleCommand()` 處理，並用 `replyUdp()` 把回應送回 Python 端的來源 IP + Port。

---

### Servo 角度常數

所有關節位置都用具名常數定義，方便調整：

```cpp
// Home 位置
const int HOME_M1 = 90;   // 底座
const int HOME_M2 = 90;   // 肩關節
const int HOME_M3 = 90;   // 肘關節
const int HOME_M4 = 110;  // 夾爪（半開）

// 夾爪開合
const int GRIP_OPEN  = 115;
const int GRIP_CLOSE = 70;

// 下降夾取
const int PICK_DOWN_M2 = 34;
const int PICK_DOWN_M3 = 90;

// 抬起
const int PICK_UP_M2 = 85;
const int PICK_UP_M3 = 95;

// 放置高度
const int PLACE_DOWN_M2 = 36;
const int PLACE_DOWN_M3 = 70;

// 各顏色放置點的底座角度
const int PLACE_RED_M1   = 40;
const int PLACE_GREEN_M1 = 115;
const int PLACE_BLUE_M1  = 140;
```

**接線對應：**

| 馬達 | GPIO | 功能 |
|---|---|---|
| M1 | GPIO 18 | 底座旋轉 |
| M2 | GPIO 19 | 肩關節 |
| M3 | GPIO 21 | 肘關節 |
| M4 | GPIO 22 | 夾爪 |

---

### Servo 動作函式

**`slowMove(motorID, target)`**

逐步移動伺服馬達，避免瞬間跳角造成機構衝擊。一般馬達每步延遲 `DELAY_BIG=15ms`，夾爪馬達每步延遲 `DELAY_GRIP=10ms`，角度範圍用 `constrain()` 限制在 0～180°。

**`pickAndPlace(color)`**

收到 `PICK:COLOR` 後的完整動作序列：

```
openGripper()
→ slowMove M2 下降（PICK_DOWN_M2=34）
→ slowMove M3（PICK_DOWN_M3=90）
→ closeGripper()
→ slowMove M3 抬起（PICK_UP_M3=95）
→ slowMove M2（PICK_UP_M2=85）
→ slowMove M1 轉到對應顏色放置點
→ slowMove M2 下降（PLACE_DOWN_M2=36）
→ slowMove M3（PLACE_DOWN_M3=70）
→ openGripper()
→ 抬起 → goHome()
```

動作執行期間 `isBusy = true`，這段時間收到其他移動指令一律回傳 `BUSY` 並忽略。

---

### 支援的指令列表

| 指令 | 說明 | ACK 回傳 |
|---|---|---|
| `DISCOVER_ESP32` | 自動發現廣播 | `ESP32_HERE\|IP=...\|PORT=8888\|RSSI=...` |
| `PING` | 連線測試 | `PONG\|IP=...\|RSSI=...` |
| `STATUS` | 查詢目前狀態 | `STATUS\|IP=...\|GW=...\|RSSI=...\|BUSY=0\|M1=90\|...` |
| `HOME` | 回到 Home 姿態 | `OK\|HOME` |
| `OPEN` | 夾爪打開 | `OK\|OPEN` |
| `CLOSE` | 夾爪關閉 | `OK\|CLOSE` |
| `PICK:RED` | 完整夾取紅色並放置 | `ACK\|PICK_START\|RED` → `DONE\|PICK\|RED` |
| `PICK:GREEN` | 完整夾取綠色並放置 | `ACK\|PICK_START\|GREEN` → `DONE\|PICK\|GREEN` |
| `PICK:BLUE` | 完整夾取藍色並放置 | `ACK\|PICK_START\|BLUE` → `DONE\|PICK\|BLUE` |
| `M1:角度` ~ `M4:角度` | 單顆馬達移動 | `OK\|M1=角度` |
| `BASE:角度` | 底座（M1）移動（別名） | `OK\|BASE=角度` |
| `數字` | 直接送數字 → M1 旋轉 | `OK\|BASE=數字` |

---

## 執行前的準備

### 安裝 Python 套件

```bash
pip install opencv-python numpy
```

### 燒錄 ESP32

1. 安裝 Arduino IDE，並安裝 `ESP32Servo` 函式庫。
2. 打開 `sketch_may19a.ino`，修改 `ssid` 和 `password` 為你的熱點名稱與密碼。
3. 燒錄到 ESP32，打開 Serial Monitor（115200），確認出現 `WiFi Connected!` 與 `IP: ...`。

### 換成手機熱點

只需要改 ESP32 程式裡的 `ssid` 和 `password`，讓 ESP32 連上手機熱點即可。  
Python 端因為使用 UDP 廣播自動發現，不需要修改任何 IP 設定。  
手機熱點務必開啟 **2.4GHz 頻段**，ESP32 不支援 5GHz。

---

## 執行方式

```bash
python test_version_2-2.py
```

程式啟動後會自動廣播搜尋 ESP32，找到後 HUD 會顯示 ESP32 IP，即可開始運作。

---

## 常見問題

### ESP32 找不到（NET 顯示 DISCOVER_FAIL）

- 確認 ESP32 的 `ssid` / `password` 和熱點一致。
- 確認 ESP32 Serial Monitor 已出現 `WiFi Connected!`。
- 電腦和 ESP32 必須在同一個熱點底下，不能一個連電腦熱點、一個連手機熱點。

### 顏色偵測不準

- 調整對應顏色的 HSV 範圍（`lower_red1` 等變數）。
- 現場光線盡量穩定，背景避免與目標顏色相近。
- `MIN_AREA` 太小會偵測到雜訊，太大會漏掉小物品，可視情況微調。

### 手臂動作方向不對

- 調整 `PLACE_RED_M1`、`PLACE_GREEN_M1`、`PLACE_BLUE_M1` 三個角度常數。
- 調整 `PICK_DOWN_M2`、`PICK_DOWN_M3` 確認下降深度夠。
- 可用 `r` / `g` / `b` 鍵手動觸發單次夾取測試。

### 夾完一個後不繼續抓

- 確認 `PICK_WAIT_SECONDS`（預設 4.5 秒）比 ESP32 完成整個動作序列的時間長。
- 若動作很慢，把這個值調大。
