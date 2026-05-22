#include <WiFi.h>
#include <WiFiUdp.h>
#include <ESP32Servo.h>

// =========================================================
// Wi-Fi 設定
// =========================================================
const char* ssid = "xxxxxxxxxxx";
const char* password = "xxxxxxxxxx";

// =========================================================
// UDP 設定
// =========================================================
WiFiUDP Udp;
const uint16_t localPort = 8888;
char packetBuffer[128];

const char* DISCOVERY_MESSAGE = "DISCOVER_ESP32";

// =========================================================
// Servo 設定
// =========================================================
Servo servos[4];
int pins[4] = {18, 19, 21, 22};
int angles[4] = {90, 90, 90, 110};

const int HOME_M1 = 90;
const int HOME_M2 = 90;
const int HOME_M3 = 90;
const int HOME_M4 = 110;

const int GRIP_OPEN = 115;
const int GRIP_CLOSE = 70;

const int PICK_DOWN_M2 = 34;
const int PICK_DOWN_M3 = 90;
const int PICK_UP_M2 = 85;
const int PICK_UP_M3 = 95;

const int PLACE_DOWN_M2 = 36;
const int PLACE_DOWN_M3 = 70;

const int PLACE_RED_M1 = 40;
const int PLACE_GREEN_M1 = 115;
const int PLACE_BLUE_M1 = 140;

const int DELAY_BIG = 15;
const int DELAY_GRIP = 10;

bool isBusy = false;

// =========================================================
// 工具函式
// =========================================================
bool isNumericString(String s) {
  s.trim();
  if (s.length() == 0) return false;
  for (int i = 0; i < s.length(); i++) {
    if (!isDigit(s[i])) return false;
  }
  return true;
}

void replyUdp(const String& msg, IPAddress remoteIP, uint16_t remotePort) {
  if (remotePort == 0) return;
  Udp.beginPacket(remoteIP, remotePort);
  Udp.print(msg);
  Udp.endPacket();
}

String getStatusString() {
  String status = "STATUS";
  status += "|IP=" + WiFi.localIP().toString();
  status += "|GW=" + WiFi.gatewayIP().toString();
  status += "|RSSI=" + String(WiFi.RSSI());
  status += "|BUSY=" + String(isBusy ? 1 : 0);
  status += "|M1=" + String(angles[0]);
  status += "|M2=" + String(angles[1]);
  status += "|M3=" + String(angles[2]);
  status += "|M4=" + String(angles[3]);
  return status;
}

void printStatus() {
  Serial.println(getStatusString());
}

// =========================================================
// Wi-Fi
// =========================================================
void connectWiFiDHCP() {
  Serial.println("Connecting to WiFi with DHCP...");

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.disconnect(true, true);
  delay(300);

  WiFi.begin(ssid, password);

  int retry = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    retry++;

    if (retry >= 60) {
      Serial.println("\nWiFi connect timeout, retrying...");
      WiFi.disconnect();
      delay(500);
      WiFi.begin(ssid, password);
      retry = 0;
    }
  }

  Serial.println("\nWiFi Connected!");
  Serial.print("SSID   : ");
  Serial.println(ssid);
  Serial.print("IP     : ");
  Serial.println(WiFi.localIP());
  Serial.print("Gateway: ");
  Serial.println(WiFi.gatewayIP());
  Serial.print("Subnet : ");
  Serial.println(WiFi.subnetMask());
  Serial.print("RSSI   : ");
  Serial.println(WiFi.RSSI());
}

void ensureWiFi() {
  static unsigned long lastCheck = 0;
  if (millis() - lastCheck < 3000) return;
  lastCheck = millis();

  if (WiFi.status() == WL_CONNECTED) return;

  Serial.println("WiFi lost, reconnecting...");
  WiFi.disconnect();
  delay(200);
  WiFi.begin(ssid, password);

  int retry = 0;
  while (WiFi.status() != WL_CONNECTED && retry < 20) {
    delay(500);
    Serial.print("#");
    retry++;
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Reconnected IP: ");
    Serial.println(WiFi.localIP());
    Udp.begin(localPort);
    Serial.printf("UDP listening on %u\n", localPort);
  } else {
    Serial.println("Reconnect failed.");
  }
}

