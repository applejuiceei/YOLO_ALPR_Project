#include "common/config.hpp"

#include <opencv2/core.hpp>
#include <stdexcept>

namespace vehicle_system {
namespace {

std::filesystem::path resolve_path(const std::filesystem::path& root, const std::string& value) {
    std::filesystem::path path = std::filesystem::u8path(value);
    if (path.is_relative()) {
        path = root / path;
    }
    return path.lexically_normal();
}

int read_int(const cv::FileNode& node, const char* key, int fallback) {
    const cv::FileNode value = node[key];
    return value.empty() ? fallback : static_cast<int>(value);
}

double read_double(const cv::FileNode& node, const char* key, double fallback) {
    const cv::FileNode value = node[key];
    return value.empty() ? fallback : static_cast<double>(value);
}

std::string read_string(const cv::FileNode& node, const char* key, const std::string& fallback = {}) {
    const cv::FileNode value = node[key];
    return value.empty() ? fallback : static_cast<std::string>(value);
}

}  // namespace

AppConfig load_config(const std::filesystem::path& config_path) {
    const std::filesystem::path absolute_config = std::filesystem::absolute(config_path);
    cv::FileStorage storage(absolute_config.u8string(), cv::FileStorage::READ);
    if (!storage.isOpened()) {
        throw std::runtime_error("Cannot open config: " + absolute_config.u8string());
    }

    AppConfig config;
    config.project_root = absolute_config.parent_path().parent_path();

    const cv::FileNode camera = storage["camera"];
    config.camera.camera_id = read_int(camera, "camera_id", 1);
    config.camera.lane_id = read_int(camera, "lane_id", 1);
    const std::string source = read_string(camera, "source");
    if (source.empty()) {
        throw std::runtime_error("camera.source is required");
    }
    const bool numeric_source = source.find_first_not_of("0123456789") == std::string::npos;
    config.camera.source = numeric_source ? source : resolve_path(config.project_root, source).u8string();
    config.camera.queue_capacity = static_cast<std::size_t>(read_int(camera, "queue_capacity", 2));
    config.camera.realtime_playback = read_int(camera, "realtime_playback", 1) != 0;

    const cv::FileNode detector = storage["vehicle_detector"];
    config.detector.backend = read_string(detector, "backend", "onnxruntime");
    config.detector.model_path = resolve_path(config.project_root, read_string(detector, "model"));
    config.detector.input_width = read_int(detector, "input_width", 640);
    config.detector.input_height = read_int(detector, "input_height", 640);
    config.detector.confidence = static_cast<float>(read_double(detector, "confidence", 0.4));
    config.detector.nms = static_cast<float>(read_double(detector, "nms", 0.45));
    config.detector.intra_op_threads = read_int(detector, "intra_op_threads", 4);

    const cv::FileNode cropper = storage["vehicle_cropper"];
    config.cropper.expand_left = static_cast<float>(read_double(cropper, "expand_left", 0.0));
    config.cropper.expand_right = static_cast<float>(read_double(cropper, "expand_right", 0.0));
    config.cropper.expand_top = static_cast<float>(read_double(cropper, "expand_top", 0.0));
    config.cropper.expand_bottom = static_cast<float>(read_double(cropper, "expand_bottom", 0.0));
    config.cropper.min_width = read_int(cropper, "min_width", 16);
    config.cropper.min_height = read_int(cropper, "min_height", 16);
    config.cropper.clone_output = read_int(cropper, "clone_output", 0) != 0;

    const cv::FileNode vehicle_color = storage["vehicle_color"];
    config.vehicle_color.backend = read_string(vehicle_color, "backend", "onnxruntime");
    config.vehicle_color.model_path = resolve_path(
        config.project_root, read_string(vehicle_color, "model"));
    config.vehicle_color.input_width = read_int(vehicle_color, "input_width", 256);
    config.vehicle_color.input_height = read_int(vehicle_color, "input_height", 192);
    config.vehicle_color.confidence = static_cast<float>(read_double(vehicle_color, "confidence", 0.5));
    config.vehicle_color.intra_op_threads = read_int(vehicle_color, "intra_op_threads", 2);

    const cv::FileNode tracker = storage["vehicle_tracker"];
    config.tracker.backend = read_string(tracker, "backend", "bytetrack");
    config.tracker.high_confidence = static_cast<float>(read_double(tracker, "high_confidence", 0.4));
    config.tracker.low_confidence = static_cast<float>(read_double(tracker, "low_confidence", 0.1));
    config.tracker.new_track_confidence = static_cast<float>(
        read_double(tracker, "new_track_confidence", 0.5));
    config.tracker.first_match_threshold = static_cast<float>(
        read_double(tracker, "first_match_threshold", 0.8));
    config.tracker.second_match_threshold = static_cast<float>(
        read_double(tracker, "second_match_threshold", 0.5));
    config.tracker.unconfirmed_match_threshold = static_cast<float>(
        read_double(tracker, "unconfirmed_match_threshold", 0.7));
    config.tracker.track_buffer_frames = read_int(tracker, "track_buffer_frames", 30);
    config.tracker.class_aware = read_int(tracker, "class_aware", 1) != 0;

    const cv::FileNode vehicle_fusion = storage["vehicle_fusion"];
    config.vehicle_fusion.backend = read_string(
        vehicle_fusion, "backend", "confidence_weighted");
    config.vehicle_fusion.max_history_per_track = read_int(
        vehicle_fusion, "max_history_per_track", 30);
    config.vehicle_fusion.min_samples = read_int(vehicle_fusion, "min_samples", 3);
    config.vehicle_fusion.min_sample_confidence = static_cast<float>(
        read_double(vehicle_fusion, "min_sample_confidence", 0.5));
    config.vehicle_fusion.min_vote_ratio = static_cast<float>(
        read_double(vehicle_fusion, "min_vote_ratio", 0.6));
    config.vehicle_fusion.stale_after_frames = read_int(
        vehicle_fusion, "stale_after_frames", 60);
    config.vehicle_fusion.include_other = read_int(vehicle_fusion, "include_other", 0) != 0;

    const cv::FileNode runtime = storage["runtime"];
    config.runtime.display = read_int(runtime, "display", 1) != 0;
    config.runtime.max_frames = read_int(runtime, "max_frames", 610);
    config.runtime.report_interval = read_int(runtime, "report_interval", 60);
    config.runtime.output_video = resolve_path(config.project_root, read_string(runtime, "output_video"));
    config.runtime.summary_json = resolve_path(config.project_root, read_string(runtime, "summary_json"));
    const std::string vehicle_roi_dir = read_string(runtime, "vehicle_roi_dir");
    if (!vehicle_roi_dir.empty()) {
        config.runtime.vehicle_roi_dir = resolve_path(config.project_root, vehicle_roi_dir);
    }
    config.runtime.max_saved_vehicle_rois = read_int(runtime, "max_saved_vehicle_rois", 64);
    return config;
}

}  // namespace vehicle_system
