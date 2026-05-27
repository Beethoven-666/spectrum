// main.cpp -- comprehensive H1 spectrometer demo on ESP32-S3.
//
// Wiring -- HYD1 FPC -> ESP32-S3. **Use the pinout from page 2 of
// HYD1硬件接口说明.pdf (the J2 table), NOT page 1.** Page 1 swaps the pin
// numbering end-to-end and will produce reverse polarity on VCC/GND,
// destroying the sensor.
//
//   FPC pin  Signal       ESP32-S3 pin
//   -------  -----------  -----------------------------------
//   1        GND          GND
//   2        RESET        GPIO5  (driven HIGH to release reset)
//   3        VCC_3.3V     3V3  (separate AMS1117-3.3 from USB 5V if WiFi on)
//   4        RXD0         GPIO17 (ESP32 TX -> sensor RX)
//   5        TXD0         GPIO18 (ESP32 RX <- sensor TX)
//   6        Trigger      GPIO4  (driven LOW; only rising edge captures)
//   7        GND          GND (optional second ground)
//   8-9, 11  NC           leave open
//   10       GND          GND (optional)
//   12       VCC_3.3V     3V3 (optional second VCC)
//
// Console: native USB-CDC (USB Serial/JTAG) -- /dev/cu.usbmodemXXXX on macOS.

#include <atomic>
#include <chrono>
#include <cstdio>
#include <exception>
#include <thread>

#include "h1/Device.hpp"
#include "h1/Errors.hpp"
#include "h1/Esp32SerialPort.hpp"
#include "h1/Types.hpp"

#include "driver/uart.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

// ---------------------------------------------------------------------------
// Pin configuration (change to match your wiring)
// ---------------------------------------------------------------------------
static constexpr uart_port_t kH1Uart      = UART_NUM_1;
static constexpr int         kH1RxPin     = 18;   // ESP32 RX  <- device TXD0 (FPC 8)
static constexpr int         kH1TxPin     = 17;   // ESP32 TX  -> device RXD0 (FPC 9)
static constexpr int         kH1ResetPin  = 5;    // -> device RESET (FPC 11), active-low
static constexpr int         kH1TriggerPin= 4;    // -> device Trigger (FPC 7), rising-edge
static constexpr int         kH1Baud      = 115200;
static constexpr int         kH1RxBuf     = 8192;

