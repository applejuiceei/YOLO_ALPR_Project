#include "camera/camera_manager.hpp"

#include <algorithm>
#include <chrono>
#include <cctype>
#include <opencv2/videoio.hpp>
#include <stdexcept>

namespace vehicle_system {

CameraManager::CameraManager(CameraConfig config)
    : config_(std::move(config)), queue_(config_.queue_capacity) {}

CameraManager::~CameraManager() {
    stop();
}

void CameraManager::start() {
    if (capture_thread_.joinable()) {
        throw std::runtime_error("CameraManager is already running");
    }
    stop_requested_ = false;
    capture_thread_ = std::thread(&CameraManager::capture_loop, this);
}

void CameraManager::stop() {
    stop_requested_ = true;
    queue_.close();
    if (capture_thread_.joinable()) {
        capture_thread_.join();
    }
}

bool CameraManager::wait_frame(FramePacket& packet) {
    return queue_.wait_pop(packet);
}

void CameraManager::capture_loop() {
    cv::VideoCapture capture;
    const bool numeric_source = !config_.source.empty() &&
        std::all_of(config_.source.begin(), config_.source.end(), [](unsigned char value) { return std::isdigit(value) != 0; });
    if (numeric_source) {
        capture.open(std::stoi(config_.source), cv::CAP_ANY);
    } else {
        capture.open(config_.source, cv::CAP_ANY);
    }
    if (!capture.isOpened()) {
        last_error_ = "Cannot open camera source: " + config_.source;
        queue_.close();
        return;
    }

    source_fps_ = capture.get(cv::CAP_PROP_FPS);
    if (source_fps_ <= 0.0 || source_fps_ > 240.0) {
        source_fps_ = 30.0;
    }
    frame_width_ = static_cast<int>(capture.get(cv::CAP_PROP_FRAME_WIDTH));
    frame_height_ = static_cast<int>(capture.get(cv::CAP_PROP_FRAME_HEIGHT));

    const auto frame_period = std::chrono::duration<double>(1.0 / source_fps_);
    auto next_deadline = std::chrono::steady_clock::now();
    std::uint64_t frame_id = 0;

    while (!stop_requested_) {
        cv::Mat frame;
        if (!capture.read(frame) || frame.empty()) {
            break;
        }
        if (config_.realtime_playback && !numeric_source) {
            next_deadline += std::chrono::duration_cast<std::chrono::steady_clock::duration>(frame_period);
            std::this_thread::sleep_until(next_deadline);
        }

        FramePacket packet;
        packet.camera_id = config_.camera_id;
        packet.lane_id = config_.lane_id;
        packet.frame_id = frame_id++;
        packet.timestamp = std::chrono::system_clock::now();
        packet.frame = std::move(frame);
        queue_.push(std::move(packet));
    }

    capture.release();
    queue_.close();
}

}  // namespace vehicle_system

