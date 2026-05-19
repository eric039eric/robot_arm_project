import cv2          # type: ignore
import numpy as np  # type: ignore
import socket
import time

# =========================================================
# UDP / 網路設定
# =========================================================
ESP_PORT = 8888
LOCAL_PORT = 8890
BROADCAST_IP = "255.255.255.255"

DISCOVERY_MESSAGE = "DISCOVER_ESP32"
DISCOVERY_REPLY_PREFIX = "ESP32_HERE"

MANUAL_ESP_IP = None       # 若你想固定指定 ESP32 IP，可改成字串，例如 "192.168.43.123"
SOCKET_TIMEOUT = 0.20
DISCOVERY_TIMEOUT = 2.0
COMMAND_TIMEOUT = 1.0
COMMAND_RETRIES = 2

# =========================================================
# 攝影機設定
# =========================================================
CAMERA_INDEX = 0
WINDOW_NAME = "Auto Color Pick - UDP DHCP + ACK"

# =========================================================
# 系統控制參數
# =========================================================
AUTO_RUN = True
LOCK_FRAMES = 12
PICK_WAIT_SECONDS = 4.5
CLEAR_FRAMES_REQUIRED = 8

MIN_RADIUS = 12
MIN_AREA = 250

TARGET_ZONE_HALF_W = 35
TARGET_ZONE_HALF_H = 35
TARGET_STABLE_DIST = 18

# =========================================================
# HSV 顏色辨識範圍設定
# =========================================================
lower_red1 = np.array([0, 120, 70])
upper_red1 = np.array([10, 255, 255])

lower_red2 = np.array([170, 120, 70])
upper_red2 = np.array([180, 255, 255])

lower_green = np.array([40, 50, 50])
upper_green = np.array([80, 255, 255])

lower_blue = np.array([100, 50, 50])
upper_blue = np.array([130, 255, 255])

# =========================================================
# 狀態機全域變數
# =========================================================
state = "SEARCH"
stable_count = 0
pick_start_time = 0.0
last_cmd = "-"
last_ack = "-"
last_target = None
clear_count = 0
current_esp_ip = MANUAL_ESP_IP
last_net_status = "INIT"

# =========================================================
# 建立 UDP socket
# =========================================================
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
sock.bind(("", LOCAL_PORT))
sock.settimeout(SOCKET_TIMEOUT)

# =========================================================
# 開啟攝影機
# =========================================================
cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
if not cap.isOpened():
    cap = cv2.VideoCapture(CAMERA_INDEX)

# =========================================================
# 啟動資訊
# =========================================================
print("=" * 68)
print("ESP32 Auto Discovery + UDP ACK 版：Fixed Cross Auto Color Pick")
print(f"LOCAL UDP PORT : {LOCAL_PORT}")
print(f"ESP32 UDP PORT : {ESP_PORT}")
print(f"CAMERA INDEX   : {CAMERA_INDEX}")
print(f"AUTO_RUN       : {AUTO_RUN}")
print("=" * 68)
print("快捷鍵:")
print("  q       = 離開程式")
print("  s       = 切換 AUTO_RUN")
print("  d       = 重新搜尋 ESP32")
print("  p       = PING（測試 ESP32 是否在線）")
print("  u       = STATUS（查詢 ESP32 狀態）")
print("  h       = HOME（手臂回原點）")
print("  o       = OPEN（夾爪打開）")
print("  c       = CLOSE（夾爪關閉）")
print("  r/g/b   = 手動觸發紅/綠/藍夾取")
print("  1/2/3/4 = 手動測試單顆伺服馬達回定位")
print("  z/x     = Base 馬達（M1）左右微調")
print("=" * 68)

# =========================================================
# 網路函式
# =========================================================
def recv_reply(timeout_s: float, expected_ip=None, expected_prefix=None):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            remaining = max(0.01, deadline - time.time())
            sock.settimeout(min(SOCKET_TIMEOUT, remaining))
            data, addr = sock.recvfrom(1024)
        except socket.timeout:
            continue
        except Exception:
            return None, None

        text = data.decode("utf-8", errors="ignore").strip()

        if expected_ip is not None and addr[0] != expected_ip:
            continue

        if expected_prefix is not None and not text.startswith(expected_prefix):
            continue

        return text, addr

    return None, None