// ---------------------------------------------------------------------------
// Pretty-print helpers
// ---------------------------------------------------------------------------
namespace {

const char* exposureStatusStr(h1::ExposureStatus s) {
    switch (s) {
        case h1::ExposureStatus::Normal: return "Normal";
        case h1::ExposureStatus::Over:   return "Overexposed";
        case h1::ExposureStatus::Under:  return "Underexposed";
    }
    return "?";
}

const char* exposureModeStr(h1::ExposureMode m) {
    return m == h1::ExposureMode::Auto ? "Auto" : "Manual";
}

const char* cieModeStr(h1::CieMode m) {
    switch (m) {
        case h1::CieMode::Cie1931_2:  return "CIE1931 2deg";
        case h1::CieMode::Cie1964_10: return "CIE1964 10deg";
        case h1::CieMode::Cie2015_2:  return "CIE2015 2deg";
        case h1::CieMode::Cie2015_10: return "CIE2015 10deg";
    }
    return "?";
}

void section(const char* title) {
    printf("\n=== %s ===\n", title);
}

// Try one (tx,rx) pin pair: install UART, send GetDeviceInfo, dump RX for
// ~1.5 s. Returns the byte count received. Tears down the driver before
// returning so the caller can call again with different pins.
int probePair(int txPin, int rxPin) {
    printf("\n  --- probing TX=GPIO%d  RX=GPIO%d ---\n", txPin, rxPin);
    uart_config_t cfg = {};
    cfg.baud_rate = kH1Baud;
    cfg.data_bits = UART_DATA_8_BITS;
    cfg.parity = UART_PARITY_DISABLE;
    cfg.stop_bits = UART_STOP_BITS_1;
    cfg.flow_ctrl = UART_HW_FLOWCTRL_DISABLE;
    cfg.source_clk = UART_SCLK_DEFAULT;

    if (uart_driver_install(kH1Uart, kH1RxBuf, 0, 0, nullptr, 0) != ESP_OK) {
        printf("  uart_driver_install failed\n");
        return -1;
    }
    uart_param_config(kH1Uart, &cfg);
    uart_set_pin(kH1Uart, txPin, rxPin, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    gpio_set_pull_mode(static_cast<gpio_num_t>(rxPin), GPIO_PULLUP_ONLY);
    uart_flush_input(kH1Uart);

    // GetDeviceInfo: CC 01 0A 00 00 08 18 F7 0D 0A
    const uint8_t cmd[] = {0xCC, 0x01, 0x0A, 0x00, 0x00, 0x08, 0x18, 0xF7, 0x0D, 0x0A};

    uint8_t rxBuf[256];
    int totalRx = 0;
    // Try sending 3 times with a generous receive window each time --
    // covers the case where the sensor missed the first byte due to a
    // power-up race.
    for (int attempt = 1; attempt <= 3; ++attempt) {
        uart_flush_input(kH1Uart);
        uart_write_bytes(kH1Uart, reinterpret_cast<const char*>(cmd), sizeof(cmd));
        uart_wait_tx_done(kH1Uart, pdMS_TO_TICKS(200));

        const TickType_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(800);
        while (xTaskGetTickCount() < deadline) {
            const int n = uart_read_bytes(kH1Uart, rxBuf, sizeof(rxBuf),
                                          pdMS_TO_TICKS(50));
            if (n > 0) {
                if (totalRx == 0) printf("  RX (attempt %d):", attempt);
                for (int i = 0; i < n; ++i) printf(" %02X", rxBuf[i]);
                totalRx += n;
            }
        }
        if (totalRx > 0) break;
    }
    if (totalRx == 0) {
        printf("  RX: (no bytes after 3 attempts)\n");
    } else {
        printf("\n  RX total: %d bytes\n", totalRx);
    }
    uart_driver_delete(kH1Uart);
    return totalRx;
}

// Listen-only test: install UART, don't transmit, just see if any bytes
// arrive in 1.5 s. If yes -> the line is hot from somewhere (real sensor
// output, or a short to a driven pin, or floating-pin noise).
int listenOnly(int rxPin) {
    printf("\n  --- listen-only on RX=GPIO%d (no TX) ---\n", rxPin);
    uart_config_t cfg = {};
    cfg.baud_rate = kH1Baud;
    cfg.data_bits = UART_DATA_8_BITS;
    cfg.parity = UART_PARITY_DISABLE;
    cfg.stop_bits = UART_STOP_BITS_1;
    cfg.flow_ctrl = UART_HW_FLOWCTRL_DISABLE;
    cfg.source_clk = UART_SCLK_DEFAULT;

    if (uart_driver_install(kH1Uart, kH1RxBuf, 0, 0, nullptr, 0) != ESP_OK) {
        return -1;
    }
    uart_param_config(kH1Uart, &cfg);
    // TX = NO_CHANGE means UART has no TX pin assigned -- can't transmit.
    uart_set_pin(kH1Uart, UART_PIN_NO_CHANGE, rxPin,
                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    gpio_set_pull_mode(static_cast<gpio_num_t>(rxPin), GPIO_PULLUP_ONLY);
    uart_flush_input(kH1Uart);

    uint8_t rxBuf[128];
    int totalRx = 0;
    const TickType_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(1500);
    while (xTaskGetTickCount() < deadline) {
        const int n = uart_read_bytes(kH1Uart, rxBuf, sizeof(rxBuf),
                                      pdMS_TO_TICKS(100));
        if (n > 0) {
            if (totalRx == 0) printf("  RX:");
            for (int i = 0; i < n && totalRx + i < 40; ++i) {
                printf(" %02X", rxBuf[i]);
            }
            totalRx += n;
        }
    }
    if (totalRx == 0) {
        printf("  RX: (silent — pin is floating or device idle)\n");
    } else {
        printf("\n  RX total: %d bytes (without us transmitting)\n", totalRx);
    }
    uart_driver_delete(kH1Uart);
    return totalRx;
}

// Sweep both pin orientations and a couple of common alternates so the user
// gets a one-shot diagnostic. Returns the (tx, rx) pair that actually got
// bytes, or {-1, -1} if nothing answered.
struct PinPair { int tx; int rx; };
PinPair autoScan() {
    section("Pin-pair auto-scan");
    // First, listen-only on both candidate RX pins. If we get bytes without
    // transmitting, the line is being driven (real device or accidental
    // short).
    printf("\n[Phase 1: Listen-only — is anything spontaneously on the line?]\n");
    const int idle17 = listenOnly(17);
    const int idle18 = listenOnly(18);
    printf("\n  idle traffic: GPIO17=%d bytes, GPIO18=%d bytes\n", idle17, idle18);
    printf("  (both should be ~0 unless the sensor is in streaming mode.)\n");

    printf("\n[Phase 2: Active probe — TX our command, look for a response]\n");
    // Candidates: documented + swapped + the original sketch's 16/17 pair.
    const PinPair candidates[] = {
        {17, 18},  // documented: TX=17, RX=18  (FPC pin 9 -> GPIO17, FPC pin 8 -> GPIO18)
        {18, 17},  // swapped TX/RX
        {17, 16},  // alternate, in case user followed the earlier minimal sketch
        {16, 17},
    };
    for (const auto& c : candidates) {
        const int n = probePair(c.tx, c.rx);
        if (n > 0) {
            printf("\n  >>> got data with TX=GPIO%d RX=GPIO%d <<<\n", c.tx, c.rx);
            return c;
        }
    }
    printf("\n  No pin pair responded. Check power, GND, and FPC orientation:\n");
    printf("    1. Multimeter: FPC pin 1 (VCC_3.3V) <-> pin 3 (GND) = 3.3 V\n");
    printf("    2. ESP32 GND  shares ground with FPC GND (pin 3, 6, or 12)\n");
    printf("    3. FPC orientation -- contacts face the right way in the connector\n");
    printf("    4. Sensor TX (FPC pin 8) goes to ESP32 RX (input)\n");
    printf("       Sensor RX (FPC pin 9) goes to ESP32 TX (output)\n");
    return {-1, -1};
}

void dumpPhotometric(const h1::PhotometricParams& p) {
    printf("  XYZ      : (%.3f, %.3f, %.3f)\n", p.X, p.Y, p.Z);
    printf("  xy       : (%.4f, %.4f)\n", p.x, p.y);
    printf("  uv'      : (%.4f, %.4f)  (CIE1976)\n", p.u_prime, p.v_prime);
    printf("  CCT      : %.0f K   DUV: %.4f\n", p.CCT, p.DUV);
    printf("  Nit      : %.3f cd/m^2\n", p.Nit);
    printf("  lux      : %.2f      Ee: %.4f W/m^2     fc: %.3f\n",
           p.lux, p.Ee, p.fc);
    printf("  Lp       : %.1f nm   HW: %.2f nm        Ld: %.1f nm\n",
           p.Lp, p.HW, p.Ld);
    printf("  purity   : %.2f %%   S/P: %.3f          SDCM/k: %.3f\n",
           p.purity, p.SP, p.SDCM_k);
    printf("  Ra       : %.2f      CQS: %.2f\n", p.Ra, p.CQS);
    printf("  CRI      : ");
    for (size_t i = 0; i < p.R.size(); ++i) {
        printf("R%zu=%.1f ", i + 1, p.R[i]);
        if (i == 7) printf("\n             ");
    }
    printf("\n");
    printf("  GAI      : EES=%.2f  BB_8=%.2f  BB_15=%.2f\n",
           p.GAI_EES, p.GAI_BB_8, p.GAI_BB_15);
    printf("  melanopic: EML=%.3f  M-EDI=%.3f\n", p.EML, p.M_EDI);
}

void dumpFrame(const h1::SpectrumFrame& f, std::uint16_t wlStart) {
    printf("  exposure : %s @ %lu us   coefficient N=%d   samples=%u\n",
           exposureStatusStr(f.exposureStatus),
           static_cast<unsigned long>(f.exposureTimeUs),
           static_cast<int>(f.spectrumCoefficient),
           static_cast<unsigned>(f.rawSpectrum.size()));

    dumpPhotometric(f.photometric);

    printf("  blue hzd : Eb=%.4f W/m^2\n", f.blueHazard.Eb);
    printf("  NIR      : red=%.4f  A=%.4f  B=%.4f W/m^2\n",
           f.nir.redEe, f.nir.nirEeA, f.nir.nirEeB);
    printf("  plant    : PAR=%.2f  PPFD=%.2f  PPFDb=%.2f  PPFDr=%.2f  YPFD=%.2f\n",
           f.plant.PAR, f.plant.PPFD, f.plant.PPFDb, f.plant.PPFDr, f.plant.YPFD);

    if (f.tm30) {
        printf("  TM-30    : Rf=%.2f  Rg=%.2f\n", f.tm30->Rf, f.tm30->Rg);
    }

    // First 10 and last 5 spectrum samples
    const auto actual = f.actualSpectrum();
    const std::size_t n = f.rawSpectrum.size();
    printf("  spectrum head:\n");
    for (std::size_t i = 0; i < 10 && i < n; ++i) {
        printf("    %4u nm: raw=%5u  scaled=%.3f\n",
               static_cast<unsigned>(wlStart + i),
               f.rawSpectrum[i], actual[i]);
    }
    if (n > 15) {
        printf("  spectrum tail:\n");
        for (std::size_t i = n - 5; i < n; ++i) {
            printf("    %4u nm: raw=%5u  scaled=%.3f\n",
                   static_cast<unsigned>(wlStart + i),
                   f.rawSpectrum[i], actual[i]);
        }
    }
}

}  // namespace

// ---------------------------------------------------------------------------
// Demo
// ---------------------------------------------------------------------------
extern "C" void app_main(void) {
    using namespace std::chrono_literals;

    // Give the USB-CDC console a moment to enumerate so we don't lose the
    // first prints to the host.
    std::this_thread::sleep_for(1000ms);

    printf("\n\n");
    printf("============================================\n");
    printf(" H1 spectrometer demo on ESP32-S3 (ESP-IDF) \n");
    printf("============================================\n");
    printf("UART%d  RX=GPIO%d  TX=GPIO%d  baud=%d\n",
           static_cast<int>(kH1Uart), kH1RxPin, kH1TxPin, kH1Baud);
    printf("RESET=GPIO%d (driven HIGH)  Trigger=GPIO%d (driven LOW)\n",
           kH1ResetPin, kH1TriggerPin);

    // Trigger: active low idle (rising-edge triggers a capture). Drive low.
    gpio_config_t trig_conf = {};
    trig_conf.mode = GPIO_MODE_OUTPUT;
    trig_conf.pin_bit_mask = 1ULL << kH1TriggerPin;
    trig_conf.pull_up_en = GPIO_PULLUP_DISABLE;
    trig_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
    trig_conf.intr_type = GPIO_INTR_DISABLE;
    gpio_config(&trig_conf);
    gpio_set_level(static_cast<gpio_num_t>(kH1TriggerPin), 0);

    // Sweep RESET configurations. Try input+pullup (mimics dev board's
    // weak pull-up), then active HIGH drive, then active LOW drive, then
    // input+no-pull (fully floating, in case the chip has its own internal
    // pull-up on RESET).
    PinPair found{-1, -1};
    auto configureReset = [&](const char* name, gpio_mode_t mode,
                              int driveLevel, bool pullUp, bool pullDown) {
        printf("\n########## TRYING %s ##########\n", name);
        gpio_config_t conf = {};
        conf.mode = mode;
        conf.pin_bit_mask = 1ULL << kH1ResetPin;
        conf.pull_up_en = pullUp ? GPIO_PULLUP_ENABLE : GPIO_PULLUP_DISABLE;
        conf.pull_down_en = pullDown ? GPIO_PULLDOWN_ENABLE : GPIO_PULLDOWN_DISABLE;
        conf.intr_type = GPIO_INTR_DISABLE;
        gpio_config(&conf);
        if (mode == GPIO_MODE_OUTPUT && driveLevel >= 0) {
            gpio_set_level(static_cast<gpio_num_t>(kH1ResetPin), driveLevel);
        }
        std::this_thread::sleep_for(1500ms);
    };

    const struct {
        const char* name;
        gpio_mode_t mode;
        int driveLevel;
        bool pullUp;
        bool pullDown;
    } resetTrials[] = {
        {"RESET = INPUT + internal pull-up (dev-board-style)",
         GPIO_MODE_INPUT, -1, true, false},
        {"RESET = INPUT only (fully floating, chip handles internally)",
         GPIO_MODE_INPUT, -1, false, false},
        {"RESET = OUTPUT driven HIGH",
         GPIO_MODE_OUTPUT, 1, false, false},
        {"RESET = OUTPUT driven LOW",
         GPIO_MODE_OUTPUT, 0, false, false},
    };
    for (const auto& trial : resetTrials) {
        configureReset(trial.name, trial.mode, trial.driveLevel,
                       trial.pullUp, trial.pullDown);
        found = autoScan();
        if (found.tx >= 0) {
            printf("\n>>> WORKING CONFIG: %s, TX=GPIO%d RX=GPIO%d <<<\n",
                   trial.name, found.tx, found.rx);
            break;
        }
    }
    const int useTx = (found.tx >= 0) ? found.tx : kH1TxPin;
    const int useRx = (found.rx >= 0) ? found.rx : kH1RxPin;

    std::unique_ptr<h1::Device> devPtr;
    h1::WavelengthRange wr;

    auto section_try = [&](const char* title, auto&& fn) {
        section(title);
        try {
            fn();
        } catch (const std::exception& e) {
            printf("!! %s\n", e.what());
        }
    };

    try {
        auto port = h1::openEsp32SerialPort(kH1Uart, useRx, useTx,
                                            kH1Baud, kH1RxBuf);
        devPtr = std::make_unique<h1::Device>(std::move(port));
        printf("\nSDK using TX=GPIO%d  RX=GPIO%d\n", useTx, useRx);
    } catch (const std::exception& e) {
        printf("!! could not open UART: %s\n", e.what());
        while (true) std::this_thread::sleep_for(1s);
    }
    h1::Device& dev = *devPtr;

    // 1. Device info (0x08)
    section_try("Device info", [&] {
        const auto info = dev.getDeviceInfo();
        printf("serial number: %s\n", info.serialNumber.c_str());
    });

    // 2. Wavelength range (0x0F)
    section_try("Wavelength range", [&] {
        wr = dev.getWavelengthRange();
        printf("range: %u - %u nm   count: %u samples\n",
               wr.start, wr.end, static_cast<unsigned>(wr.count()));
    });

    // 3. Current settings (0x0B / 0x0D / 0x14 / 0x37)
    section_try("Current settings", [&] {
        printf("exposure mode : %s\n", exposureModeStr(dev.getExposureMode()));
        printf("exposure time : %lu us\n",
               static_cast<unsigned long>(dev.getExposureTimeUs()));
        printf("max exposure  : %lu us\n",
               static_cast<unsigned long>(dev.getMaxExposureTimeUs()));
        printf("CIE mode      : %s\n", cieModeStr(dev.getCieMode()));
    });

    // 4. Configure (0x0A / 0x36)
    section_try("Configure: CIE=1931/2deg, exposure=Auto", [&] {
        try {
            dev.setCieMode(h1::CieMode::Cie1931_2);
            printf("  CIE   -> %s\n", cieModeStr(dev.getCieMode()));
        } catch (const h1::DeviceError& e) {
            printf("  (setCieMode not supported: %s)\n", e.what());
        }
        dev.setExposureMode(h1::ExposureMode::Auto);
        printf("  mode  -> %s\n", exposureModeStr(dev.getExposureMode()));
    });

    // 5. Single capture, no TM30 (0x32)
    section_try("Single capture (no TM30)", [&] {
        const auto frame = dev.captureSingle(/*includeTm30=*/false, 10000ms);
        dumpFrame(frame, wr.start);
    });

    // 6. Single capture WITH TM30 (0x34)
    section_try("Single capture (with TM30)", [&] {
        const auto frame = dev.captureSingle(/*includeTm30=*/true, 15000ms);
        dumpFrame(frame, wr.start);
    });

    // 7. Streaming (0x33 + 0x04)
    section_try("Streaming 5 frames", [&] {
        std::atomic<int>  frameCount{0};
        std::atomic<bool> done{false};

        dev.startStreaming(
            [&](h1::SpectrumFrame f) {
                const int n = ++frameCount;
                const auto& p = f.photometric;
                printf("[stream %d] CCT=%.0fK  lux=%.2f  exp=%luus  status=%s\n",
                       n, p.CCT, p.lux,
                       static_cast<unsigned long>(f.exposureTimeUs),
                       exposureStatusStr(f.exposureStatus));
                if (n >= 5) done = true;
            },
            /*includeTm30=*/false,
            [](std::exception_ptr ep) {
                try { std::rethrow_exception(ep); }
                catch (const std::exception& e) {
                    printf("[stream error] %s\n", e.what());
                }
            });

        const auto deadline = std::chrono::steady_clock::now() + 30s;
        while (!done && std::chrono::steady_clock::now() < deadline) {
            std::this_thread::sleep_for(50ms);
        }
        dev.stopStreaming();
        printf("streaming stopped after %d frames\n", frameCount.load());
    });

    // 8. APIs intentionally NOT exercised in the demo (still wired up):
    //      dev.setMaxExposureTimeUs(N)            // 0x13
    //      dev.setExposureMode(Manual)            // 0x0A
    //      dev.setExposureTimeUs(N)               // 0x0C  (only in Manual)
    //      dev.setWorkingMode(Trigger)            // 0x41 -- needs hardware pulse
    //      dev.enterSleep() / exitSleep()         // 0x40
    //      dev.uploadEfficiencyCurve(ratios)      // 0x23
    //      dev.verifyAndComputeEfficiencyCurve()  // 0x27 -- writes flash!
    //      dev.resetEfficiencyCurve()             // 0x25 -- factory reset

    section("Demo complete");
    printf("(idle. Press the reset button to re-run.)\n");

    // Keep app_main alive so the USB-CDC console session stays attached.
    while (true) std::this_thread::sleep_for(1s);
}
