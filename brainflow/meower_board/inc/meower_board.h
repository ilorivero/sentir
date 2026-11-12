#pragma once
/*********************************************************************
 * meower_board.h - BrainFlow UDP driver for the Meower EEG board
 * (ESP32-C3 + 2x ADS1299, 16 channels) - SENTIR edition.
 *
 * Based on the VRChatBoard driver by Gleb Manokhin (nikki), MIT/Apache-2.0,
 * https://github.com/nikki-uwu/Meower  (BrainFlow_files/vrchatboard)
 *
 * Differences from the original driver:
 *  - Keep-alive uses "WOOF_WOOF" (what the current Meower firmware expects;
 *    the original driver sent "floof", which the firmware ignores).
 *  - Clock synchronisation: NTP-style "TSYNC" probes on the control port
 *    (needs firmware patch 0001-sentir-tsync-and-id). A robust linear fit
 *    (offset + drift) maps board ticks to host UNIX time. If the firmware
 *    does not answer TSYNC, falls back to a min-delay estimator on packet
 *    arrival times.
 *  - 32-bit tick counter is unwrapped (wraps every ~9.5 h).
 *  - EEG rows in microvolts, using PGA / digital gain tracked from the
 *    config_board() commands that set them.
 *  - Raw device time, frame counter, lost-frame counter and sync
 *    uncertainty exported as extra rows.
 *  - Every TSYNC exchange is pushed to the ANCILLARY preset so the host
 *    application can re-fit the clock offline.
 *
 * DEFAULT preset rows (num_rows = 24):
 *   0..15  EEG (uV)               16 battery (V)
 *   17     timestamp (host UNIX s, synchronised)
 *   18     device time (s, unwrapped, board clock)
 *   19     package_num (frame counter)
 *   20     marker                  21 sync uncertainty (ms)
 *   22     lost frames (cumulative)
 *   23     ADS1299 status word (8-channel board only, see below; 0 otherwise)
 *
 * 8-channel board (one ADS1299, SENTIR firmware reports "ads=1" in its ID reply): rows 8..15
 * are zero and the raw 24-bit status word of the master chip (sent by the firmware in the
 * channel-16 slot) is copied, unsigned, to row 23:
 *   [23:20]=1100 [19:12]=LOFF_STATP [11:4]=LOFF_STATN [3:0]=GPIO4..1 (GPIO1 = photodiode)
 *
 * ANCILLARY preset rows (num_rows = 9):
 *   0 seq, 1 t1 host send (s), 2 t2 board rx (s), 3 t3 board tx (s),
 *   4 t4 host recv (s), 5 rtt (ms), 6 offset host-board (s),
 *   7 timestamp, 8 marker
 *
 * params.other_info (space separated key=value):
 *   discovery_timeout=3000  tsync_interval_ms=1000  tsync_window=120
 *   pga_gain=1  digital_gain=1
 *   board_ctrl_port=5100   (only for tools/meower_sim.py on the same PC)
 *   ads_count=1 or 2       (override the number of ADS1299 reported by the board)
 *********************************************************************/

#include <atomic>
#include <deque>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "board.h"
#include "board_controller.h"
#include "socket_server_udp.h"


class MeowerBoard : public Board
{
public:
    MeowerBoard (int board_id, struct BrainFlowInputParams params);
    ~MeowerBoard () override;

    int prepare_session () override;
    int start_stream (int buffer_size, const char *streamer_params) override;
    int stop_stream () override;
    int release_session () override;
    int config_board (std::string config, std::string &response) override;

private:
    struct TsyncSample
    {
        double seq;
        double t1, t2, t3, t4; // host / device seconds
    };

    void read_thread ();
    void ping_thread ();
    void close_sockets ();
    bool wait_for_beacon (int timeout_ms);

    // control socket helpers (caller must hold ctrl_mutex_)
    bool send_ctrl_locked (const std::string &msg);
    int recv_ctrl_locked (char *buf, int size, int timeout_ms);
    bool tsync_once_locked (int timeout_ms);

    // clock model
    void refit_clock_locked ();
    double device_to_host (double dev_s, double arrival_host_s, double *uncertainty_ms);
    uint64_t unwrap_ticks (uint32_t tick32);
    void track_gain_command (const std::string &cmd);
    int get_option_int (const std::string &key, int def) const;

    SocketServerUDP *data_srv_ {nullptr};
    int ctrl_socket_ {-1};
    std::mutex ctrl_mutex_;

    std::atomic<bool> keep_alive_ {false};
    std::atomic<bool> keep_ping_ {false};
    std::thread read_th_;
    std::thread ping_th_;

    bool initialized_ {false};
    std::atomic<bool> streaming_ {false};

    int data_port_ {5001};
    int ctrl_port_ {5000};
    int board_ctrl_port_ {5000}; // destination port on the board (differs only for the local simulator)
    std::string board_ip_;

#ifdef _WIN32
    bool wsa_initialized_ {false};
#endif

    // ----- clock sync state (guarded by clock_mutex_) -----
    std::mutex clock_mutex_;
    std::deque<TsyncSample> tsync_samples_;
    size_t tsync_window_ {120};
    int tsync_interval_ms_ {1000};
    uint32_t tsync_seq_ {0};
    int tsync_misses_ {0};
    std::atomic<bool> tsync_supported_ {false};
    bool have_fit_ {false};
    double fit_host0_ {0.0}, fit_dev0_ {0.0}, fit_a_ {0.0}, fit_b_ {1.0};
    double fit_uncertainty_ms_ {0.0};
    // fallback estimator: sliding minimum of (arrival - device time)
    std::deque<std::pair<double, double>> arrival_offsets_; // (host_time, offset)

    // tick unwrapping (only read thread + tsync reference)
    std::atomic<uint64_t> last_tick_ref_ {0};
    std::atomic<bool> have_tick_ref_ {false};

    // scaling
    std::atomic<double> pga_gain_[16];
    std::atomic<double> digital_gain_ {1.0};
    std::atomic<bool> reset_rate_estimator_ {false};

    // device identity (reply to "ID?", SENTIR firmware)
    std::string device_info_;
    std::atomic<int> ads_count_ {2};
    std::atomic<bool> fake_adc_ {false};
};
