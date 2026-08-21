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

    const cv::FileNode plate_detector = storage["plate_detector"];
    config.plate_detector.backend = read_string(plate_detector, "backend", "onnxruntime");
    config.plate_detector.model_path = resolve_path(
        config.project_root, read_string(plate_detector, "model"));
    config.plate_detector.input_width = read_int(plate_detector, "input_width", 320);
    config.plate_detector.input_height = read_int(plate_detector, "input_height", 320);
    config.plate_detector.confidence = static_cast<float>(
        read_double(plate_detector, "confidence", 0.25));
    config.plate_detector.nms = static_cast<float>(read_double(plate_detector, "nms", 0.45));
    config.plate_detector.max_detections = read_int(plate_detector, "max_detections", 3);
    config.plate_detector.intra_op_threads = read_int(plate_detector, "intra_op_threads", 2);

    const cv::FileNode plate_cropper = storage["plate_cropper"];
    config.plate_cropper.expand_left = static_cast<float>(
        read_double(plate_cropper, "expand_left", 0.0));
    config.plate_cropper.expand_right = static_cast<float>(
        read_double(plate_cropper, "expand_right", 0.0));
    config.plate_cropper.expand_top = static_cast<float>(
        read_double(plate_cropper, "expand_top", 0.0));
    config.plate_cropper.expand_bottom = static_cast<float>(
        read_double(plate_cropper, "expand_bottom", 0.0));
    config.plate_cropper.min_width = read_int(plate_cropper, "min_width", 8);
    config.plate_cropper.min_height = read_int(plate_cropper, "min_height", 4);
    config.plate_cropper.clone_output = read_int(plate_cropper, "clone_output", 0) != 0;

    const cv::FileNode plate_quality = storage["plate_quality"];
    config.plate_quality.backend = read_string(plate_quality, "backend", "opencv");
    config.plate_quality.min_width = read_int(plate_quality, "min_width", 24);
    config.plate_quality.min_height = read_int(plate_quality, "min_height", 8);
    config.plate_quality.target_width = read_int(plate_quality, "target_width", 64);
    config.plate_quality.target_height = read_int(plate_quality, "target_height", 20);
    config.plate_quality.min_blur_score = static_cast<float>(
        read_double(plate_quality, "min_blur_score", 20.0));
    config.plate_quality.min_brightness = static_cast<float>(
        read_double(plate_quality, "min_brightness", 30.0));
    config.plate_quality.max_brightness = static_cast<float>(
        read_double(plate_quality, "max_brightness", 245.0));
    config.plate_quality.target_brightness = static_cast<float>(
        read_double(plate_quality, "target_brightness", 127.5));
    config.plate_quality.min_contrast = static_cast<float>(
        read_double(plate_quality, "min_contrast", 10.0));
    config.plate_quality.sharpness_reference = static_cast<float>(
        read_double(plate_quality, "sharpness_reference", 10000.0));
    config.plate_quality.contrast_reference = static_cast<float>(
        read_double(plate_quality, "contrast_reference", 48.0));
    config.plate_quality.min_quality_score = static_cast<float>(
        read_double(plate_quality, "min_quality_score", 0.5));
    config.plate_quality.size_weight = static_cast<float>(
        read_double(plate_quality, "size_weight", 0.4));
    config.plate_quality.sharpness_weight = static_cast<float>(
        read_double(plate_quality, "sharpness_weight", 0.25));
    config.plate_quality.exposure_weight = static_cast<float>(
        read_double(plate_quality, "exposure_weight", 0.2));
    config.plate_quality.contrast_weight = static_cast<float>(
        read_double(plate_quality, "contrast_weight", 0.15));

    const cv::FileNode plate_rectifier = storage["plate_rectifier"];
    config.plate_rectifier.backend = read_string(plate_rectifier, "backend", "opencv");
    config.plate_rectifier.mode = read_string(plate_rectifier, "mode", "perspective");
    config.plate_rectifier.output_width = read_int(plate_rectifier, "output_width", 320);
    config.plate_rectifier.output_height = read_int(plate_rectifier, "output_height", 96);
    config.plate_rectifier.min_edge_length = static_cast<float>(
        read_double(plate_rectifier, "min_edge_length", 2.0));
    config.plate_rectifier.min_quadrilateral_area = static_cast<float>(
        read_double(plate_rectifier, "min_quadrilateral_area", 16.0));
    config.plate_rectifier.corner_tolerance = static_cast<float>(
        read_double(plate_rectifier, "corner_tolerance", 2.0));
    config.plate_rectifier.max_abs_rotation_degrees = static_cast<float>(
        read_double(plate_rectifier, "max_abs_rotation_degrees", 60.0));
    config.plate_rectifier.fallback_to_resize =
        read_int(plate_rectifier, "fallback_to_resize", 1) != 0;

    const cv::FileNode plate_color = storage["plate_color"];
    config.plate_color.backend = read_string(plate_color, "backend", "hsv");
    config.plate_color.roi_margin_x_ratio = static_cast<float>(
        read_double(plate_color, "roi_margin_x_ratio", 0.03));
    config.plate_color.roi_margin_y_ratio = static_cast<float>(
        read_double(plate_color, "roi_margin_y_ratio", 0.05));
    config.plate_color.min_saturation = read_int(plate_color, "min_saturation", 25);
    config.plate_color.chromatic_min_value = read_int(
        plate_color, "chromatic_min_value", 70);
    config.plate_color.white_max_saturation = read_int(
        plate_color, "white_max_saturation", 24);
    config.plate_color.white_min_value = read_int(plate_color, "white_min_value", 140);
    config.plate_color.black_max_value = read_int(plate_color, "black_max_value", 69);
    config.plate_color.yellow_hue_min = read_int(plate_color, "yellow_hue_min", 15);
    config.plate_color.yellow_hue_max = read_int(plate_color, "yellow_hue_max", 34);
    config.plate_color.green_hue_min = read_int(plate_color, "green_hue_min", 35);
    config.plate_color.green_hue_max = read_int(plate_color, "green_hue_max", 89);
    config.plate_color.blue_hue_min = read_int(plate_color, "blue_hue_min", 90);
    config.plate_color.blue_hue_max = read_int(plate_color, "blue_hue_max", 140);
    config.plate_color.min_coverage = static_cast<float>(
        read_double(plate_color, "min_coverage", 0.30));
    config.plate_color.min_dominance_margin = static_cast<float>(
        read_double(plate_color, "min_dominance_margin", 0.05));

    const cv::FileNode plate_recognizer = storage["plate_recognizer"];
    config.plate_recognizer.backend = read_string(
        plate_recognizer, "backend", "onnxruntime");
    config.plate_recognizer.model_path = resolve_path(
        config.project_root, read_string(plate_recognizer, "model"));
    config.plate_recognizer.input_width = read_int(plate_recognizer, "input_width", 160);
    config.plate_recognizer.input_height = read_int(plate_recognizer, "input_height", 48);
    config.plate_recognizer.input_color_order = read_string(
        plate_recognizer, "input_color_order", "bgr");
    config.plate_recognizer.min_confidence = static_cast<float>(
        read_double(plate_recognizer, "min_confidence", 0.50));
    config.plate_recognizer.min_text_length = read_int(
        plate_recognizer, "min_text_length", 7);
    config.plate_recognizer.max_text_length = read_int(
        plate_recognizer, "max_text_length", 8);
    config.plate_recognizer.require_standard_format =
        read_int(plate_recognizer, "require_standard_format", 1) != 0;
    config.plate_recognizer.intra_op_threads = read_int(
        plate_recognizer, "intra_op_threads", 2);
    config.plate_recognizer.warmup_runs = read_int(plate_recognizer, "warmup_runs", 1);

    const cv::FileNode plate_fusion = storage["plate_fusion"];
    config.plate_fusion.backend = read_string(
        plate_fusion, "backend", "confidence_weighted");
    config.plate_fusion.max_history_per_track = read_int(
        plate_fusion, "max_history_per_track", 30);
    config.plate_fusion.top_k = read_int(plate_fusion, "top_k", 10);
    config.plate_fusion.min_samples = read_int(plate_fusion, "min_samples", 3);
    config.plate_fusion.min_winner_samples = read_int(
        plate_fusion, "min_winner_samples", 2);
    config.plate_fusion.min_ocr_confidence = static_cast<float>(
        read_double(plate_fusion, "min_ocr_confidence", 0.50));
    config.plate_fusion.min_quality_score = static_cast<float>(
        read_double(plate_fusion, "min_quality_score", 0.50));
    config.plate_fusion.min_vote_ratio = static_cast<float>(
        read_double(plate_fusion, "min_vote_ratio", 0.50));
    config.plate_fusion.min_color_confidence = static_cast<float>(
        read_double(plate_fusion, "min_color_confidence", 0.30));
    config.plate_fusion.stale_after_frames = read_int(
        plate_fusion, "stale_after_frames", 60);
    config.plate_fusion.include_other_color =
        read_int(plate_fusion, "include_other_color", 0) != 0;

    const cv::FileNode text_renderer = storage["text_renderer"];
    config.text_renderer.backend = read_string(
        text_renderer, "backend", "windows_gdi");
    config.text_renderer.font_family = read_string(
        text_renderer, "font_family", "Microsoft YaHei");
    config.text_renderer.font_height = read_int(text_renderer, "font_height", 22);
    config.text_renderer.horizontal_padding = read_int(
        text_renderer, "horizontal_padding", 6);
    config.text_renderer.vertical_padding = read_int(
        text_renderer, "vertical_padding", 3);

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
    const std::string plate_roi_dir = read_string(runtime, "plate_roi_dir");
    if (!plate_roi_dir.empty()) {
        config.runtime.plate_roi_dir = resolve_path(config.project_root, plate_roi_dir);
    }
    config.runtime.max_saved_plate_rois = read_int(runtime, "max_saved_plate_rois", 64);
    const std::string rectified_plate_dir = read_string(runtime, "rectified_plate_dir");
    if (!rectified_plate_dir.empty()) {
        config.runtime.rectified_plate_dir = resolve_path(
            config.project_root, rectified_plate_dir);
    }
    config.runtime.max_saved_rectified_plates = read_int(
        runtime, "max_saved_rectified_plates", 64);
    const std::string ocr_results_jsonl = read_string(runtime, "ocr_results_jsonl");
    if (!ocr_results_jsonl.empty()) {
        config.runtime.ocr_results_jsonl = resolve_path(config.project_root, ocr_results_jsonl);
    }
    const std::string plate_fusion_results_jsonl = read_string(
        runtime, "plate_fusion_results_jsonl");
    if (!plate_fusion_results_jsonl.empty()) {
        config.runtime.plate_fusion_results_jsonl = resolve_path(
            config.project_root, plate_fusion_results_jsonl);
    }
    return config;
}

}  // namespace vehicle_system
