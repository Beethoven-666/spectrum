// src/WinSerialPort.cpp -- Win32 CreateFile/SetCommState ISerialPort.
//
// Only compiled on Windows. The implementation mirrors UnixSerialPort: open
// the COM port, configure 8N1, then read/write with overlapped I/O patterns
// emulated via WaitCommEvent + ReadFile for the timeout-aware read.
#if defined(_WIN32)

// Windows.h drags in min/max macros we don't want; #define NOMINMAX first.
#define NOMINMAX
#include <windows.h>

#include <cstring>
#include <stdexcept>
#include <string>

#include "h1/ISerialPort.hpp"

namespace h1 {
namespace {

class WinSerialPort final : public ISerialPort {
public:
    WinSerialPort(const std::string& path, int baud) {
        // For COM ports above 9, Windows requires the `\\.\\COMn` form.
        std::string fullPath = path;
        if (fullPath.compare(0, 4, "\\\\.\\") != 0) {
            fullPath = "\\\\.\\" + path;
        }
        handle_ = CreateFileA(fullPath.c_str(),
                              GENERIC_READ | GENERIC_WRITE,
                              0,        // no sharing
                              nullptr,  // default security
                              OPEN_EXISTING,
                              0,        // non-overlapped (simpler)
                              nullptr);
        if (handle_ == INVALID_HANDLE_VALUE) {
            throw std::runtime_error("CreateFile(" + fullPath + ") failed, GetLastError=" +
                                     std::to_string(GetLastError()));
        }

        DCB dcb{};
        dcb.DCBlength = sizeof(dcb);
        if (!GetCommState(handle_, &dcb)) {
            CloseHandle(handle_);
            throw std::runtime_error("GetCommState failed");
        }
        dcb.BaudRate = static_cast<DWORD>(baud);
        dcb.ByteSize = 8;
        dcb.Parity = NOPARITY;
        dcb.StopBits = ONESTOPBIT;
        dcb.fBinary = TRUE;
        dcb.fParity = FALSE;
        dcb.fOutxCtsFlow = FALSE;
        dcb.fOutxDsrFlow = FALSE;
        dcb.fDtrControl = DTR_CONTROL_DISABLE;
        dcb.fRtsControl = RTS_CONTROL_DISABLE;
        dcb.fOutX = FALSE;
        dcb.fInX = FALSE;
        if (!SetCommState(handle_, &dcb)) {
            CloseHandle(handle_);
            throw std::runtime_error("SetCommState failed");
        }

        // Default timeouts: read returns immediately. We reset
        // ReadIntervalTimeout per-call in read().
        COMMTIMEOUTS to{};
        to.ReadIntervalTimeout = MAXDWORD;
        to.ReadTotalTimeoutConstant = 0;
        to.ReadTotalTimeoutMultiplier = 0;
        to.WriteTotalTimeoutConstant = 1000;
        to.WriteTotalTimeoutMultiplier = 10;
        SetCommTimeouts(handle_, &to);

        PurgeComm(handle_, PURGE_RXCLEAR | PURGE_TXCLEAR);
    }

    ~WinSerialPort() override { close(); }

    std::size_t write(const std::uint8_t* data, std::size_t len) override {
        DWORD written = 0;
        if (!WriteFile(handle_, data, static_cast<DWORD>(len), &written, nullptr)) {
            throw std::runtime_error("WriteFile failed");
        }
        return static_cast<std::size_t>(written);
    }

    std::size_t read(std::uint8_t* buf, std::size_t max_len,
                     std::chrono::milliseconds timeout) override {
        COMMTIMEOUTS to{};
        // ReadTotalTimeoutConstant = wait up to this many ms total before
        // returning whatever was read.
        to.ReadIntervalTimeout = MAXDWORD;
        to.ReadTotalTimeoutConstant = static_cast<DWORD>(timeout.count());
        to.ReadTotalTimeoutMultiplier = MAXDWORD;
        to.WriteTotalTimeoutConstant = 1000;
        to.WriteTotalTimeoutMultiplier = 10;
        SetCommTimeouts(handle_, &to);

        DWORD got = 0;
        if (!ReadFile(handle_, buf, static_cast<DWORD>(max_len), &got, nullptr)) {
            throw std::runtime_error("ReadFile failed");
        }
        return static_cast<std::size_t>(got);
    }

    void close() override {
        if (handle_ != nullptr && handle_ != INVALID_HANDLE_VALUE) {
            CloseHandle(handle_);
            handle_ = INVALID_HANDLE_VALUE;
        }
    }

private:
    HANDLE handle_ = INVALID_HANDLE_VALUE;
};

}  // namespace

std::unique_ptr<ISerialPort> openSerialPort(const std::string& path, int baud) {
    return std::make_unique<WinSerialPort>(path, baud);
}

}  // namespace h1

#endif  // _WIN32