def discover_esp32(force=False):
    global current_esp_ip, last_ack, last_net_status

    if current_esp_ip is not None and not force:
        return True

    last_net_status = "DISCOVERING"
    print("\n[DISCOVER] Searching ESP32...")

    for attempt in range(3):
        try:
            sock.sendto(DISCOVERY_MESSAGE.encode("utf-8"), (BROADCAST_IP, ESP_PORT))
            reply, addr = recv_reply(DISCOVERY_TIMEOUT, expected_prefix=DISCOVERY_REPLY_PREFIX)
            if reply and addr:
                current_esp_ip = addr[0]
                last_ack = reply
                last_net_status = "DISCOVERED"
                print(f"[DISCOVER] ESP32 found at {current_esp_ip}")
                print(f"[DISCOVER] Reply: {reply}")
                return True
        except Exception as e:
            print(f"[DISCOVER] attempt {attempt + 1} failed: {e}")

    last_net_status = "DISCOVER_FAIL"
    print("[DISCOVER] ESP32 not found")
    return False


def ensure_esp32_ready():
    if current_esp_ip is not None:
        return True
    return discover_esp32(force=True)


def send_cmd(cmd: str, expect_reply=True):
    global last_cmd, last_ack, last_net_status, current_esp_ip

    if not ensure_esp32_ready():
        print(f"SEND FAILED -> {cmd} | ESP32 not discovered")
        last_net_status = "NO_ESP32"
        return False, None

    for attempt in range(COMMAND_RETRIES):
        try:
            sock.sendto(cmd.encode("utf-8"), (current_esp_ip, ESP_PORT))
            last_cmd = cmd
            print(f"SEND -> {cmd} -> {current_esp_ip}:{ESP_PORT}")

            if not expect_reply:
                last_net_status = "SEND_ONLY"
                return True, None

            reply, addr = recv_reply(COMMAND_TIMEOUT, expected_ip=current_esp_ip)
            if reply and addr:
                last_ack = reply
                last_net_status = "ACK_OK"
                print(f"RECV <- {reply} <- {addr[0]}:{addr[1]}")
                return True, reply

            print(f"NO ACK -> {cmd} (attempt {attempt + 1})")
            last_net_status = "NO_ACK"

        except Exception as e:
            print(f"SEND FAILED -> {cmd} | {e}")
            last_net_status = "SEND_ERR"

        if attempt < COMMAND_RETRIES - 1:
            discover_esp32(force=True)

    return False, None

# =========================================================
# 影像處理函式
# =========================================================
def preprocess_mask(mask):
    mask = cv2.erode(mask, None, iterations=2)
    mask = cv2.dilate(mask, None, iterations=2)
    return mask


def find_target(mask, frame, color_name, draw_color):
    mask = preprocess_mask(mask)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if len(contours) == 0:
        return None

    c = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(c)

    if area < MIN_AREA:
        return None

    (center, radius) = cv2.minEnclosingCircle(c)
    cx, cy = center

    if radius < MIN_RADIUS:
        return None

    cv2.circle(frame, (int(cx), int(cy)), int(radius), draw_color, 2)
    cv2.putText(
        frame,
        color_name,
        (int(cx) - 20, int(cy) - 18),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        draw_color,
        2,
    )

    return {
        "color": color_name,
        "cx": int(cx),
        "cy": int(cy),
        "radius": float(radius),
        "area": float(area),
    }


def choose_target(targets, center_x, center_y):
    valid = [t for t in targets if t is not None]
    if not valid:
        return None

    def score(t):
        dist = abs(t["cx"] - center_x) + abs(t["cy"] - center_y)
        area_bonus = t["area"] * 0.002
        return dist - area_bonus

    return min(valid, key=score)


