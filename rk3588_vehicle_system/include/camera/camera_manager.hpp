#pragma once

#include "camera/frame_queue.hpp"
#include "common/config.hpp"

#include <atomic>
#include <cstdint>
#include <string>
#include <thread>

namespace vehicle_system {

class CameraManager {
public:
    explicit CameraManager(CameraConfig config);
    ~CameraManager();

    CameraManager(const CameraManager&) = delete;
    CameraManager& operator=(const CameraManager&) = delete;

    void start();
    void stop();
    bool wait_frame(FramePacket& packet);

    double source_fps() const { return source_fps_; }
    int frame_width() const { return frame_width_; }
    int frame_height() const { return frame_height_; }
    std::uint64_t dropped_frames() const { return queue_.dropped(); }
    const std::string& last_error() const { return last_error_; }

private:
    void capture_loop();

    CameraConfig config_;
    FrameQueue queue_;
    std::thread capture_thread_;
    std::atomic<bool> stop_requested_{false};
    double source_fps_ = 0.0;
    int frame_width_ = 0;
    int frame_height_ = 0;
    std::string last_error_;
};

}  // namespace vehicle_system

