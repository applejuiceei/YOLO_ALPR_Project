#pragma once

#include <filesystem>
#include <string>

namespace vehicle_system {

struct CameraConfig {
    int camera_id = 1;
    int lane_id = 1;
    std::string source;
    std::size_t queue_capacity = 2;
    bool realtime_playback = true;
};

struct DetectorConfig {
    std::string backend = "onnxruntime";
    std::filesystem::path model_path;
    int input_width = 640;
    int input_height = 640;
    float confidence = 0.4F;
    float nms = 0.45F;
    int intra_op_threads = 4;
};

struct VehicleCropperConfig {
    float expand_left = 0.0F;
    float expand_right = 0.0F;
    float expand_top = 0.0F;
    float expand_bottom = 0.0F;
    int min_width = 16;
    int min_height = 16;
    bool clone_output = false;
};

struct VehicleColorConfig {
    std::string backend = "onnxruntime";
    std::filesystem::path model_path;
    int input_width = 256;
    int input_height = 192;
    float confidence = 0.5F;
    int intra_op_threads = 2;
};

struct TrackerConfig {
    std::string backend = "bytetrack";
    float high_confidence = 0.4F;
    float low_confidence = 0.1F;
    float new_track_confidence = 0.5F;
    float first_match_threshold = 0.8F;
    float second_match_threshold = 0.5F;
    float unconfirmed_match_threshold = 0.7F;
    int track_buffer_frames = 30;
    bool class_aware = true;
};

struct VehicleFusionConfig {
    std::string backend = "confidence_weighted";
    int max_history_per_track = 30;
    int min_samples = 3;
    float min_sample_confidence = 0.5F;
    float min_vote_ratio = 0.6F;
    int stale_after_frames = 60;
    bool include_other = false;
};

struct RuntimeConfig {
    bool display = true;
    int max_frames = 610;
    int report_interval = 60;
    std::filesystem::path output_video;
    std::filesystem::path summary_json;
    std::filesystem::path vehicle_roi_dir;
    int max_saved_vehicle_rois = 64;
};

struct AppConfig {
    std::filesystem::path project_root;
    CameraConfig camera;
    DetectorConfig detector;
    VehicleCropperConfig cropper;
    VehicleColorConfig vehicle_color;
    TrackerConfig tracker;
    VehicleFusionConfig vehicle_fusion;
    RuntimeConfig runtime;
};

AppConfig load_config(const std::filesystem::path& config_path);

}  // namespace vehicle_system