def update_stable_count(target):
    global stable_count, last_target

    if target is None:
        stable_count = 0
        last_target = None
        return

    if last_target is None:
        stable_count = 1
    else:
        same_color = target["color"] == last_target["color"]
        close_enough = (
            abs(target["cx"] - last_target["cx"]) <= TARGET_STABLE_DIST
            and abs(target["cy"] - last_target["cy"]) <= TARGET_STABLE_DIST
        )

        if same_color and close_enough:
            stable_count += 1
        else:
            stable_count = 1

    last_target = {
        "color": target["color"],
        "cx": target["cx"],
        "cy": target["cy"],
    }


def is_target_in_pick_zone(target, center_x, center_y):
    if target is None:
        return False

    error_x = target["cx"] - center_x
    error_y = target["cy"] - center_y
    return abs(error_x) <= TARGET_ZONE_HALF_W and abs(error_y) <= TARGET_ZONE_HALF_H


def reset_search_state():
    global state, stable_count, last_target, clear_count
    state = "SEARCH"
    stable_count = 0
    last_target = None
    clear_count = 0

# =========================================================
# 啟動時先搜尋一次 ESP32
# =========================================================
discover_esp32(force=True)

# =========================================================
# 攝影機驗證
# =========================================================
if not cap.isOpened():
    print("無法開啟攝影機，請檢查 CAMERA_INDEX。")
    sock.close()
    raise SystemExit

