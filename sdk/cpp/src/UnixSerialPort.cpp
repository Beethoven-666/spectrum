// src/UnixSerialPort.cpp -- termios-based ISerialPort for macOS and Linux.
//
// Compiled when the target is anything other than Windows. The Windows
// version lives in WinSerialPort.cpp.
#if !defined(_WIN32)

#include <errno.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/select.h>
#include <termios.h>
#include <unistd.h>

#include <cstring>
#include <stdexcept>
#include <string>

#include "h1/ISerialPort.hpp"

namespace h1 {
namespace {

// Map a numeric baud rate to its termios speed_t constant. We only need a
// handful for this device but enumerate a useful range so callers aren't
// surprised when they pick e.g. 57600 for a different sensor.
speed_t toSpeed(int baud) {
    switch (baud) {
        case 9600: return B9600;
        case 19200: return B19200;
        case 38400: return B38400;
        case 57600: return B57600;
        case 115200: return B115200;
        case 230400: return B230400;
#ifdef B460800
        case 460800: return B460800;
#endif
#ifdef B921600
        case 921600: return B921600;
#endif
        default:
            throw std::runtime_error("unsupported baud rate: " + std::to_string(baud));
    }
}

class UnixSerialPort final : public ISerialPort {
public:
    UnixSerialPort(const std::string& path, int baud) {
        fd_ = ::open(path.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK);
        if (fd_ < 0) {
            throw std::runtime_error("open(" + path + ") failed: " +
                                     std::strerror(errno));
        }

        // Take ownership of the device.
        int flags = ::fcntl(fd_, F_GETFL, 0);
        if (flags < 0 || ::fcntl(fd_, F_SETFL, flags & ~O_NONBLOCK) < 0) {
            ::close(fd_);
            throw std::runtime_error("fcntl failed: " + std::string(std::strerror(errno)));
        }

        struct termios tio{};
        if (::tcgetattr(fd_, &tio) != 0) {
            ::close(fd_);
            throw std::runtime_error("tcgetattr failed: " + std::string(std::strerror(errno)));
        }

        // Raw mode: cfmakeraw + 8N1 + no flow control.
        cfmakeraw(&tio);
        tio.c_cflag |= (CLOCAL | CREAD);
        tio.c_cflag &= ~CSIZE;
        tio.c_cflag |= CS8;
        tio.c_cflag &= ~PARENB;   // no parity
        tio.c_cflag &= ~CSTOPB;   // 1 stop bit
        tio.c_cflag &= ~CRTSCTS;  // no hardware flow control
        tio.c_iflag &= ~(IXON | IXOFF | IXANY);  // no software flow control

        // Read returns immediately with whatever is available (we use
        // select() ourselves to enforce timeouts).
        tio.c_cc[VMIN] = 0;
        tio.c_cc[VTIME] = 0;

        const speed_t spd = toSpeed(baud);
        if (::cfsetispeed(&tio, spd) != 0 || ::cfsetospeed(&tio, spd) != 0) {
            ::close(fd_);
            throw std::runtime_error("cfsetspeed failed: " + std::string(std::strerror(errno)));
        }
        if (::tcsetattr(fd_, TCSANOW, &tio) != 0) {
            ::close(fd_);
            throw std::runtime_error("tcsetattr failed: " + std::string(std::strerror(errno)));
        }
        // Discard any stale bytes from previous sessions.
        ::tcflush(fd_, TCIOFLUSH);
    }

    ~UnixSerialPort() override {
        close();
    }

    std::size_t write(const std::uint8_t* data, std::size_t len) override {
        std::size_t total = 0;
        while (total < len) {
            ssize_t n = ::write(fd_, data + total, len - total);
            if (n < 0) {
                if (errno == EINTR) continue;
                throw std::runtime_error("serial write failed: " + std::string(std::strerror(errno)));
            }
            total += static_cast<std::size_t>(n);
        }
        return total;
    }

    std::size_t read(std::uint8_t* buf, std::size_t max_len,
                     std::chrono::milliseconds timeout) override {
        // select() with the supplied timeout, then a single ::read.
        fd_set rfds;
        FD_ZERO(&rfds);
        FD_SET(fd_, &rfds);
        struct timeval tv{};
        tv.tv_sec = static_cast<time_t>(timeout.count() / 1000);
        tv.tv_usec = static_cast<suseconds_t>((timeout.count() % 1000) * 1000);

        int rv = ::select(fd_ + 1, &rfds, nullptr, nullptr, &tv);
        if (rv < 0) {
            if (errno == EINTR) return 0;
            throw std::runtime_error("select failed: " + std::string(std::strerror(errno)));
        }
        if (rv == 0) return 0;  // timeout
        ssize_t n = ::read(fd_, buf, max_len);
        if (n < 0) {
            if (errno == EINTR || errno == EAGAIN) return 0;
            throw std::runtime_error("serial read failed: " + std::string(std::strerror(errno)));
        }
        return static_cast<std::size_t>(n);
    }

    void close() override {
        if (fd_ >= 0) {
            ::close(fd_);
            fd_ = -1;
        }
    }

private:
    int fd_ = -1;
};

}  // namespace

std::unique_ptr<ISerialPort> openSerialPort(const std::string& path, int baud) {
    return std::make_unique<UnixSerialPort>(path, baud);
}

}  // namespace h1

#endif  // !_WIN32