// =========================================================
// Servo 動作
// =========================================================
void slowMove(int motorID, int target) {
  if (motorID < 1 || motorID > 4) return;

  int idx = motorID - 1;
  target = constrain(target, 0, 180);

  if (abs(target - angles[idx]) <= 1) {
    servos[idx].write(target);
    angles[idx] = target;
    return;
  }

  int d = (motorID == 4) ? DELAY_GRIP : DELAY_BIG;

  if (angles[idx] < target) {
    for (int p = angles[idx]; p <= target; p++) {
      servos[idx].write(p);
      delay(d);
    }
  } else {
    for (int p = angles[idx]; p >= target; p--) {
      servos[idx].write(p);
      delay(d);
    }
  }

  angles[idx] = target;
}

void openGripper() {
  slowMove(4, GRIP_OPEN);
}

void closeGripper() {
  slowMove(4, GRIP_CLOSE);
}

void goHome() {
  openGripper();
  slowMove(3, HOME_M3);
  slowMove(2, HOME_M2);
  slowMove(1, HOME_M1);
  slowMove(4, HOME_M4);
}

int getPlaceBaseByColor(String color) {
  color.toUpperCase();
  if (color == "RED") return PLACE_RED_M1;
  if (color == "GREEN") return PLACE_GREEN_M1;
  if (color == "BLUE") return PLACE_BLUE_M1;
  return HOME_M1;
}

void pickAndPlace(String color) {
  if (isBusy) {
    Serial.println("PICK ignored: BUSY");
    return;
  }

  isBusy = true;
  color.toUpperCase();

  Serial.print("PICK START -> ");
  Serial.println(color);

  openGripper();
  slowMove(2, PICK_DOWN_M2);
  slowMove(3, PICK_DOWN_M3);
  delay(150);

  closeGripper();
  delay(250);

  slowMove(3, PICK_UP_M3);
  slowMove(2, PICK_UP_M2);

  slowMove(1, getPlaceBaseByColor(color));
  slowMove(2, PLACE_DOWN_M2);
  slowMove(3, PLACE_DOWN_M3);
  delay(150);

  openGripper();
  delay(250);

  slowMove(3, PICK_UP_M3);
  slowMove(2, PICK_UP_M2);
  goHome();

  Serial.print("PICK DONE -> ");
  Serial.println(color);

  isBusy = false;
}

