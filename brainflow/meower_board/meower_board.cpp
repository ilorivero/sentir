/*********************************************************************
 * meower_board.cpp - BrainFlow UDP driver for the Meower EEG board (SENTIR)
 * See meower_board.h for the data layout and the differences from the
 * original VRChatBoard driver.
 *
 * Wire format (unchanged Meower firmware):
 *   datagram = frame[0..n-1] + battery(float32 LE), 1 <= n <= 28
 *   frame    = 16 x int24 big-endian (48 B) + uint32 LE timestamp (8 us ticks)
 * Control port (UTF-8):
 *   PC -> "WOOF_WOOF" (discovery + keep-alive, < 10 s)
 *   PC -> "TSYNC <seq>"  board -> "TSYNC <seq> <t2_ticks> <t3_ticks>"  (patch 0001)
 *   PC -> any sys/usr/spi command, board -> "OK: ..." / "ERR: ..."
 *********************************************************************/

#include "meower_board.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <sstream>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "ws2_32.lib")
#else
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

#include "brainflow_constants.h"
#include "timestamp.h"

namespace
{
    constexpr int CHANNELS = 16;
    constexpr int BYTES_PER_CHANNEL = 3;
    constexpr int CHANNEL_DATA_SIZE = CHANNELS * BYTES_PER_CHANNEL; // 48
    constexpr int FRAME_SIZE = CHANNEL_DATA_SIZE + 4;               // 52
    constexpr int BATTERY_SIZE = 4;
    constexpr int RECV_BUFFER_SIZE = 1500;
    constexpr double TICK_S = 8e-6;
    constexpr double ADS1299_LSB_UV = 4.5 / 8388608.0 * 1e6; // 0.536 uV at gain 1
    constexpr int KEEPALIVE_INTERVAL_MS = 4000;
    constexpr int DEFAULT_DISCOVERY_TIMEOUT_MS = 3000;
    constexpr int CTRL_TIMEOUT_MS = 1000;
    constexpr int TSYNC_REPLY_TIMEOUT_MS = 250;
    constexpr int INITIAL_TSYNC_BURST = 20;
    constexpr double FALLBACK_WINDOW_S = 10.0;
    constexpr double MAX_SLEW = 1e-3;        // 1000 ppm
    constexpr double STEP_THRESHOLD_S = 0.1; // larger errors are corrected at once

    // default layout (overridden by the board descriptor when present)
    constexpr int ROW_BATTERY = 16;
    constexpr int ROW_TIMESTAMP = 17;
    constexpr int ROW_DEVICE_TIME = 18;
    constexpr int ROW_PACKAGE = 19;
    constexpr int ROW_MARKER = 20;
    constexpr int ROW_SYNC_UNC = 21;
    constexpr int ROW_LOST = 22;
    constexpr int ROW_STATUS = 23;
    constexpr int NUM_ROWS = 24;
    constexpr int ANC_ROWS = 9;

    void close_raw_socket (int s)
    {
        if (s < 0)
            return;
#ifdef _WIN32
        closesocket (s);
#else
        close (s);
#endif
    }

    void sleep_ms (int ms)
    {
        std::this_thread::sleep_for (std::chrono::milliseconds (ms));
    }
}

// ====================================================================
//                       CONSTRUCTOR / DESTRUCTOR
// ====================================================================

MeowerBoard::MeowerBoard (int board_id, struct BrainFlowInputParams params)
    : Board (board_id, params)
{
    data_port_ = params.ip_port ? params.ip_port : 5001;
    ctrl_port_ = params.ip_port_aux ? params.ip_port_aux : 5000;
    board_ctrl_port_ = get_option_int ("board_ctrl_port", ctrl_port_);
    tsync_interval_ms_ = std::max (200, get_option_int ("tsync_interval_ms", 1000));
    tsync_window_ = (size_t)std::max (10, get_option_int ("tsync_window", 120));
    double pga = (double)std::max (1, get_option_int ("pga_gain", 1));
    for (int i = 0; i < CHANNELS; i++)
    {
        pga_gain_[i] = pga;
    }
    digital_gain_ = (double)std::max (1, get_option_int ("digital_gain", 1));
}

MeowerBoard::~MeowerBoard ()
{
    skip_logs = true;
    release_session ();
}

