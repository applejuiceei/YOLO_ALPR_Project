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

struct PlateDetectorConfig {
    std::string backend = "onnxruntime";
    std::filesystem::path model_path;
    int input_width = 320;
    int input_height = 320;
    float confidence = 0.25F;
    float nms = 0.45F;
    int max_detections = 3;
    int intra_op_threads = 2;
};

struct PlateCropperConfig {
    float expand_left = 0.0F;
    float expand_right = 0.0F;
    float expand_top = 0.0F;
    float expand_bottom = 0.0F;
    int min_width = 8;
    int min_height = 4;
    bool clone_output = false;
};

struct PlateQualityConfig {
    std::string backend = "opencv";
    int min_width = 24;
    int min_height = 8;
    int target_width = 64;
    int target_height = 20;
    float min_blur_score = 20.0F;
    float min_brightness = 30.0F;
    float max_brightness = 245.0F;
    float target_brightness = 127.5F;
    float min_contrast = 10.0F;
    float sharpness_reference = 10000.0F;
    float contrast_reference = 48.0F;
    float min_quality_score = 0.50F;
    float size_weight = 0.40F;
    float sharpness_weight = 0.25F;
    float exposure_weight = 0.20F;
    float contrast_weight = 0.15F;
};

struct PlateRectifierConfig {
    std::string backend = "opencv";
    std::string mode = "perspective";
    int output_width = 320;
    int output_height = 96;
    float min_edge_length = 2.0F;
    float min_quadrilateral_area = 16.0F;
    float corner_tolerance = 2.0F;
    float max_abs_rotation_degrees = 60.0F;
    bool fallback_to_resize = true;
};

struct PlateColorConfig {
    std::string backend = "hsv";
    float roi_margin_x_ratio = 0.03F;
    float roi_margin_y_ratio = 0.05F;
    int min_saturation = 25;
    int chromatic_min_value = 70;
    int white_max_saturation = 24;
    int white_min_value = 140;
    int black_max_value = 69;
    int yellow_hue_min = 15;
    int yellow_hue_max = 34;
    int green_hue_min = 35;
    int green_hue_max = 89;
    int blue_hue_min = 90;
    int blue_hue_max = 140;
    float min_coverage = 0.30F;
    float min_dominance_margin = 0.05F;
};

struct PlateRecognizerConfig {
    std::string backend = "onnxruntime";
    std::filesystem::path model_path;
    int input_width = 160;
    int input_height = 48;
    std::string input_color_order = "bgr";
    float min_confidence = 0.50F;
    int min_text_length = 7;
    int max_text_length = 8;
    bool require_standard_format = true;
    int intra_op_threads = 2;
    int warmup_runs = 1;
};

struct PlateFusionConfig {
    std::string backend = "confidence_weighted";
    int max_history_per_track = 30;
    int top_k = 10;
    int min_samples = 3;
    int min_winner_samples = 2;
    float min_ocr_confidence = 0.50F;
    float min_quality_score = 0.50F;
    float min_vote_ratio = 0.50F;
    float min_color_confidence = 0.30F;
    int stale_after_frames = 60;
    bool include_other_color = false;
};

struct TextRendererConfig {
    std::string backend = "windows_gdi";
    std::string font_family = "Microsoft YaHei";
    int font_height = 22;
    int horizontal_padding = 6;
    int vertical_padding = 3;
};

struct RuntimeConfig {
    bool display = true;
    int max_frames = 610;
    int report_interval = 60;
    std::filesystem::path output_video;
    std::filesystem::path summary_json;
    std::filesystem::path vehicle_roi_dir;
    int max_saved_vehicle_rois = 64;
    std::filesystem::path plate_roi_dir;
    int max_saved_plate_rois = 64;
    std::filesystem::path rectified_plate_dir;
    int max_saved_rectified_plates = 64;
    std::filesystem::path ocr_results_jsonl;
    std::filesystem::path plate_fusion_results_jsonl;
};

struct AppConfig {
    std::filesystem::path project_root;
    CameraConfig camera;
    DetectorConfig detector;
    VehicleCropperConfig cropper;
    VehicleColorConfig vehicle_color;
    TrackerConfig tracker;
    VehicleFusionConfig vehicle_fusion;
    PlateDetectorConfig plate_detector;
    PlateCropperConfig plate_cropper;
    PlateQualityConfig plate_quality;
    PlateRectifierConfig plate_rectifier;
    PlateColorConfig plate_color;
    PlateRecognizerConfig plate_recognizer;
    PlateFusionConfig plate_fusion;
    TextRendererConfig text_renderer;
    RuntimeConfig runtime;
};

AppConfig load_config(const std::filesystem::path& config_path);

}  // namespace vehicle_system