# =========================================================
# 主迴圈
# =========================================================
while True:
    ret, frame = cap.read()
    if not ret:
        print("讀不到攝影機畫面，程式結束。")
        break

    h, w, _ = frame.shape
    center_x = w // 2
    center_y = h // 2

    # 十字準線
    cv2.line(frame, (center_x, 0), (center_x, h), (255, 255, 255), 1)
    cv2.line(frame, (0, center_y), (w, center_y), (255, 255, 255), 1)

    # 固定夾取區
    box_left = center_x - TARGET_ZONE_HALF_W
    box_right = center_x + TARGET_ZONE_HALF_W
    box_top = center_y - TARGET_ZONE_HALF_H
    box_bottom = center_y + TARGET_ZONE_HALF_H

    cv2.rectangle(frame, (box_left, box_top), (box_right, box_bottom), (0, 255, 255), 2)
    cv2.putText(
        frame,
        "FIXED PICK ZONE",
        (box_left - 10, box_top - 8),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 255, 255),
        2,
    )

    # 前處理
    blurred = cv2.GaussianBlur(frame, (11, 11), 0)
    hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)

    # 顏色遮罩
    mask_r = cv2.inRange(hsv, lower_red1, upper_red1) + cv2.inRange(hsv, lower_red2, upper_red2)
    mask_g = cv2.inRange(hsv, lower_green, upper_green)
    mask_b = cv2.inRange(hsv, lower_blue, upper_blue)

    # 找目標
    target_r = find_target(mask_r, frame, "RED", (0, 0, 255))
    target_g = find_target(mask_g, frame, "GREEN", (0, 255, 0))
    target_b = find_target(mask_b, frame, "BLUE", (255, 0, 0))

    target = choose_target([target_r, target_g, target_b], center_x, center_y)

    status_msg = "SEARCH"
    color_msg = "-"
    zone_msg = "OUT"

    in_pick_zone = is_target_in_pick_zone(target, center_x, center_y)

    if target is not None:
        color_msg = target["color"]
        zone_msg = "IN" if in_pick_zone else "OUT"

    # =========================================================
    # 狀態機邏輯
    # =========================================================
    if state == "WAIT_PICK":
        remain = PICK_WAIT_SECONDS - (time.time() - pick_start_time)
        if remain <= 0:
            state = "WAIT_CLEAR"
            clear_count = 0
            stable_count = 0
            last_target = None
        else:
            status_msg = f"WAIT_PICK {remain:.1f}s"

    elif state == "WAIT_CLEAR":
        if in_pick_zone:
            clear_count = 0
            status_msg = "WAIT_REMOVE_OBJECT"
        else:
            clear_count += 1
            status_msg = f"WAIT_CLEAR {clear_count}/{CLEAR_FRAMES_REQUIRED}"
            if clear_count >= CLEAR_FRAMES_REQUIRED:
                state = "SEARCH"
                clear_count = 0
                stable_count = 0
                last_target = None
                status_msg = "READY_NEXT_OBJECT"

    elif state == "SEARCH":
        if target is None:
            stable_count = 0
            last_target = None
            status_msg = "SEARCH -> No target"
        else:
            if in_pick_zone:
                update_stable_count(target)
                status_msg = f"LOCKING {stable_count}/{LOCK_FRAMES}"
                cv2.circle(frame, (target["cx"], target["cy"]), 6, (0, 255, 255), -1)
            else:
                stable_count = 0
                last_target = None
                status_msg = "Place object on cross"

        if in_pick_zone and stable_count >= LOCK_FRAMES and AUTO_RUN:
            cmd = f"PICK:{target['color']}"
            print(f"Detected color: {target['color']}")
            ok, reply = send_cmd(cmd, expect_reply=True)

            if ok:
                pick_start_time = time.time()
                state = "WAIT_PICK"
                stable_count = 0
                last_target = None
                clear_count = 0
                status_msg = f"SEND {cmd}"
            else:
                status_msg = "UDP SEND FAILED"

    # =========================================================
    # HUD
    # =========================================================
    hud_lines = [
        f"ESP32 IP : {current_esp_ip if current_esp_ip else 'NOT FOUND'}",
        f"NET      : {last_net_status}",
        f"State    : {status_msg}",
        f"Color    : {color_msg}",
        f"Zone     : {zone_msg}",
        f"Stable   : {stable_count}/{LOCK_FRAMES}",
        f"Clear    : {clear_count}/{CLEAR_FRAMES_REQUIRED}",
        f"AUTO_RUN : {AUTO_RUN}",
        f"LAST CMD : {last_cmd}",
        f"LAST ACK : {last_ack[:45]}",
    ]

    y = 30
    for i, line in enumerate(hud_lines):
        color = (255, 255, 255)
        if i == 0:
            color = (255, 255, 0)
        elif i == 1:
            color = (0, 255, 255)
        elif "Zone" in line:
            color = (0, 255, 0) if zone_msg == "IN" else (0, 0, 255)

        cv2.putText(frame, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.60, color, 2)
        y += 28

    cv2.imshow(WINDOW_NAME, frame)

    # =========================================================
    # 鍵盤控制
    # =========================================================
    key = cv2.waitKey(1) & 0xFF

    if key == ord("q"):
        break

    elif key == ord("s"):
        AUTO_RUN = not AUTO_RUN
        stable_count = 0
        last_target = None
        clear_count = 0
        if state != "WAIT_PICK":
            state = "SEARCH"
        print("AUTO_RUN =", AUTO_RUN)

    elif key == ord("d"):
        discover_esp32(force=True)

    elif key == ord("p"):
        send_cmd("PING")

    elif key == ord("u"):
        send_cmd("STATUS")

    elif key == ord("h"):
        send_cmd("HOME")

    elif key == ord("o"):
        send_cmd("OPEN")

    elif key == ord("c"):
        send_cmd("CLOSE")

    elif key == ord("r"):
        send_cmd("PICK:RED")

    elif key == ord("g"):
        send_cmd("PICK:GREEN")

    elif key == ord("b"):
        send_cmd("PICK:BLUE")

    elif key == ord("1"):
        send_cmd("M1:90")

    elif key == ord("2"):
        send_cmd("M2:90")

    elif key == ord("3"):
        send_cmd("M3:90")

    elif key == ord("4"):
        send_cmd("M4:110")

    elif key == ord("z"):
        send_cmd("BASE:80")

    elif key == ord("x"):
        send_cmd("BASE:100")

# =========================================================
# 程式結束
# =========================================================
cap.release()
cv2.destroyAllWindows()
sock.close()