int MeowerBoard::get_option_int (const std::string &key, int def) const
{
    const std::string needle = key + "=";
    size_t pos = params.other_info.find (needle);
    if (pos == std::string::npos)
    {
        return def;
    }
    try
    {
        return std::stoi (params.other_info.substr (pos + needle.size ()));
    }
    catch (...)
    {
        return def;
    }
}

// ====================================================================
//                         SESSION MANAGEMENT
// ====================================================================

int MeowerBoard::prepare_session ()
{
    if (initialized_)
    {
        safe_logger (spdlog::level::info, "Session already prepared");
        return (int)BrainFlowExitCodes::STATUS_OK;
    }

#ifdef _WIN32
    if (!wsa_initialized_)
    {
        WSADATA wsa_data;
        if (WSAStartup (MAKEWORD (2, 2), &wsa_data) != 0)
        {
            safe_logger (spdlog::level::err, "WSAStartup failed");
            return (int)BrainFlowExitCodes::GENERAL_ERROR;
        }
        wsa_initialized_ = true;
    }
#endif

    data_srv_ = new SocketServerUDP (data_port_);
    if (data_srv_->bind () != (int)SocketServerUDPReturnCodes::STATUS_OK)
    {
        safe_logger (spdlog::level::err, "Failed to bind data port {}", data_port_);
        delete data_srv_;
        data_srv_ = nullptr;
        return (int)BrainFlowExitCodes::UNABLE_TO_OPEN_PORT_ERROR;
    }

    board_ip_ = params.ip_address;
    if (board_ip_.empty ())
    {
        int timeout_ms = get_option_int ("discovery_timeout", DEFAULT_DISCOVERY_TIMEOUT_MS);
        if (!wait_for_beacon (timeout_ms))
        {
            safe_logger (spdlog::level::err, "No MEOW_MEOW beacon on port {} within {} ms",
                ctrl_port_, timeout_ms);
            close_sockets ();
            return (int)BrainFlowExitCodes::BOARD_NOT_READY_ERROR;
        }
    }
    safe_logger (spdlog::level::info, "Meower board at {} (data {}, ctrl {})", board_ip_,
        data_port_, ctrl_port_);

    ctrl_socket_ = (int)socket (AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (ctrl_socket_ < 0)
    {
        safe_logger (spdlog::level::err, "Failed to create control socket");
        close_sockets ();
        return (int)BrainFlowExitCodes::GENERAL_ERROR;
    }
    int reuse = 1;
    setsockopt (ctrl_socket_, SOL_SOCKET, SO_REUSEADDR, (const char *)&reuse, sizeof (reuse));
    struct sockaddr_in bind_addr;
    memset (&bind_addr, 0, sizeof (bind_addr));
    bind_addr.sin_family = AF_INET;
    bind_addr.sin_addr.s_addr = INADDR_ANY;
    bind_addr.sin_port = htons (ctrl_port_);
    if (bind (ctrl_socket_, (struct sockaddr *)&bind_addr, sizeof (bind_addr)) < 0)
    {
        safe_logger (spdlog::level::err, "Failed to bind control port {}", ctrl_port_);
        close_sockets ();
        return (int)BrainFlowExitCodes::UNABLE_TO_OPEN_PORT_ERROR;
    }

    {
        std::lock_guard<std::mutex> lock (ctrl_mutex_);
        // the firmware only accepts commands after it has seen WOOF_WOOF from the PC
        send_ctrl_locked ("WOOF_WOOF");
        sleep_ms (100);
        int ok = 0;
        for (int i = 0; i < INITIAL_TSYNC_BURST; i++)
        {
            ok += tsync_once_locked (TSYNC_REPLY_TIMEOUT_MS) ? 1 : 0;
            if ((i == 2) && (ok == 0))
            {
                break; // firmware without TSYNC support
            }
            sleep_ms (20);
        }
        tsync_supported_ = ok > 0;

        // identity: number of ADS1299 chips (8 or 16 channels) and emulated-ADC flag
        if (send_ctrl_locked ("ID?"))
        {
            char buf[256];
            auto deadline = std::chrono::steady_clock::now () + std::chrono::milliseconds (300);
            while (std::chrono::steady_clock::now () < deadline)
            {
                int n = recv_ctrl_locked (buf, sizeof (buf), 100);
                if ((n > 0) && (strncmp (buf, "ID ", 3) == 0))
                {
                    device_info_ = buf;
                    if (strstr (buf, " ads=1") != nullptr)
                        ads_count_ = 1;
                    if (strstr (buf, " fake=1") != nullptr)
                        fake_adc_ = true;
                    break;
                }
            }
        }
        if (get_option_int ("ads_count", 0) > 0)
        {
            ads_count_ = get_option_int ("ads_count", 2);
        }
    }
    safe_logger (spdlog::level::info, "Meower: {} ADS1299 ({} channels){} [{}]", ads_count_.load (),
        ads_count_ == 1 ? 8 : 16, fake_adc_ ? " EMULATED ADC - test firmware" : "", device_info_);
    if (tsync_supported_)
    {
        safe_logger (spdlog::level::info, "TSYNC supported, clock fit ready: {}", have_fit_);
    }
    else
    {
        safe_logger (spdlog::level::warn,
            "Board does not answer TSYNC (apply SENTIR firmware patch). Using arrival-time "
            "min-delay estimator; expect several ms of timestamp error.");
    }

    keep_ping_ = true;
    ping_th_ = std::thread ([this] { this->ping_thread (); });
    initialized_ = true;
    return (int)BrainFlowExitCodes::STATUS_OK;
}

int MeowerBoard::start_stream (int buffer_size, const char *streamer_params)
{
    if (!initialized_)
    {
        return (int)BrainFlowExitCodes::BOARD_NOT_CREATED_ERROR;
    }
    if (streaming_)
    {
        return (int)BrainFlowExitCodes::STREAM_ALREADY_RUN_ERROR;
    }
    int res = prepare_for_acquisition (buffer_size, streamer_params);
    if (res != (int)BrainFlowExitCodes::STATUS_OK)
    {
        return res;
    }
    // start reading BEFORE asking the board to stream: otherwise ~1 s of datagrams pile up in
    // the socket while config_board waits (start_cnt has no reply) and arrival times are skewed
    keep_alive_ = true;
    streaming_ = true;
    read_th_ = std::thread ([this] { this->read_thread (); });
    std::string response;
    config_board ("sys start_cnt", response);
    return (int)BrainFlowExitCodes::STATUS_OK;
}

int MeowerBoard::stop_stream ()
{
    if (!streaming_)
    {
        return (int)BrainFlowExitCodes::STREAM_THREAD_IS_NOT_RUNNING;
    }
    streaming_ = false;
    std::string response;
    config_board ("sys stop_cnt", response);
    keep_alive_ = false;
    if (read_th_.joinable ())
    {
        read_th_.join ();
    }
    streaming_ = false;
    return (int)BrainFlowExitCodes::STATUS_OK;
}

int MeowerBoard::release_session ()
{
    if (streaming_)
    {
        stop_stream ();
    }
    keep_ping_ = false;
    if (ping_th_.joinable ())
    {
        ping_th_.join ();
    }
    close_sockets ();
    initialized_ = false;
    {
        std::lock_guard<std::mutex> lock (clock_mutex_);
        tsync_samples_.clear ();
        arrival_offsets_.clear ();
        have_fit_ = false;
    }
    have_tick_ref_ = false;
    free_packages ();
    return (int)BrainFlowExitCodes::STATUS_OK;
}

void MeowerBoard::close_sockets ()
{
    if (data_srv_ != nullptr)
    {
        data_srv_->close ();
        delete data_srv_;
        data_srv_ = nullptr;
    }
    close_raw_socket (ctrl_socket_);
    ctrl_socket_ = -1;
#ifdef _WIN32
    if (wsa_initialized_)
    {
        WSACleanup ();
        wsa_initialized_ = false;
    }
#endif
}

// ====================================================================
//                         CONTROL SOCKET
// ====================================================================

bool MeowerBoard::send_ctrl_locked (const std::string &msg)
{
    if ((ctrl_socket_ < 0) || board_ip_.empty ())
    {
        return false;
    }
    struct sockaddr_in dest;
    memset (&dest, 0, sizeof (dest));
    dest.sin_family = AF_INET;
    dest.sin_port = htons (board_ctrl_port_);
    inet_pton (AF_INET, board_ip_.c_str (), &dest.sin_addr);
    int res = (int)sendto (
        ctrl_socket_, msg.c_str (), (int)msg.size (), 0, (struct sockaddr *)&dest, sizeof (dest));
    return res == (int)msg.size ();
}

int MeowerBoard::recv_ctrl_locked (char *buf, int size, int timeout_ms)
{
#ifdef _WIN32
    fd_set set;
    FD_ZERO (&set);
    FD_SET ((SOCKET)ctrl_socket_, &set);
    timeval tv;
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
    int ready = select (0, &set, nullptr, nullptr, &tv);
#else
    struct pollfd pfd;
    pfd.fd = ctrl_socket_;
    pfd.events = POLLIN;
    int ready = poll (&pfd, 1, timeout_ms);
#endif
    if (ready <= 0)
    {
        return 0;
    }
    struct sockaddr_in from;
    socklen_t from_len = sizeof (from);
    int n = (int)recvfrom (ctrl_socket_, buf, size - 1, 0, (struct sockaddr *)&from, &from_len);
    if (n > 0)
    {
        buf[n] = '\0';
        // ignore our own beacon echoes and packets from other boards
        char ip[INET_ADDRSTRLEN];
        inet_ntop (AF_INET, &from.sin_addr, ip, INET_ADDRSTRLEN);
        if ((board_ip_ != ip) || (strncmp (buf, "MEOW_MEOW", 9) == 0))
        {
            return -2;
        }
    }
    return n;
}

bool MeowerBoard::tsync_once_locked (int timeout_ms)
{
    uint32_t seq = ++tsync_seq_;
    char msg[32];
    snprintf (msg, sizeof (msg), "TSYNC %u", seq);
    double t1 = get_timestamp ();
    if (!send_ctrl_locked (msg))
    {
        return false;
    }
    char buf[256];
    auto deadline = std::chrono::steady_clock::now () + std::chrono::milliseconds (timeout_ms);
    while (std::chrono::steady_clock::now () < deadline)
    {
        int left = (int)std::chrono::duration_cast<std::chrono::milliseconds> (
            deadline - std::chrono::steady_clock::now ())
                       .count ();
        int n = recv_ctrl_locked (buf, sizeof (buf), std::max (1, left));
        double t4 = get_timestamp ();
        if (n == 0)
        {
            break;
        }
        if (n < 0)
        {
            continue;
        }
        unsigned int rseq = 0;
        unsigned long long t2 = 0, t3 = 0;
        if (sscanf (buf, "TSYNC %u %llu %llu", &rseq, &t2, &t3) == 3)
        {
            if (rseq != seq)
            {
                continue; // late reply of a previous probe
            }
            TsyncSample s {(double)seq, t1, t2 * TICK_S, t3 * TICK_S, t4};
            last_tick_ref_ = (uint64_t)t3;
            have_tick_ref_ = true;
            {
                std::lock_guard<std::mutex> lock (clock_mutex_);
                tsync_samples_.push_back (s);
                while (tsync_samples_.size () > tsync_window_)
                {
                    tsync_samples_.pop_front ();
                }
                refit_clock_locked ();
            }
            double anc[ANC_ROWS] = {0};
            anc[0] = s.seq;
            anc[1] = s.t1;
            anc[2] = s.t2;
            anc[3] = s.t3;
            anc[4] = s.t4;
            anc[5] = (t4 - t1 - (s.t3 - s.t2)) * 1000.0;
            anc[6] = 0.5 * (t1 + t4) - 0.5 * (s.t2 + s.t3);
            anc[7] = t4;
            if (streaming_)
            {
                push_package (anc, (int)BrainFlowPresets::ANCILLARY_PRESET);
            }
            tsync_misses_ = 0;
            return true;
        }
    }
    tsync_misses_++;
    return false;
}

int MeowerBoard::config_board (std::string config, std::string &response)
{
    // local (driver-side) queries, never sent to the board
    if (config == "sentir:info")
    {
        response = "ads=" + std::to_string (ads_count_.load ()) +
            " channels=" + std::to_string (ads_count_ == 1 ? 8 : 16) +
            " fake=" + std::to_string (fake_adc_ ? 1 : 0) + " id=" + device_info_;
        return (int)BrainFlowExitCodes::STATUS_OK;
    }
    if (config == "sentir:clock")
    {
        std::lock_guard<std::mutex> lock (clock_mutex_);
        std::ostringstream os;
        os.precision (12);
        os << "mode=" << (tsync_supported_.load () ? (have_fit_ ? "tsync" : "tsync_warmup") : "arrival")
           << " host0=" << fit_host0_ << " dev0=" << fit_dev0_ << " a=" << fit_a_
           << " b=" << fit_b_ << " unc_ms=" << fit_uncertainty_ms_
           << " samples=" << tsync_samples_.size ();
        response = os.str ();
        return (int)BrainFlowExitCodes::STATUS_OK;
    }
    if (ctrl_socket_ < 0)
    {
        response = "NO_CONTROL_SOCKET";
        return (int)BrainFlowExitCodes::BOARD_NOT_READY_ERROR;
    }
    if (config.empty ())
    {
        response = "EMPTY_CONFIG";
        return (int)BrainFlowExitCodes::INVALID_ARGUMENTS_ERROR;
    }

    std::lock_guard<std::mutex> lock (ctrl_mutex_);
    if (!send_ctrl_locked (config))
    {
        response = "SEND_ERROR";
        return (int)BrainFlowExitCodes::BOARD_WRITE_ERROR;
    }
    char buf[1024];
    auto deadline = std::chrono::steady_clock::now () + std::chrono::milliseconds (CTRL_TIMEOUT_MS);
    response = "TIMEOUT"; // some commands (adc_reset, start_cnt) do not answer
    while (std::chrono::steady_clock::now () < deadline)
    {
        int left = (int)std::chrono::duration_cast<std::chrono::milliseconds> (
            deadline - std::chrono::steady_clock::now ())
                       .count ();
        int n = recv_ctrl_locked (buf, sizeof (buf), std::max (1, left));
        if (n == 0)
        {
            break;
        }
        // skip clock-sync traffic (and the ERR an unpatched firmware returns for TSYNC)
        if ((n < 0) || (strstr (buf, "TSYNC") != nullptr) || (strstr (buf, "tsync") != nullptr) ||
            (strncmp (buf, "ID ", 3) == 0))
        {
            continue;
        }
        response = std::string (buf);
        break;
    }
    if (response.find ("ERR") != std::string::npos)
    {
        safe_logger (spdlog::level::err, "Board rejected '{}': {}", config, response);
        return (int)BrainFlowExitCodes::BOARD_WRITE_ERROR;
    }
    track_gain_command (config);
    return (int)BrainFlowExitCodes::STATUS_OK;
}

void MeowerBoard::track_gain_command (const std::string &cmd)
{
    std::istringstream is (cmd);
    std::string family, name, a, b;
    is >> family >> name >> a >> b;
    auto lower = [] (std::string s)
    {
        std::transform (s.begin (), s.end (), s.begin (), ::tolower);
        return s;
    };
    family = lower (family);
    name = lower (name);
    try
    {
        if ((family == "usr") && (name == "gain") && !b.empty ())
        {
            double g = std::stod (b);
            if (lower (a) == "all")
            {
                for (int i = 0; i < CHANNELS; i++)
                    pga_gain_[i] = g;
            }
            else
            {
                int ch = std::stoi (a);
                if ((ch >= 0) && (ch < CHANNELS))
                    pga_gain_[ch] = g;
            }
        }
        else if ((family == "sys") && (name == "digitalgain") && !a.empty ())
        {
            digital_gain_ = std::stod (a);
        }
        else if ((family == "usr") && (name == "set_sampling_freq"))
        {
            reset_rate_estimator_ = true;
        }
    }
    catch (...)
    {
    }
}

// ====================================================================
//                            CLOCK MODEL
// ====================================================================

void MeowerBoard::refit_clock_locked ()
{
    // Keep the probes with the smallest round-trip (least queuing delay), then fit
    // host_mid = host0 + a + b * (dev_mid - dev0) by least squares.
    const size_t n = tsync_samples_.size ();
    if (n < 3)
    {
        have_fit_ = false;
        return;
    }
    std::vector<double> rtts;
    rtts.reserve (n);
    for (const auto &s : tsync_samples_)
    {
        rtts.push_back ((s.t4 - s.t1) - (s.t3 - s.t2));
    }
    std::vector<double> sorted = rtts;
    std::sort (sorted.begin (), sorted.end ());
    double thr = sorted[std::min (n - 1, std::max ((size_t)2, (size_t)(n * 0.3)))];

    std::vector<double> xs, ys;
    double best_rtt = sorted[0];
    for (size_t i = 0; i < n; i++)
    {
        if (rtts[i] <= thr)
        {
            const auto &s = tsync_samples_[i];
            xs.push_back (0.5 * (s.t2 + s.t3));
            ys.push_back (0.5 * (s.t1 + s.t4));
        }
    }
    fit_dev0_ = xs.front ();
    fit_host0_ = ys.front ();
    const size_t m = xs.size ();
    double mx = 0, my = 0;
    for (size_t i = 0; i < m; i++)
    {
        mx += xs[i] - fit_dev0_;
        my += ys[i] - fit_host0_;
    }
    mx /= m;
    my /= m;
    double sxx = 0, sxy = 0;
    for (size_t i = 0; i < m; i++)
    {
        double dx = xs[i] - fit_dev0_ - mx;
        sxx += dx * dx;
        sxy += dx * (ys[i] - fit_host0_ - my);
    }
    double span = xs.back () - xs.front ();
    if ((span > 20.0) && (sxx > 0))
    {
        fit_b_ = sxy / sxx;
        // crystal tolerance sanity check (+-500 ppm)
        if (std::fabs (fit_b_ - 1.0) > 5e-4)
            fit_b_ = 1.0;
    }
    else
    {
        fit_b_ = 1.0;
    }
    fit_a_ = my - fit_b_ * mx;
    double ss = 0;
    for (size_t i = 0; i < m; i++)
    {
        double pred = fit_a_ + fit_b_ * (xs[i] - fit_dev0_);
        double r = (ys[i] - fit_host0_) - pred;
        ss += r * r;
    }
    double resid_ms = std::sqrt (ss / m) * 1000.0;
    fit_uncertainty_ms_ = 0.5 * best_rtt * 1000.0 + resid_ms;
    have_fit_ = true;
}

double MeowerBoard::device_to_host (double dev_s, double arrival_host_s, double *uncertainty_ms)
{
    std::lock_guard<std::mutex> lock (clock_mutex_);
    if (have_fit_)
    {
        *uncertainty_ms = fit_uncertainty_ms_;
        return fit_host0_ + fit_a_ + fit_b_ * (dev_s - fit_dev0_);
    }
    // fallback: offset = sliding minimum of (arrival - device time) over FALLBACK_WINDOW_S
    // monotonic deque -> O(1) amortised sliding minimum
    double off = arrival_host_s - dev_s;
    while (!arrival_offsets_.empty () && (arrival_offsets_.back ().second >= off))
    {
        arrival_offsets_.pop_back ();
    }
    arrival_offsets_.push_back ({arrival_host_s, off});
    while (arrival_host_s - arrival_offsets_.front ().first > FALLBACK_WINDOW_S)
    {
        arrival_offsets_.pop_front ();
    }
    const double min_off = arrival_offsets_.front ().second;
    *uncertainty_ms = (off - min_off) * 1000.0;
    return dev_s + min_off;
}

uint64_t MeowerBoard::unwrap_ticks (uint32_t tick32)
{
    // choose the 64-bit value closest to the last reference (TSYNC reply or previous frame)
    if (!have_tick_ref_)
    {
        last_tick_ref_ = tick32;
        have_tick_ref_ = true;
        return tick32;
    }
    uint64_t ref = last_tick_ref_;
    int32_t delta = (int32_t)(tick32 - (uint32_t)(ref & 0xFFFFFFFFu));
    uint64_t value = (uint64_t)((int64_t)ref + delta);
    last_tick_ref_ = value;
    return value;
}

// ====================================================================
//                            DATA THREAD
// ====================================================================

void MeowerBoard::read_thread ()
{
    int num_rows = NUM_ROWS;
    std::vector<int> eeg_rows (CHANNELS);
    for (int i = 0; i < CHANNELS; i++)
        eeg_rows[i] = i;
    int battery_row = ROW_BATTERY, ts_row = ROW_TIMESTAMP, pkg_row = ROW_PACKAGE;
    try
    {
        num_rows = board_descr["default"]["num_rows"];
        eeg_rows = board_descr["default"]["eeg_channels"].get<std::vector<int>> ();
        battery_row = board_descr["default"]["battery_channel"];
        ts_row = board_descr["default"]["timestamp_channel"];
        pkg_row = board_descr["default"]["package_num_channel"];
    }
    catch (...)
    {
        safe_logger (spdlog::level::warn, "Board descriptor incomplete, using defaults");
    }

    std::vector<double> package (num_rows, 0.0);
    std::vector<unsigned char> buf (RECV_BUFFER_SIZE);
    double frame_counter = 0;
    double lost_frames = 0;
    uint64_t prev_tick = 0;
    bool have_prev = false;
    std::vector<uint64_t> deltas;
    double nominal_dt_ticks = 0;
    bool have_out = false;
    double last_out_ts = 0.0, last_out_dev = 0.0;

    while (keep_alive_)
    {
        int n = data_srv_->recv (buf.data (), (int)buf.size ());
        double arrival = get_timestamp ();
        if (n <= 0)
            continue;
        if ((n < FRAME_SIZE + BATTERY_SIZE) || ((n - BATTERY_SIZE) % FRAME_SIZE != 0))
        {
            safe_logger (spdlog::level::trace, "Bad packet size {}", n);
            continue;
        }
        if (reset_rate_estimator_.exchange (false))
        {
            deltas.clear ();
            nominal_dt_ticks = 0;
            have_prev = false;
        }
        const int frames = (n - BATTERY_SIZE) / FRAME_SIZE;
        float battery;
        memcpy (&battery, &buf[n - BATTERY_SIZE], sizeof (float));

        // device time of the last frame in the datagram (closest to arrival)
        uint32_t last_tick32;
        memcpy (&last_tick32, &buf[(frames - 1) * FRAME_SIZE + CHANNEL_DATA_SIZE], 4);

        for (int f = 0; f < frames; f++)
        {
            const unsigned char *fr = &buf[f * FRAME_SIZE];
            const double dgain = digital_gain_;
            for (int ch = 0; ch < CHANNELS && ch < (int)eeg_rows.size (); ch++)
            {
                const unsigned char *p = fr + ch * BYTES_PER_CHANNEL;
                uint32_t raw24 = ((uint32_t)p[0] << 16) | ((uint32_t)p[1] << 8) | p[2];
                int32_t value = (int32_t)(raw24 << 8) >> 8;
                package[eeg_rows[ch]] = value * ADS1299_LSB_UV / (pga_gain_[ch] * dgain);
            }
            if (ads_count_ == 1)
            {
                // 8-channel board: slot 16 carries the master's status word, not a channel
                const unsigned char *st = fr + 15 * BYTES_PER_CHANNEL;
                const uint32_t status = ((uint32_t)st[0] << 16) | ((uint32_t)st[1] << 8) | st[2];
                for (int ch = 8; ch < CHANNELS && ch < (int)eeg_rows.size (); ch++)
                    package[eeg_rows[ch]] = 0.0;
                if (ROW_STATUS < num_rows)
                    package[ROW_STATUS] = (double)status;
            }
            uint32_t tick32;
            memcpy (&tick32, fr + CHANNEL_DATA_SIZE, 4);
            uint64_t tick = unwrap_ticks (tick32);

            // frame-loss accounting from the tick spacing
            if (have_prev)
            {
                uint64_t d = tick - prev_tick;
                if (nominal_dt_ticks <= 0)
                {
                    deltas.push_back (d);
                    if (deltas.size () >= 64)
                    {
                        std::nth_element (
                            deltas.begin (), deltas.begin () + deltas.size () / 2, deltas.end ());
                        nominal_dt_ticks = (double)deltas[deltas.size () / 2];
                    }
                }
                else if (d > 1.5 * nominal_dt_ticks)
                {
                    lost_frames += std::round (d / nominal_dt_ticks) - 1.0;
                }
            }
            prev_tick = tick;
            have_prev = true;

            const double dev_s = tick * TICK_S;
            // arrival time of this frame ~ arrival of datagram minus the frames after it
            const double frame_arrival =
                arrival - ((double)(uint32_t)(last_tick32 - tick32)) * TICK_S;
            double unc_ms = 0;
            const double target_ts = device_to_host (dev_s, frame_arrival, &unc_ms);
            // slew: follow the clock model at most MAX_SLEW s/s, so timestamps stay continuous
            // and strictly increasing when the fit is updated (steps only if error > 100 ms)
            double host_ts = target_ts;
            if (have_out)
            {
                const double elapsed = std::max (0.0, dev_s - last_out_dev);
                const double predicted = last_out_ts + elapsed;
                const double err = target_ts - predicted;
                const double max_step = MAX_SLEW * elapsed;
                if (std::fabs (err) <= STEP_THRESHOLD_S)
                {
                    host_ts = predicted + std::max (-max_step, std::min (max_step, err));
                }
            }
            last_out_ts = host_ts;
            last_out_dev = dev_s;
            have_out = true;

            if (battery_row >= 0 && battery_row < num_rows)
                package[battery_row] = battery;
            if (ts_row >= 0 && ts_row < num_rows)
                package[ts_row] = host_ts;
            if (pkg_row >= 0 && pkg_row < num_rows)
                package[pkg_row] = frame_counter;
            if (ROW_DEVICE_TIME < num_rows)
                package[ROW_DEVICE_TIME] = dev_s;
            if (ROW_SYNC_UNC < num_rows)
                package[ROW_SYNC_UNC] = unc_ms;
            if (ROW_LOST < num_rows)
                package[ROW_LOST] = lost_frames;
            if (ROW_MARKER < num_rows)
                package[ROW_MARKER] = 0.0;
            push_package (package.data (), (int)BrainFlowPresets::DEFAULT_PRESET);
            frame_counter += 1.0;
        }
    }
}

// ====================================================================
//                     KEEP-ALIVE + CLOCK SYNC THREAD
// ====================================================================

void MeowerBoard::ping_thread ()
{
    auto last_keepalive = std::chrono::steady_clock::now () - std::chrono::hours (1);
    auto last_tsync = last_keepalive;
    while (keep_ping_)
    {
        auto now = std::chrono::steady_clock::now ();
        {
            std::lock_guard<std::mutex> lock (ctrl_mutex_);
            if (now - last_keepalive >= std::chrono::milliseconds (KEEPALIVE_INTERVAL_MS))
            {
                send_ctrl_locked ("WOOF_WOOF");
                last_keepalive = now;
            }
            // keep probing even if the firmware lacked TSYNC at start (reflash / reboot)
            int interval = tsync_supported_ ? tsync_interval_ms_ : 10000;
            if (now - last_tsync >= std::chrono::milliseconds (interval))
            {
                if (tsync_once_locked (TSYNC_REPLY_TIMEOUT_MS))
                {
                    tsync_supported_ = true;
                }
                last_tsync = now;
            }
        }
        sleep_ms (50);
    }
}

// ====================================================================
//                            DISCOVERY
// ====================================================================

bool MeowerBoard::wait_for_beacon (int timeout_ms)
{
    int sock = (int)socket (AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sock < 0)
        return false;
    int reuse = 1;
    setsockopt (sock, SOL_SOCKET, SO_REUSEADDR, (const char *)&reuse, sizeof (reuse));
    struct sockaddr_in addr;
    memset (&addr, 0, sizeof (addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons (ctrl_port_);
    if (bind (sock, (struct sockaddr *)&addr, sizeof (addr)) < 0)
    {
        close_raw_socket (sock);
        return false;
    }
#ifdef _WIN32
    u_long nb = 1;
    ioctlsocket (sock, FIONBIO, &nb);
#else
    fcntl (sock, F_SETFL, fcntl (sock, F_GETFL, 0) | O_NONBLOCK);
#endif
    auto start = std::chrono::steady_clock::now ();
    char buf[256];
    bool found = false;
    while (!found &&
        std::chrono::steady_clock::now () - start < std::chrono::milliseconds (timeout_ms))
    {
        struct sockaddr_in from;
        socklen_t len = sizeof (from);
        int n = (int)recvfrom (sock, buf, sizeof (buf) - 1, 0, (struct sockaddr *)&from, &len);
        if ((n >= 9) && (strncmp (buf, "MEOW_MEOW", 9) == 0))
        {
            char ip[INET_ADDRSTRLEN];
            inet_ntop (AF_INET, &from.sin_addr, ip, INET_ADDRSTRLEN);
            board_ip_ = ip;
            found = true;
        }
        else
        {
            sleep_ms (10);
        }
    }
    close_raw_socket (sock);
    return found;
}
