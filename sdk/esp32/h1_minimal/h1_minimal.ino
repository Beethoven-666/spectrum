// h1_minimal.ino -- minimal Arduino-ESP32-S3 sketch for the H1 spectrometer.
//
// Wiring -- use the pinout from page 2 of HYD1硬件接口说明.pdf (the J2 table),
// NOT page 1. Page 1 swaps the pin numbering end-to-end and produces reverse
// polarity on VCC/GND, which destroys the sensor in seconds.
//
//   FPC pin  Signal       ESP32-S3
//   -------  -----------  -------------------------
//   1        GND          GND
//   2        RESET        GPIO5 (optional)
//   3        VCC_3.3V     3V3
//   4        RXD0         GPIO17 (this sketch's H1_TX_PIN)
//   5        TXD0         GPIO18 (this sketch's H1_RX_PIN)
//   6        Trigger      GPIO4  (optional, only for trigger mode)
//   7        GND          GND    (optional second ground)
//   12       VCC_3.3V     3V3    (optional second VCC)
//
// Power note: if you turn WiFi/BLE on while powering the sensor from the
// dev board's 3V3, the LDO can brown out. For reliability, drive the
// sensor from a separate AMS1117-3.3 (or similar) and share GND.
//
// Build: Arduino IDE with esp32 board package (board: "ESP32S3 Dev Module"),
// or PlatformIO. C++11+ is enough.

#include <Arduino.h>

// -------- pin/uart configuration ----------------------------------------
static const int      H1_RX_PIN = 18;       // ESP32-S3 RX <- device TXD0 (FPC 8)
static const int      H1_TX_PIN = 17;       // ESP32-S3 TX -> device RXD0 (FPC 9)
static const uint32_t H1_BAUD   = 115200;
static const size_t   H1_RXBUF  = 8192;     // must be > max frame (~4 KB w/ TM30)

HardwareSerial& H1 = Serial1;               // use UART1

// -------- protocol primitives -------------------------------------------
static const uint8_t HDR0 = 0xCC, CMD_HDR1 = 0x01, RSP_HDR1 = 0x81;
static const uint8_t FT0  = 0x0D, FT1      = 0x0A;

static uint8_t checksum(const uint8_t* p, size_t n) {
    uint16_t s = 0;
    for (size_t i = 0; i < n; ++i) s += p[i];
    return s & 0xFF;
}

// Build a command frame into `out`. Returns total bytes written.
// Frame: CC 01 | totalLen(3 LE) | cmdType | [data...] | checksum | 0D 0A
static size_t buildCmd(uint8_t* out, uint8_t cmdType,
                       const uint8_t* data, size_t dataLen) {
    size_t total = 9 + dataLen;
    out[0] = HDR0;
    out[1] = CMD_HDR1;
    out[2] = total & 0xFF;
    out[3] = (total >> 8) & 0xFF;
    out[4] = (total >> 16) & 0xFF;
    out[5] = cmdType;
    if (dataLen) memcpy(out + 6, data, dataLen);
    out[6 + dataLen] = checksum(out, 6 + dataLen);
    out[7 + dataLen] = FT0;
    out[8 + dataLen] = FT1;
    return total;
}

static bool readExact(uint8_t* dst, size_t n, uint32_t timeoutMs) {
    uint32_t start = millis();
    size_t got = 0;
    while (got < n) {
        if (millis() - start > timeoutMs) return false;
        int r = H1.read();
        if (r >= 0) dst[got++] = (uint8_t)r;
        else        delay(1);
    }
    return true;
}

// Read one full response frame. Returns total length on success, 0 on error.
static size_t readFrame(uint8_t* out, size_t outMax, uint32_t timeoutMs) {
    if (!readExact(out, 5, timeoutMs)) {
        Serial.println(F("[frame] preamble timeout"));
        return 0;
    }
    if (out[0] != HDR0 || out[1] != RSP_HDR1) {
        Serial.printf("[frame] bad header %02X %02X\n", out[0], out[1]);
        return 0;
    }
    size_t totalLen = (size_t)out[2] | ((size_t)out[3] << 8) | ((size_t)out[4] << 16);
    if (totalLen < 9 || totalLen > outMax) {
        Serial.printf("[frame] bad totalLen=%u\n", (unsigned)totalLen);
        return 0;
    }
    if (!readExact(out + 5, totalLen - 5, timeoutMs)) {
        Serial.println(F("[frame] body timeout"));
        return 0;
    }
    uint8_t expected = checksum(out, totalLen - 3);
    uint8_t got      = out[totalLen - 3];
    if (expected != got) {
        Serial.printf("[frame] bad checksum %02X != %02X\n", expected, got);
        return 0;
    }
    if (out[totalLen - 2] != FT0 || out[totalLen - 1] != FT1) {
        Serial.println(F("[frame] bad footer"));
        return 0;
    }
    return totalLen;
}