// =========================================================
// 指令處理
// =========================================================
void handleCommand(String cmd, String source, bool viaUdp, IPAddress remoteIP, uint16_t remotePort) {
  cmd.trim();
  if (cmd.length() == 0) return;

  String ucmd = cmd;
  ucmd.toUpperCase();

  Serial.print(source);
  Serial.print(" RX -> ");
  Serial.println(ucmd);

  if (ucmd == DISCOVERY_MESSAGE) {
    String msg = "ESP32_HERE|IP=" + WiFi.localIP().toString() + "|PORT=" + String(localPort) + "|RSSI=" + String(WiFi.RSSI());
    replyUdp(msg, remoteIP, remotePort);
    return;
  }

  if (ucmd == "PING") {
    Serial.println("PONG");
    if (viaUdp) {
      String msg = "PONG|IP=" + WiFi.localIP().toString() + "|RSSI=" + String(WiFi.RSSI());
      replyUdp(msg, remoteIP, remotePort);
    }
    return;
  }

  if (ucmd == "STATUS") {
    printStatus();
    if (viaUdp) {
      replyUdp(getStatusString(), remoteIP, remotePort);
    }
    return;
  }

  if (ucmd == "HOME") {
    goHome();
    printStatus();
    if (viaUdp) replyUdp("OK|HOME", remoteIP, remotePort);
    return;
  }

  if (ucmd == "OPEN") {
    openGripper();
    printStatus();
    if (viaUdp) replyUdp("OK|OPEN", remoteIP, remotePort);
    return;
  }

  if (ucmd == "CLOSE") {
    closeGripper();
    printStatus();
    if (viaUdp) replyUdp("OK|CLOSE", remoteIP, remotePort);
    return;
  }

  if (ucmd == "PICK:RED" || ucmd == "PICK:GREEN" || ucmd == "PICK:BLUE") {
    String color = ucmd.substring(5);

    if (isBusy) {
      Serial.println("IGNORED: BUSY");
      if (viaUdp) replyUdp("BUSY|PICK", remoteIP, remotePort);
      return;
    }

    if (viaUdp) replyUdp("ACK|PICK_START|" + color, remoteIP, remotePort);
    pickAndPlace(color);
    printStatus();
    if (viaUdp) replyUdp("DONE|PICK|" + color, remoteIP, remotePort);
    return;
  }

  if (isBusy) {
    if (ucmd.startsWith("BASE:") || ucmd.startsWith("M") || isNumericString(ucmd)) {
      Serial.println("IGNORED: BUSY");
      if (viaUdp) replyUdp("BUSY", remoteIP, remotePort);
      return;
    }
  }

  if (isNumericString(ucmd)) {
    int angle = ucmd.toInt();
    slowMove(1, angle);
    printStatus();
    if (viaUdp) replyUdp("OK|BASE=" + String(angle), remoteIP, remotePort);
    return;
  }

  if (ucmd.startsWith("BASE:")) {
    int angle = ucmd.substring(5).toInt();
    slowMove(1, angle);
    printStatus();
    if (viaUdp) replyUdp("OK|BASE=" + String(angle), remoteIP, remotePort);
    return;
  }

  if (ucmd.startsWith("M")) {
    int colon = ucmd.indexOf(':');
    if (colon > 1) {
      int motorID = ucmd.substring(1, colon).toInt();
      int angle = ucmd.substring(colon + 1).toInt();

      if (motorID >= 1 && motorID <= 4) {
        slowMove(motorID, angle);
        printStatus();
        if (viaUdp) replyUdp("OK|M" + String(motorID) + "=" + String(angle), remoteIP, remotePort);
        return;
      }
    }
  }

  Serial.println("Unknown command");
  if (viaUdp) replyUdp("ERR|UNKNOWN_CMD", remoteIP, remotePort);
}

// =========================================================
// setup / loop
// =========================================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("=== ESP32 Auto Pick Controller (DHCP + UDP ACK + DISCOVERY) ===");

  for (int i = 0; i < 4; i++) {
    servos[i].setPeriodHertz(50);
    servos[i].attach(pins[i], 500, 2400);
    servos[i].write(angles[i]);
    Serial.printf("Servo %d attached on D%d, angle=%d\n", i + 1, pins[i], angles[i]);
    delay(400);
  }

  connectWiFiDHCP();

  Udp.begin(localPort);
  Serial.printf("UDP listening on %u\n", localPort);

  goHome();
  printStatus();
}

void loop() {
  ensureWiFi();

  if (Serial.available() > 0) {
    String serialCmd = Serial.readStringUntil('\n');
    handleCommand(serialCmd, "SERIAL", false, IPAddress(0, 0, 0, 0), 0);
  }

  int packetSize = Udp.parsePacket();
  if (packetSize > 0) {
    IPAddress remoteIP = Udp.remoteIP();
    uint16_t remotePort = Udp.remotePort();

    int len = Udp.read(packetBuffer, sizeof(packetBuffer) - 1);
    if (len > 0) {
      packetBuffer[len] = '\0';
      String udpCmd = String(packetBuffer);
      handleCommand(udpCmd, "UDP", true, remoteIP, remotePort);
    }
  }
}