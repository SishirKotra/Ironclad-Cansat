// Ironclad CanSat flight logic (simulation build for Wokwi, ESP32-C3).
// Height is simulated until the BME280 is wired; the real build replaces fakeHeight()
// with the pressure altitude from the BME280.
//
// Wokwi wiring: LED + 220 ohm on GPIO 4 (stands in for the MOSFET + nichrome),
// buzzer on GPIO 5, pushbutton from GPIO 3 to GND (press = the drone lets go).

const int BURN_PIN = 4;
const int BUZZ_PIN = 5;
const int DROP_BTN = 3;

enum State { ON_DRONE, BURNING, DESCENT, LANDED };
State state = ON_DRONE;
const char* NAMES[] = {"ON_DRONE", "BURNING", "DESCENT", "LANDED"};

bool released = false, chuteOpen = false;
float h = 500, v = 0, maxH = 500;
unsigned long tLast, tBurn, tPacket = 0;

float fakeHeight(float dt) {             // same physics as the Colab notebook
  if (!released || h <= 0) return h;
  float cdA = 0.8 * 0.00342 + (chuteOpen ? 0.8 * 0.196 : 0);
  float a = 9.81 - 0.5 * 1.15 * v * v * cdA / 0.30;
  v += a * dt;  h -= v * dt;
  if (h < 0) { h = 0; v = 0; }
  return h;
}

void setup() {
  Serial.begin(115200);
  pinMode(BURN_PIN, OUTPUT);
  pinMode(BUZZ_PIN, OUTPUT);
  pinMode(DROP_BTN, INPUT_PULLUP);
  tLast = millis();
}

void loop() {
  unsigned long now = millis();
  float dt = (now - tLast) / 1000.0;  tLast = now;
  if (digitalRead(DROP_BTN) == LOW) released = true;
  float height = fakeHeight(dt);
  if (height > maxH) maxH = height;

  switch (state) {
    case ON_DRONE:                       // fire once we have fallen 10 m
      if (height < maxH - 10) { digitalWrite(BURN_PIN, HIGH); tBurn = now; state = BURNING; }
      break;
    case BURNING:                        // 2 s to cut the thread
      if (now - tBurn > 2000) { digitalWrite(BURN_PIN, LOW); chuteOpen = true; state = DESCENT; }
      break;
    case DESCENT:
      if (height <= 0.5) state = LANDED;
      break;
    case LANDED:
      break;
  }
  if (now - tPacket >= 1000) {           // one telemetry line per second
    tPacket = now;
    Serial.printf("%lu,%s,%.1f,%.1f\n", now / 1000, NAMES[state], height, v);
    if (state == LANDED) tone(BUZZ_PIN, 2000, 300);   // beep so the team can find it
  }
  delay(10);
}