// Send a command and read its response into respBuf. Returns frame length or 0.
static size_t txrx(uint8_t cmdType, const uint8_t* data, size_t dataLen,
                   uint8_t* respBuf, size_t respMax, uint32_t timeoutMs) {
    uint8_t txBuf[32];
    size_t  n = buildCmd(txBuf, cmdType, data, dataLen);
    while (H1.read() >= 0) {}   // drain any stray bytes
    H1.write(txBuf, n);
    H1.flush();
    return readFrame(respBuf, respMax, timeoutMs);
}

// -------- typed helpers --------------------------------------------------
static uint16_t wlStart = 0;
static uint16_t wlEnd   = 0;

static void cmdDeviceInfo() {
    uint8_t buf[64];
    uint8_t arg = 0x18;  // request 24 bytes
    size_t n = txrx(0x08, &arg, 1, buf, sizeof(buf), 500);
    if (!n) return;
    const uint8_t* vd = buf + 6;
    size_t vdLen = n - 9;
    Serial.print(F("device info: "));
    for (size_t i = 0; i < vdLen; ++i) Serial.write(vd[i]);
    Serial.println();
}

static void cmdWavelengthRange() {
    uint8_t buf[32];
    size_t n = txrx(0x0F, nullptr, 0, buf, sizeof(buf), 500);
    if (!n) return;
    const uint8_t* vd = buf + 6;
    wlStart = (uint16_t)vd[0] | ((uint16_t)vd[1] << 8);
    wlEnd   = (uint16_t)vd[2] | ((uint16_t)vd[3] << 8);
    Serial.printf("wavelength range: %u-%u nm (count=%u)\n",
                  wlStart, wlEnd, (unsigned)(wlEnd - wlStart + 1));
}

// Single-capture (no TM30) -- cmd 0x32. Layout of validData:
//   [0]                  exposure status (u8, 0=ok / 1=overexposed / 2=underexposed)
//   [1..5)               exposure time us (u32 LE)
//   [5..193)             47 photometric params (float LE)
//   [193..197)           blue hazard Eb (float)
//   [197..209)           3 NIR floats
//   [209..273)           16 plant-light floats
//   [273..275)           spectrum coefficient N (int16 LE)
//   [275..275+count*2)   spectrum samples (u16 LE), one per nm
static void cmdCaptureSingle() {
    static uint8_t buf[8192];   // big enough for full 340-1050 nm range
    size_t n = txrx(0x32, nullptr, 0, buf, sizeof(buf), 10000);
    if (!n) return;

    const uint8_t* vd     = buf + 6;
    uint8_t        status = vd[0];
    uint32_t       expUs  = (uint32_t)vd[1]       | ((uint32_t)vd[2] << 8)
                          | ((uint32_t)vd[3] << 16) | ((uint32_t)vd[4] << 24);
    int16_t        N      = (int16_t)((uint16_t)vd[273] | ((uint16_t)vd[274] << 8));
    size_t         count  = (size_t)(wlEnd - wlStart + 1);
    const uint8_t* spec   = vd + 275;

    float scale = 1.0f;
    for (int i = 0; i < N; ++i) scale *= 0.1f;     // divide by 10^N

    Serial.printf("status=%u exposureUs=%lu N=%d samples=%u\n",
                  status, (unsigned long)expUs, (int)N, (unsigned)count);
    Serial.println(F("first 10 samples (nm: raw / scaled):"));
    for (size_t i = 0; i < 10 && i < count; ++i) {
        uint16_t raw = (uint16_t)spec[i*2] | ((uint16_t)spec[i*2 + 1] << 8);
        Serial.printf("  %4u nm : %5u  /  %.3f\n",
                      (unsigned)(wlStart + i), raw, raw * scale);
    }
}

// -------- setup / loop ---------------------------------------------------
void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println(F("\n=== H1 spectrometer on ESP32 ==="));

    H1.setRxBufferSize(H1_RXBUF);     // MUST be before begin()
    H1.begin(H1_BAUD, SERIAL_8N1, H1_RX_PIN, H1_TX_PIN);
    delay(200);
    while (H1.read() >= 0) {}         // drain boot noise

    cmdDeviceInfo();
    cmdWavelengthRange();
    cmdCaptureSingle();
}

void loop() {
    delay(2000);
    cmdCaptureSingle();
}
