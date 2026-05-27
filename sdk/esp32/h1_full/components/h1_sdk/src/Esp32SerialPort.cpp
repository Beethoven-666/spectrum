// src/Esp32SerialPort.cpp -- ESP-IDF UART backing for ISerialPort.
#include "h1/Esp32SerialPort.hpp"

#include <stdexcept>
#include <string>

#include "driver/uart.h"
#include "driver/gpio.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

namespace h1 {
namespace {

class Esp32SerialPort final : public ISerialPort {
public:
    Esp32SerialPort(uart_port_t port, int rxPin, int txPin, int baud, int rxBufSize)
        : port_(port), installed_(false) {
        uart_config_t cfg = {};
        cfg.baud_rate = baud;
        cfg.data_bits = UART_DATA_8_BITS;
        cfg.parity = UART_PARITY_DISABLE;
        cfg.stop_bits = UART_STOP_BITS_1;
        cfg.flow_ctrl = UART_HW_FLOWCTRL_DISABLE;
        cfg.source_clk = UART_SCLK_DEFAULT;

        esp_err_t err = uart_driver_install(port_, rxBufSize, /*tx_buf*/ 0,
                                            /*queue*/ 0, nullptr, 0);
        if (err != ESP_OK) {
            throw std::runtime_error(std::string("uart_driver_install: ") +
                                     esp_err_to_name(err));
        }
        installed_ = true;

        err = uart_param_config(port_, &cfg);
        if (err != ESP_OK) {
            uart_driver_delete(port_);
            installed_ = false;
            throw std::runtime_error(std::string("uart_param_config: ") +
                                     esp_err_to_name(err));
        }

        err = uart_set_pin(port_, txPin, rxPin,
                           UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
        if (err != ESP_OK) {
            uart_driver_delete(port_);
            installed_ = false;
            throw std::runtime_error(std::string("uart_set_pin: ") +
                                     esp_err_to_name(err));
        }

        // Enable internal pull-up on RX so that a disconnected line idles
        // high (UART idle = mark = high) instead of floating and picking up
        // crosstalk from the adjacent TX pin. Cheap and harmless when a
        // real driver is connected.
        if (rxPin >= 0) {
            gpio_set_pull_mode(static_cast<gpio_num_t>(rxPin), GPIO_PULLUP_ONLY);
        }

        // Drop anything that may have arrived during power-up.
        uart_flush_input(port_);
    }

    ~Esp32SerialPort() override {
        if (installed_) {
            uart_driver_delete(port_);
        }
    }

    std::size_t write(const std::uint8_t* data, std::size_t len) override {
        const int n = uart_write_bytes(port_,
                                       reinterpret_cast<const char*>(data),
                                       len);
        if (n < 0) return 0;
        // Block until the bytes are physically out the wire so that the
        // device doesn't see a partial frame followed by a long pause.
        uart_wait_tx_done(port_, pdMS_TO_TICKS(1000));
        return static_cast<std::size_t>(n);
    }

    std::size_t read(std::uint8_t* buf, std::size_t maxLen,
                     std::chrono::milliseconds timeout) override {
        const TickType_t ticks = timeout.count() <= 0
            ? 0
            : pdMS_TO_TICKS(timeout.count());
        const int n = uart_read_bytes(port_, buf, maxLen, ticks);
        if (n < 0) return 0;
        return static_cast<std::size_t>(n);
    }

    void close() override {
        if (installed_) {
            uart_driver_delete(port_);
            installed_ = false;
        }
    }

private:
    uart_port_t port_;
    bool installed_;
};

}  // namespace

std::unique_ptr<ISerialPort> openEsp32SerialPort(
    uart_port_t port, int rxPin, int txPin, int baud, int rxBufSize) {
    return std::make_unique<Esp32SerialPort>(port, rxPin, txPin, baud, rxBufSize);
}

// The desktop SDK declares an openSerialPort() factory that takes a path.
// We provide a stub so the link-step is happy if anyone ever calls it on
// ESP32 -- but the demo uses openEsp32SerialPort() instead.
std::unique_ptr<ISerialPort> openSerialPort(const std::string&, int) {
    throw std::runtime_error("openSerialPort(path,baud) is not supported on ESP32; "
                             "use openEsp32SerialPort() instead");
}

}  // namespace h1
