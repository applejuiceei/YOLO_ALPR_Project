#include "camera/camera_manager.hpp"
#include "classifier/pp_vehicle_onnx_color_classifier.hpp"
#include "common/config.hpp"
#include "common/types.hpp"
#include "common/utf8_text_renderer.hpp"
#include "cropper/vehicle_cropper.hpp"
#include "detector/yolo11_onnx_vehicle_detector.hpp"
#include "fusion/confidence_weighted_vehicle_fusion.hpp"
#include "fusion/confidence_weighted_plate_fusion.hpp"
#include "plate/hyperlpr3_onnx_plate_recognizer.hpp"
#include "plate/hsv_plate_color_classifier.hpp"
#include "plate/opencv_plate_quality_evaluator.hpp"
#include "plate/opencv_plate_rectifier.hpp"
#include "plate/plate_cropper.hpp"
#include "plate/yolo_obb_onnx_plate_detector.hpp"
#include "tracker/byte_tracker.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <map>
#include <numeric>
#include <optional>
#include <opencv2/highgui.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/videoio.hpp>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#include <psapi.h>
#endif

namespace {

using vehicle_system::Detection;
using vehicle_system::DetectorTiming;

struct CommandLine {
    std::filesystem::path config = "config/config.yaml";
    bool no_display = false;
    int max_frames_override = -1;
};

void print_help() {
    std::cout << "Usage: vehicle_demo [--config FILE] [--no-display] [--max-frames N]\n";
}

CommandLine parse_arguments(int argc, char** argv) {
    CommandLine command;
    for (int index = 1; index < argc; ++index) {
        const std::string argument = argv[index];
        if (argument == "--help" || argument == "-h") {
            print_help();
            std::exit(0);
        } else if (argument == "--config" && index + 1 < argc) {
            command.config = std::filesystem::u8path(argv[++index]);
        } else if (argument == "--no-display") {
            command.no_display = true;
        } else if (argument == "--max-frames" && index + 1 < argc) {
            command.max_frames_override = std::stoi(argv[++index]);
        } else {
            throw std::runtime_error("Unknown or incomplete argument: " + argument);
        }
    }
    return command;
}

cv::Scalar color_for_type(vehicle_system::ObjectType type) {
    switch (type) {
        case vehicle_system::ObjectType::Person: return {0, 255, 255};
        case vehicle_system::ObjectType::Car: return {0, 255, 0};
        case vehicle_system::ObjectType::Bus: return {255, 128, 0};
        case vehicle_system::ObjectType::Truck: return {0, 128, 255};
        case vehicle_system::ObjectType::NonMotor: return {255, 0, 255};
        default: return {200, 200, 200};
    }
}

void draw_tracks(
    cv::Mat& frame,
    const std::vector<vehicle_system::TrackedObject>& tracks,
    const std::vector<std::optional<vehicle_system::VehicleFusionResult>>& fused_colors,
    const std::vector<std::optional<vehicle_system::PlateFusionResult>>& fused_plates,
    vehicle_system::IUtf8TextRenderer& text_renderer) {
    const cv::Rect frame_bounds(0, 0, frame.cols, frame.rows);
    for (std::size_t index = 0; index < tracks.size(); ++index) {
        const vehicle_system::TrackedObject& track = tracks[index];
        const cv::Rect display_bbox = track.bbox & frame_bounds;
        if (display_bbox.empty()) {
            continue;
        }
        const cv::Scalar color = color_for_type(track.type);
        cv::rectangle(frame, display_bbox, color, 2, cv::LINE_AA);
        std::ostringstream label;
        label << "ID:" << track.track_id << ' '
              << vehicle_system::object_type_name(track.type) << ' '
              << std::fixed << std::setprecision(2) << track.confidence;
        if (index < fused_colors.size() && fused_colors[index].has_value()) {
            const vehicle_system::VehicleFusionResult& fused = *fused_colors[index];
            label << ' ' << fused.color.color << ' '
                  << std::fixed << std::setprecision(2) << fused.color.confidence
                  << " F:" << fused.sample_count << '/' << fused.vote_ratio;
            if (fused.stable) {
                label << '*';
            }
        }
        std::string plate_label;
        bool stable_plate = false;
        if (index < fused_plates.size() && fused_plates[index].has_value()) {
            const vehicle_system::PlateFusionResult& plate = *fused_plates[index];
            const vehicle_system::PlateOCRResult& display_ocr =
                plate.stable && !plate.fused_ocr.text.empty() ?
                    plate.fused_ocr : plate.latest_ocr;
            stable_plate = plate.stable && !plate.fused_ocr.text.empty();
            if (!display_ocr.text.empty()) {
                std::ostringstream plate_stream;
                plate_stream << (stable_plate ? "车牌: " : "车牌(单帧): ")
                             << display_ocr.text << ' '
                             << std::fixed << std::setprecision(2)
                             << display_ocr.confidence;
                if (!plate.color.color.empty() && plate.color.color != "other") {
                    plate_stream << ' ' << plate.color.color;
                }
                plate_label = plate_stream.str();
            }
        }

        const cv::Size vehicle_label_size = text_renderer.measure_label(label.str());
        const cv::Size plate_label_size = plate_label.empty() ? cv::Size() :
            text_renderer.measure_label(plate_label);
        const int label_width = std::max(vehicle_label_size.width, plate_label_size.width);
        const int label_height = vehicle_label_size.height + plate_label_size.height;
        const int text_left = std::clamp(display_bbox.x, 0,
            std::max(0, frame.cols - label_width));
        const int preferred_top = display_bbox.y - label_height - 2;
        const int text_top = preferred_top >= 0 ? preferred_top :
            std::clamp(display_bbox.y + 2, 0, std::max(0, frame.rows - label_height));
        text_renderer.draw_label(frame, label.str(), cv::Point(text_left, text_top),
            cv::Scalar(20, 20, 20), color);
        if (!plate_label.empty()) {
            const cv::Scalar plate_background = stable_plate ?
                cv::Scalar(0, 230, 255) : cv::Scalar(110, 75, 30);
            const cv::Scalar plate_foreground = stable_plate ?
                cv::Scalar(20, 20, 20) : cv::Scalar(245, 245, 245);
            text_renderer.draw_label(frame, plate_label,
                cv::Point(text_left, text_top + vehicle_label_size.height),
                plate_foreground, plate_background);
        }
    }
}

struct GlobalPlateAnnotation {
    int track_id = -1;
    std::array<cv::Point2f, 4> corners{};
    float confidence = 0.0F;
    float quality_score = 0.0F;
    bool quality_evaluated = false;
    bool quality_acceptable = false;
    std::string color;
    float color_confidence = 0.0F;
};

std::string json_escape(const std::string& value) {
    std::string escaped;
    escaped.reserve(value.size());
    for (const unsigned char byte : value) {
        switch (byte) {
            case '"': escaped += "\\\""; break;
            case '\\': escaped += "\\\\"; break;
            case '\b': escaped += "\\b"; break;
            case '\f': escaped += "\\f"; break;
            case '\n': escaped += "\\n"; break;
            case '\r': escaped += "\\r"; break;
            case '\t': escaped += "\\t"; break;
            default:
                if (byte >= 0x20U) {
                    escaped.push_back(static_cast<char>(byte));
                }
                break;
        }
    }
    return escaped;
}

void draw_plates(cv::Mat& frame, const std::vector<GlobalPlateAnnotation>& plates) {
    for (const GlobalPlateAnnotation& plate : plates) {
        const cv::Scalar color = !plate.quality_evaluated ? cv::Scalar(180, 180, 180) :
            (plate.quality_acceptable ? cv::Scalar(255, 255, 0) : cv::Scalar(0, 0, 255));
        for (std::size_t corner = 0; corner < plate.corners.size(); ++corner) {
            cv::line(frame, plate.corners[corner],
                plate.corners[(corner + 1) % plate.corners.size()],
                color, 2, cv::LINE_AA);
        }
        const auto top_corner = std::min_element(
            plate.corners.begin(), plate.corners.end(), [](const cv::Point2f& left, const cv::Point2f& right) {
                return left.y < right.y;
            });
        std::ostringstream label;
        label << "plate ID:" << plate.track_id << ' '
              << std::fixed << std::setprecision(2) << plate.confidence;
        if (plate.quality_evaluated) {
            label << " Q:" << std::fixed << std::setprecision(2) << plate.quality_score
                  << (plate.quality_acceptable ? '+' : '-');
        }
        if (!plate.color.empty()) {
            label << ' ' << plate.color << ':' << std::fixed << std::setprecision(2)
                  << plate.color_confidence;
        }
        const cv::Point origin(
            std::clamp(static_cast<int>(std::round(top_corner->x)), 0, std::max(0, frame.cols - 1)),
            std::clamp(static_cast<int>(std::round(top_corner->y)) - 4, 14, std::max(14, frame.rows - 1)));
        cv::putText(frame, label.str(), origin, cv::FONT_HERSHEY_SIMPLEX,
            0.45, color, 1, cv::LINE_AA);
    }
}

bool is_vehicle(vehicle_system::ObjectType type) {
    return type == vehicle_system::ObjectType::Car ||
        type == vehicle_system::ObjectType::Bus ||
        type == vehicle_system::ObjectType::Truck ||
        type == vehicle_system::ObjectType::NonMotor;
}

const char* rectification_method_name(vehicle_system::PlateRectificationMethod method) {
    switch (method) {
        case vehicle_system::PlateRectificationMethod::Resize: return "resize";
        case vehicle_system::PlateRectificationMethod::Perspective: return "perspective";
        case vehicle_system::PlateRectificationMethod::ResizeFallback: return "resize_fallback";
        default: return "unknown";
    }
}

double percentile(std::vector<double> values, double quantile) {
    if (values.empty()) {
        return 0.0;
    }
    std::sort(values.begin(), values.end());
    const double position = quantile * static_cast<double>(values.size() - 1);
    const std::size_t lower = static_cast<std::size_t>(std::floor(position));
    const std::size_t upper = static_cast<std::size_t>(std::ceil(position));
    const double fraction = position - static_cast<double>(lower);
    return values[lower] * (1.0 - fraction) + values[upper] * fraction;
}

std::uint64_t working_set_bytes() {
#ifdef _WIN32
    PROCESS_MEMORY_COUNTERS_EX counters{};
    if (GetProcessMemoryInfo(GetCurrentProcess(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&counters), sizeof(counters))) {
        return static_cast<std::uint64_t>(counters.WorkingSetSize);
    }
#endif
    return 0;
}

void ensure_parent(const std::filesystem::path& path) {
    if (!path.parent_path().empty()) {
        std::filesystem::create_directories(path.parent_path());
    }
}

void write_summary(
    const vehicle_system::AppConfig& config,
    std::uint64_t processed_frames,
    std::uint64_t total_detections,
    std::uint64_t total_high_confidence_detections,
    std::uint64_t tracked_observations,
    std::uint64_t tracked_low_confidence_observations,
    std::size_t unique_track_ids,
    const std::map<int, std::uint64_t>& track_observation_counts,
    std::uint64_t dropped_frames,
    std::uint64_t vehicle_crop_attempts,
    std::uint64_t vehicle_crops,
    std::uint64_t invalid_vehicle_crops,
    std::uint64_t saved_vehicle_rois,
    std::uint64_t vehicle_color_calls,
    std::uint64_t vehicle_color_other,
    std::uint64_t vehicle_fusion_updates,
    std::uint64_t vehicle_fusion_results,
    std::uint64_t vehicle_fusion_stable_observations,
    std::size_t vehicle_fusion_stable_track_ids,
    std::uint64_t plate_detector_calls,
    std::uint64_t plate_detections,
    const std::map<int, std::uint64_t>& plate_detection_counts_by_track,
    std::uint64_t plate_crop_attempts,
    std::uint64_t plate_crops,
    std::uint64_t invalid_plate_crops,
    std::uint64_t saved_plate_rois,
    std::uint64_t plate_quality_evaluations,
    std::uint64_t plate_quality_accepted,
    std::uint64_t plate_quality_rejected,
    const std::map<int, std::uint64_t>& plate_quality_accepted_by_track,
    const std::map<std::string, std::uint64_t>& plate_quality_rejection_counts,
    std::uint64_t plate_rectifier_calls,
    std::uint64_t plate_rectifier_successes,
    std::uint64_t plate_rectifier_failures,
    std::uint64_t plate_rectifier_perspective,
    std::uint64_t plate_rectifier_resize,
    std::uint64_t plate_rectifier_resize_fallback,
    std::uint64_t saved_rectified_plates,
    std::uint64_t plate_color_calls,
    std::uint64_t plate_color_other,
    const std::map<std::string, std::uint64_t>& plate_color_counts,
    const std::map<int, std::map<std::string, std::uint64_t>>& plate_color_counts_by_track,
    std::uint64_t plate_ocr_calls,
    std::uint64_t plate_ocr_nonempty,
    std::uint64_t plate_ocr_accepted,
    std::uint64_t plate_ocr_rejected,
    const std::map<std::string, std::uint64_t>& plate_ocr_rejection_counts,
    const std::map<std::string, std::uint64_t>& plate_ocr_text_counts,
    const std::map<std::string, std::uint64_t>& plate_ocr_accepted_text_counts,
    const std::map<int, std::map<std::string, std::uint64_t>>& plate_ocr_accepted_text_counts_by_track,
    std::uint64_t plate_fusion_updates,
    std::uint64_t plate_fusion_results,
    std::uint64_t plate_fusion_stable_observations,
    std::size_t plate_fusion_stable_track_ids,
    const std::map<int, std::string>& plate_fusion_latest_text_by_track,
    const std::map<int, std::string>& plate_fusion_fused_text_by_track,
    double wall_seconds,
    double cpu_seconds,
    const std::vector<double>& inference_ms,
    const std::vector<double>& total_ms,
    const std::vector<double>& cropper_ms,
    const std::vector<double>& tracker_ms,
    const std::vector<double>& color_inference_ms,
    const std::vector<double>& color_total_ms,
    const std::vector<double>& vehicle_fusion_update_ms,
    const std::vector<double>& plate_inference_ms,
    const std::vector<double>& plate_total_ms,
    const std::vector<double>& plate_cropper_ms,
    const std::vector<double>& plate_quality_evaluator_ms,
    const std::vector<double>& plate_quality_scores,
    const std::vector<double>& plate_rectifier_ms,
    const std::vector<double>& plate_color_ms,
    const std::vector<double>& plate_ocr_preprocess_ms,
    const std::vector<double>& plate_ocr_inference_ms,
    const std::vector<double>& plate_ocr_decode_ms,
    const std::vector<double>& plate_ocr_total_ms,
    const std::vector<double>& plate_fusion_update_ms) {
    ensure_parent(config.runtime.summary_json);
    std::ofstream output(config.runtime.summary_json);
    if (!output) {
        throw std::runtime_error("Cannot write summary: " + config.runtime.summary_json.u8string());
    }
    const double mean_inference = inference_ms.empty() ? 0.0 :
        std::accumulate(inference_ms.begin(), inference_ms.end(), 0.0) / static_cast<double>(inference_ms.size());
    const double mean_total = total_ms.empty() ? 0.0 :
        std::accumulate(total_ms.begin(), total_ms.end(), 0.0) / static_cast<double>(total_ms.size());
    const double mean_cropper = cropper_ms.empty() ? 0.0 :
        std::accumulate(cropper_ms.begin(), cropper_ms.end(), 0.0) / static_cast<double>(cropper_ms.size());
    const double mean_color_inference = color_inference_ms.empty() ? 0.0 :
        std::accumulate(color_inference_ms.begin(), color_inference_ms.end(), 0.0) /
            static_cast<double>(color_inference_ms.size());
    const double mean_color_total = color_total_ms.empty() ? 0.0 :
        std::accumulate(color_total_ms.begin(), color_total_ms.end(), 0.0) /
            static_cast<double>(color_total_ms.size());
    const double mean_tracker = tracker_ms.empty() ? 0.0 :
        std::accumulate(tracker_ms.begin(), tracker_ms.end(), 0.0) / static_cast<double>(tracker_ms.size());
    const double mean_vehicle_fusion_update = vehicle_fusion_update_ms.empty() ? 0.0 :
        std::accumulate(vehicle_fusion_update_ms.begin(), vehicle_fusion_update_ms.end(), 0.0) /
            static_cast<double>(vehicle_fusion_update_ms.size());
    const double mean_plate_inference = plate_inference_ms.empty() ? 0.0 :
        std::accumulate(plate_inference_ms.begin(), plate_inference_ms.end(), 0.0) /
            static_cast<double>(plate_inference_ms.size());
    const double mean_plate_total = plate_total_ms.empty() ? 0.0 :
        std::accumulate(plate_total_ms.begin(), plate_total_ms.end(), 0.0) /
            static_cast<double>(plate_total_ms.size());
    const double mean_plate_cropper = plate_cropper_ms.empty() ? 0.0 :
        std::accumulate(plate_cropper_ms.begin(), plate_cropper_ms.end(), 0.0) /
            static_cast<double>(plate_cropper_ms.size());
    const double mean_plate_quality_evaluator = plate_quality_evaluator_ms.empty() ? 0.0 :
        std::accumulate(plate_quality_evaluator_ms.begin(), plate_quality_evaluator_ms.end(), 0.0) /
            static_cast<double>(plate_quality_evaluator_ms.size());
    const double mean_plate_quality_score = plate_quality_scores.empty() ? 0.0 :
        std::accumulate(plate_quality_scores.begin(), plate_quality_scores.end(), 0.0) /
            static_cast<double>(plate_quality_scores.size());
    const double mean_plate_rectifier = plate_rectifier_ms.empty() ? 0.0 :
        std::accumulate(plate_rectifier_ms.begin(), plate_rectifier_ms.end(), 0.0) /
            static_cast<double>(plate_rectifier_ms.size());
    const double mean_plate_color = plate_color_ms.empty() ? 0.0 :
        std::accumulate(plate_color_ms.begin(), plate_color_ms.end(), 0.0) /
            static_cast<double>(plate_color_ms.size());
    const double mean_plate_ocr_preprocess = plate_ocr_preprocess_ms.empty() ? 0.0 :
        std::accumulate(plate_ocr_preprocess_ms.begin(), plate_ocr_preprocess_ms.end(), 0.0) /
            static_cast<double>(plate_ocr_preprocess_ms.size());
    const double mean_plate_ocr_inference = plate_ocr_inference_ms.empty() ? 0.0 :
        std::accumulate(plate_ocr_inference_ms.begin(), plate_ocr_inference_ms.end(), 0.0) /
            static_cast<double>(plate_ocr_inference_ms.size());
    const double mean_plate_ocr_decode = plate_ocr_decode_ms.empty() ? 0.0 :
        std::accumulate(plate_ocr_decode_ms.begin(), plate_ocr_decode_ms.end(), 0.0) /
            static_cast<double>(plate_ocr_decode_ms.size());
    const double mean_plate_ocr_total = plate_ocr_total_ms.empty() ? 0.0 :
        std::accumulate(plate_ocr_total_ms.begin(), plate_ocr_total_ms.end(), 0.0) /
            static_cast<double>(plate_ocr_total_ms.size());
    const double mean_plate_fusion_update = plate_fusion_update_ms.empty() ? 0.0 :
        std::accumulate(plate_fusion_update_ms.begin(), plate_fusion_update_ms.end(), 0.0) /
            static_cast<double>(plate_fusion_update_ms.size());
    const double process_fps = wall_seconds > 0.0 ? static_cast<double>(processed_frames) / wall_seconds : 0.0;
    const double cpu_core_equivalent = wall_seconds > 0.0 ? cpu_seconds / wall_seconds * 100.0 : 0.0;
    std::ostringstream track_counts_json;
    track_counts_json << '{';
    bool first_track = true;
    for (const auto& [track_id, count] : track_observation_counts) {
        if (!first_track) {
            track_counts_json << ',';
        }
        first_track = false;
        track_counts_json << '"' << track_id << "\":" << count;
    }
    track_counts_json << '}';
    std::ostringstream plate_counts_json;
    plate_counts_json << '{';
    bool first_plate_track = true;
    for (const auto& [track_id, count] : plate_detection_counts_by_track) {
        if (!first_plate_track) {
            plate_counts_json << ',';
        }
        first_plate_track = false;
        plate_counts_json << '"' << track_id << "\":" << count;
    }
    plate_counts_json << '}';
    std::ostringstream quality_accepted_counts_json;
    quality_accepted_counts_json << '{';
    bool first_quality_track = true;
    for (const auto& [track_id, count] : plate_quality_accepted_by_track) {
        if (!first_quality_track) {
            quality_accepted_counts_json << ',';
        }
        first_quality_track = false;
        quality_accepted_counts_json << '"' << track_id << "\":" << count;
    }
    quality_accepted_counts_json << '}';
    std::ostringstream quality_rejection_counts_json;
    quality_rejection_counts_json << '{';
    bool first_rejection_reason = true;
    for (const auto& [reason, count] : plate_quality_rejection_counts) {
        if (!first_rejection_reason) {
            quality_rejection_counts_json << ',';
        }
        first_rejection_reason = false;
        quality_rejection_counts_json << '"' << reason << "\":" << count;
    }
    quality_rejection_counts_json << '}';
    std::ostringstream plate_color_counts_json;
    plate_color_counts_json << '{';
    bool first_plate_color = true;
    for (const auto& [color, count] : plate_color_counts) {
        if (!first_plate_color) {
            plate_color_counts_json << ',';
        }
        first_plate_color = false;
        plate_color_counts_json << '"' << color << "\":" << count;
    }
    plate_color_counts_json << '}';
    std::ostringstream plate_color_tracks_json;
    plate_color_tracks_json << '{';
    bool first_color_track = true;
    for (const auto& [track_id, colors] : plate_color_counts_by_track) {
        if (!first_color_track) {
            plate_color_tracks_json << ',';
        }
        first_color_track = false;
        plate_color_tracks_json << '"' << track_id << "\":{";
        bool first_track_color = true;
        for (const auto& [color, count] : colors) {
            if (!first_track_color) {
                plate_color_tracks_json << ',';
            }
            first_track_color = false;
            plate_color_tracks_json << '"' << color << "\":" << count;
        }
        plate_color_tracks_json << '}';
    }
    plate_color_tracks_json << '}';
    std::ostringstream plate_ocr_rejection_counts_json;
    plate_ocr_rejection_counts_json << '{';
    bool first_ocr_rejection = true;
    for (const auto& [reason, count] : plate_ocr_rejection_counts) {
        if (!first_ocr_rejection) {
            plate_ocr_rejection_counts_json << ',';
        }
        first_ocr_rejection = false;
        plate_ocr_rejection_counts_json << '"' << json_escape(reason) << "\":" << count;
    }
    plate_ocr_rejection_counts_json << '}';
    const auto text_counts_json = [](const std::map<std::string, std::uint64_t>& counts) {
        std::ostringstream stream;
        stream << '{';
        bool first = true;
        for (const auto& [value, count] : counts) {
            if (!first) {
                stream << ',';
            }
            first = false;
            stream << '"' << json_escape(value) << "\":" << count;
        }
        stream << '}';
        return stream.str();
    };
    std::ostringstream plate_ocr_tracks_json;
    plate_ocr_tracks_json << '{';
    bool first_ocr_track = true;
    for (const auto& [track_id, texts] : plate_ocr_accepted_text_counts_by_track) {
        if (!first_ocr_track) {
            plate_ocr_tracks_json << ',';
        }
        first_ocr_track = false;
        plate_ocr_tracks_json << '"' << track_id << "\":" << text_counts_json(texts);
    }
    plate_ocr_tracks_json << '}';
    const auto track_text_json = [](const std::map<int, std::string>& values) {
        std::ostringstream stream;
        stream << '{';
        bool first = true;
        for (const auto& [track_id, value] : values) {
            if (!first) {
                stream << ',';
            }
            first = false;
            stream << '"' << track_id << "\":\"" << json_escape(value) << '"';
        }
        stream << '}';
        return stream.str();
    };
    output << std::fixed << std::setprecision(3)
        << "{\n"
        << "  \"platform\": \"windows-pc-simulation\",\n"
        << "  \"inference_backend\": \"onnxruntime-cpu\",\n"
        << "  \"npu_used\": false,\n"
        << "  \"processed_frames\": " << processed_frames << ",\n"
        << "  \"total_detections\": " << total_detections << ",\n"
        << "  \"total_high_confidence_detections\": " << total_high_confidence_detections << ",\n"
        << "  \"tracker_backend\": \"bytetrack-cpu\",\n"
        << "  \"tracked_observations\": " << tracked_observations << ",\n"
        << "  \"tracked_low_confidence_observations\": " << tracked_low_confidence_observations << ",\n"
        << "  \"unique_track_ids\": " << unique_track_ids << ",\n"
        << "  \"track_observation_counts\": " << track_counts_json.str() << ",\n"
        << "  \"queue_dropped_frames\": " << dropped_frames << ",\n"
        << "  \"vehicle_crop_attempts\": " << vehicle_crop_attempts << ",\n"
        << "  \"vehicle_crops\": " << vehicle_crops << ",\n"
        << "  \"invalid_vehicle_crops\": " << invalid_vehicle_crops << ",\n"
        << "  \"saved_vehicle_rois\": " << saved_vehicle_rois << ",\n"
        << "  \"vehicle_color_backend\": \"onnxruntime-cpu\",\n"
        << "  \"vehicle_color_calls\": " << vehicle_color_calls << ",\n"
        << "  \"vehicle_color_other\": " << vehicle_color_other << ",\n"
        << "  \"vehicle_fusion_backend\": \"confidence-weighted-cpu\",\n"
        << "  \"vehicle_fusion_updates\": " << vehicle_fusion_updates << ",\n"
        << "  \"vehicle_fusion_results\": " << vehicle_fusion_results << ",\n"
        << "  \"vehicle_fusion_stable_observations\": " << vehicle_fusion_stable_observations << ",\n"
        << "  \"vehicle_fusion_stable_track_ids\": " << vehicle_fusion_stable_track_ids << ",\n"
        << "  \"plate_detector_backend\": \"onnxruntime-cpu\",\n"
        << "  \"plate_detector_calls\": " << plate_detector_calls << ",\n"
        << "  \"plate_detections\": " << plate_detections << ",\n"
        << "  \"plate_detection_counts_by_track\": " << plate_counts_json.str() << ",\n"
        << "  \"plate_crop_attempts\": " << plate_crop_attempts << ",\n"
        << "  \"plate_crops\": " << plate_crops << ",\n"
        << "  \"invalid_plate_crops\": " << invalid_plate_crops << ",\n"
        << "  \"saved_plate_rois\": " << saved_plate_rois << ",\n"
        << "  \"plate_quality_backend\": \"opencv-cpu\",\n"
        << "  \"plate_quality_evaluations\": " << plate_quality_evaluations << ",\n"
        << "  \"plate_quality_accepted\": " << plate_quality_accepted << ",\n"
        << "  \"plate_quality_rejected\": " << plate_quality_rejected << ",\n"
        << "  \"plate_quality_accepted_by_track\": "
        << quality_accepted_counts_json.str() << ",\n"
        << "  \"plate_quality_rejection_counts\": "
        << quality_rejection_counts_json.str() << ",\n"
        << "  \"plate_rectifier_backend\": \"opencv-cpu\",\n"
        << "  \"plate_rectifier_calls\": " << plate_rectifier_calls << ",\n"
        << "  \"plate_rectifier_successes\": " << plate_rectifier_successes << ",\n"
        << "  \"plate_rectifier_failures\": " << plate_rectifier_failures << ",\n"
        << "  \"plate_rectifier_perspective\": " << plate_rectifier_perspective << ",\n"
        << "  \"plate_rectifier_resize\": " << plate_rectifier_resize << ",\n"
        << "  \"plate_rectifier_resize_fallback\": "
        << plate_rectifier_resize_fallback << ",\n"
        << "  \"saved_rectified_plates\": " << saved_rectified_plates << ",\n"
        << "  \"plate_color_backend\": \"opencv-hsv-cpu\",\n"
        << "  \"plate_color_calls\": " << plate_color_calls << ",\n"
        << "  \"plate_color_other\": " << plate_color_other << ",\n"
        << "  \"plate_color_counts\": " << plate_color_counts_json.str() << ",\n"
        << "  \"plate_color_counts_by_track\": " << plate_color_tracks_json.str() << ",\n"
        << "  \"plate_recognizer_backend\": \"hyperlpr3-onnxruntime-cpu\",\n"
        << "  \"plate_ocr_calls\": " << plate_ocr_calls << ",\n"
        << "  \"plate_ocr_nonempty\": " << plate_ocr_nonempty << ",\n"
        << "  \"plate_ocr_accepted\": " << plate_ocr_accepted << ",\n"
        << "  \"plate_ocr_rejected\": " << plate_ocr_rejected << ",\n"
        << "  \"plate_ocr_rejection_counts\": " << plate_ocr_rejection_counts_json.str() << ",\n"
        << "  \"plate_ocr_text_counts\": " << text_counts_json(plate_ocr_text_counts) << ",\n"
        << "  \"plate_ocr_accepted_text_counts\": "
        << text_counts_json(plate_ocr_accepted_text_counts) << ",\n"
        << "  \"plate_ocr_accepted_text_counts_by_track\": "
        << plate_ocr_tracks_json.str() << ",\n"
        << "  \"plate_fusion_backend\": \"confidence-weighted-cpu\",\n"
        << "  \"plate_fusion_updates\": " << plate_fusion_updates << ",\n"
        << "  \"plate_fusion_results\": " << plate_fusion_results << ",\n"
        << "  \"plate_fusion_stable_observations\": "
        << plate_fusion_stable_observations << ",\n"
        << "  \"plate_fusion_stable_track_ids\": "
        << plate_fusion_stable_track_ids << ",\n"
        << "  \"plate_fusion_latest_text_by_track\": "
        << track_text_json(plate_fusion_latest_text_by_track) << ",\n"
        << "  \"plate_fusion_fused_text_by_track\": "
        << track_text_json(plate_fusion_fused_text_by_track) << ",\n"
        << "  \"wall_seconds\": " << wall_seconds << ",\n"
        << "  \"processing_fps\": " << process_fps << ",\n"
        << "  \"cpu_core_equivalent_percent\": " << cpu_core_equivalent << ",\n"
        << "  \"working_set_mib\": " << (static_cast<double>(working_set_bytes()) / 1048576.0) << ",\n"
        << "  \"inference_ms_mean\": " << mean_inference << ",\n"
        << "  \"inference_ms_p50\": " << percentile(inference_ms, 0.50) << ",\n"
        << "  \"inference_ms_p95\": " << percentile(inference_ms, 0.95) << ",\n"
        << "  \"detector_total_ms_mean\": " << mean_total << ",\n"
        << "  \"detector_total_ms_p95\": " << percentile(total_ms, 0.95) << ",\n"
        << "  \"cropper_ms_mean_per_frame\": " << mean_cropper << ",\n"
        << "  \"cropper_ms_p95_per_frame\": " << percentile(cropper_ms, 0.95) << ",\n"
        << "  \"tracker_ms_mean_per_frame\": " << mean_tracker << ",\n"
        << "  \"tracker_ms_p95_per_frame\": " << percentile(tracker_ms, 0.95) << ",\n"
        << "  \"vehicle_color_inference_ms_mean_per_call\": " << mean_color_inference << ",\n"
        << "  \"vehicle_color_inference_ms_p50_per_call\": " << percentile(color_inference_ms, 0.50) << ",\n"
        << "  \"vehicle_color_inference_ms_p95_per_call\": " << percentile(color_inference_ms, 0.95) << ",\n"
        << "  \"vehicle_color_total_ms_mean_per_call\": " << mean_color_total << ",\n"
        << "  \"vehicle_color_total_ms_p95_per_call\": " << percentile(color_total_ms, 0.95) << ",\n"
        << "  \"vehicle_fusion_update_ms_mean_per_call\": " << mean_vehicle_fusion_update << ",\n"
        << "  \"vehicle_fusion_update_ms_p95_per_call\": "
        << percentile(vehicle_fusion_update_ms, 0.95) << ",\n"
        << "  \"plate_inference_ms_mean_per_call\": " << mean_plate_inference << ",\n"
        << "  \"plate_inference_ms_p50_per_call\": " << percentile(plate_inference_ms, 0.50) << ",\n"
        << "  \"plate_inference_ms_p95_per_call\": " << percentile(plate_inference_ms, 0.95) << ",\n"
        << "  \"plate_total_ms_mean_per_call\": " << mean_plate_total << ",\n"
        << "  \"plate_total_ms_p95_per_call\": " << percentile(plate_total_ms, 0.95) << ",\n"
        << "  \"plate_cropper_ms_mean_per_detection\": " << mean_plate_cropper << ",\n"
        << "  \"plate_cropper_ms_p95_per_detection\": " << percentile(plate_cropper_ms, 0.95) << ",\n"
        << "  \"plate_quality_score_mean\": " << mean_plate_quality_score << ",\n"
        << "  \"plate_quality_score_p50\": " << percentile(plate_quality_scores, 0.50) << ",\n"
        << "  \"plate_quality_score_p95\": " << percentile(plate_quality_scores, 0.95) << ",\n"
        << "  \"plate_quality_evaluator_ms_mean_per_crop\": "
        << mean_plate_quality_evaluator << ",\n"
        << "  \"plate_quality_evaluator_ms_p95_per_crop\": "
        << percentile(plate_quality_evaluator_ms, 0.95) << ",\n"
        << "  \"plate_rectifier_ms_mean_per_call\": " << mean_plate_rectifier << ",\n"
        << "  \"plate_rectifier_ms_p50_per_call\": "
        << percentile(plate_rectifier_ms, 0.50) << ",\n"
        << "  \"plate_rectifier_ms_p95_per_call\": "
        << percentile(plate_rectifier_ms, 0.95) << ",\n"
        << "  \"plate_color_ms_mean_per_call\": " << mean_plate_color << ",\n"
        << "  \"plate_color_ms_p50_per_call\": " << percentile(plate_color_ms, 0.50) << ",\n"
        << "  \"plate_color_ms_p95_per_call\": " << percentile(plate_color_ms, 0.95) << ",\n"
        << "  \"plate_ocr_preprocess_ms_mean_per_call\": " << mean_plate_ocr_preprocess << ",\n"
        << "  \"plate_ocr_inference_ms_mean_per_call\": " << mean_plate_ocr_inference << ",\n"
        << "  \"plate_ocr_inference_ms_p50_per_call\": "
        << percentile(plate_ocr_inference_ms, 0.50) << ",\n"
        << "  \"plate_ocr_inference_ms_p95_per_call\": "
        << percentile(plate_ocr_inference_ms, 0.95) << ",\n"
        << "  \"plate_ocr_decode_ms_mean_per_call\": " << mean_plate_ocr_decode << ",\n"
        << "  \"plate_ocr_total_ms_mean_per_call\": " << mean_plate_ocr_total << ",\n"
        << "  \"plate_ocr_total_ms_p95_per_call\": "
        << percentile(plate_ocr_total_ms, 0.95) << ",\n"
        << "  \"plate_fusion_update_ms_mean_per_call\": "
        << mean_plate_fusion_update << ",\n"
        << "  \"plate_fusion_update_ms_p95_per_call\": "
        << percentile(plate_fusion_update_ms, 0.95) << "\n"
        << "}\n";
}

}  // namespace

int main(int argc, char** argv) {
    try {
        vehicle_system::configure_utf8_console();
        const CommandLine command = parse_arguments(argc, argv);
        vehicle_system::AppConfig config = vehicle_system::load_config(command.config);
        if (command.no_display) {
            config.runtime.display = false;
        }
        if (command.max_frames_override >= 0) {
            config.runtime.max_frames = command.max_frames_override;
        }
        if (config.detector.backend != "onnxruntime") {
            throw std::runtime_error("PC stage supports only vehicle_detector.backend=onnxruntime");
        }
        if (config.vehicle_color.backend != "onnxruntime") {
            throw std::runtime_error("PC stage supports only vehicle_color.backend=onnxruntime");
        }
        if (config.tracker.backend != "bytetrack") {
            throw std::runtime_error("PC stage supports only vehicle_tracker.backend=bytetrack");
        }
        if (config.vehicle_fusion.backend != "confidence_weighted") {
            throw std::runtime_error(
                "PC stage supports only vehicle_fusion.backend=confidence_weighted");
        }
        if (config.plate_detector.backend != "onnxruntime") {
            throw std::runtime_error("PC stage supports only plate_detector.backend=onnxruntime");
        }
        if (config.plate_quality.backend != "opencv") {
            throw std::runtime_error("PC stage supports only plate_quality.backend=opencv");
        }
        if (config.plate_rectifier.backend != "opencv") {
            throw std::runtime_error("PC stage supports only plate_rectifier.backend=opencv");
        }
        if (config.plate_color.backend != "hsv") {
            throw std::runtime_error("PC stage supports only plate_color.backend=hsv");
        }
        if (config.plate_recognizer.backend != "onnxruntime") {
            throw std::runtime_error(
                "PC stage supports only plate_recognizer.backend=onnxruntime");
        }
        if (config.plate_fusion.backend != "confidence_weighted") {
            throw std::runtime_error(
                "PC stage supports only plate_fusion.backend=confidence_weighted");
        }
        if (config.text_renderer.backend != "windows_gdi") {
            throw std::runtime_error(
                "PC stage supports only text_renderer.backend=windows_gdi");
        }

        std::cout << "Model: " << config.detector.model_path.u8string() << '\n';
        std::cout << "Vehicle color model: " << config.vehicle_color.model_path.u8string() << '\n';
        std::cout << "Plate detector model: " << config.plate_detector.model_path.u8string() << '\n';
        std::cout << "Plate recognizer model: "
                  << config.plate_recognizer.model_path.u8string() << '\n';
        std::cout << "Camera source: " << config.camera.source << '\n';
        std::cout << "Backend: ONNX Runtime CPU (NPU not used on PC)\n";

        auto detector = std::make_unique<vehicle_system::Yolo11OnnxVehicleDetector>(config.detector);
        auto color_classifier = std::make_unique<vehicle_system::PpVehicleOnnxColorClassifier>(config.vehicle_color);
        auto plate_detector = std::make_unique<vehicle_system::YoloObbOnnxPlateDetector>(
            config.plate_detector);
        vehicle_system::ByteTracker tracker(config.tracker);
        vehicle_system::ConfidenceWeightedVehicleFusion vehicle_fusion(config.vehicle_fusion);
        vehicle_system::VehicleCropper cropper(config.cropper);
        vehicle_system::PlateCropper plate_cropper(config.plate_cropper);
        vehicle_system::OpenCvPlateQualityEvaluator plate_quality_evaluator(config.plate_quality);
        vehicle_system::OpenCvPlateRectifier plate_rectifier(config.plate_rectifier);
        vehicle_system::HsvPlateColorClassifier plate_color_classifier(config.plate_color);
        vehicle_system::HyperLpr3OnnxPlateRecognizer plate_recognizer(
            config.plate_recognizer);
        vehicle_system::ConfidenceWeightedPlateFusion plate_fusion(config.plate_fusion);
        vehicle_system::WindowsGdiUtf8TextRenderer text_renderer(config.text_renderer);
        std::ofstream ocr_results;
        if (!config.runtime.ocr_results_jsonl.empty()) {
            ensure_parent(config.runtime.ocr_results_jsonl);
            ocr_results.open(config.runtime.ocr_results_jsonl, std::ios::trunc);
            if (!ocr_results) {
                throw std::runtime_error(
                    "Cannot write OCR results: " +
                    config.runtime.ocr_results_jsonl.u8string());
            }
        }
        std::ofstream plate_fusion_results;
        if (!config.runtime.plate_fusion_results_jsonl.empty()) {
            ensure_parent(config.runtime.plate_fusion_results_jsonl);
            plate_fusion_results.open(
                config.runtime.plate_fusion_results_jsonl, std::ios::trunc);
            if (!plate_fusion_results) {
                throw std::runtime_error(
                    "Cannot write PlateFusion results: " +
                    config.runtime.plate_fusion_results_jsonl.u8string());
            }
        }
        vehicle_system::CameraManager camera(config.camera);
        camera.start();

        cv::VideoWriter writer;
        std::vector<double> inference_ms;
        std::vector<double> detector_total_ms;
        std::vector<double> cropper_ms;
        std::vector<double> tracker_ms;
        std::vector<double> color_inference_ms;
        std::vector<double> color_total_ms;
        std::vector<double> vehicle_fusion_update_ms;
        std::vector<double> plate_inference_ms;
        std::vector<double> plate_total_ms;
        std::vector<double> plate_cropper_ms;
        std::vector<double> plate_quality_evaluator_ms;
        std::vector<double> plate_quality_scores;
        std::vector<double> plate_rectifier_ms;
        std::vector<double> plate_color_ms;
        std::vector<double> plate_ocr_preprocess_ms;
        std::vector<double> plate_ocr_inference_ms;
        std::vector<double> plate_ocr_decode_ms;
        std::vector<double> plate_ocr_total_ms;
        std::vector<double> plate_fusion_update_ms;
        std::uint64_t processed_frames = 0;
        std::uint64_t total_detections = 0;
        std::uint64_t total_high_confidence_detections = 0;
        std::uint64_t tracked_observations = 0;
        std::uint64_t tracked_low_confidence_observations = 0;
        std::unordered_set<int> unique_track_ids;
        std::map<int, std::uint64_t> track_observation_counts;
        std::uint64_t vehicle_crop_attempts = 0;
        std::uint64_t vehicle_crops = 0;
        std::uint64_t invalid_vehicle_crops = 0;
        std::uint64_t saved_vehicle_rois = 0;
        std::uint64_t vehicle_color_calls = 0;
        std::uint64_t vehicle_color_other = 0;
        std::uint64_t vehicle_fusion_updates = 0;
        std::uint64_t vehicle_fusion_results = 0;
        std::uint64_t vehicle_fusion_stable_observations = 0;
        std::unordered_set<int> vehicle_fusion_stable_track_ids;
        std::uint64_t plate_detector_calls = 0;
        std::uint64_t plate_detections = 0;
        std::map<int, std::uint64_t> plate_detection_counts_by_track;
        std::uint64_t plate_crop_attempts = 0;
        std::uint64_t plate_crops = 0;
        std::uint64_t invalid_plate_crops = 0;
        std::uint64_t saved_plate_rois = 0;
        std::uint64_t plate_quality_evaluations = 0;
        std::uint64_t plate_quality_accepted = 0;
        std::uint64_t plate_quality_rejected = 0;
        std::map<int, std::uint64_t> plate_quality_accepted_by_track;
        std::map<std::string, std::uint64_t> plate_quality_rejection_counts;
        std::uint64_t plate_rectifier_calls = 0;
        std::uint64_t plate_rectifier_successes = 0;
        std::uint64_t plate_rectifier_failures = 0;
        std::uint64_t plate_rectifier_perspective = 0;
        std::uint64_t plate_rectifier_resize = 0;
        std::uint64_t plate_rectifier_resize_fallback = 0;
        std::uint64_t saved_rectified_plates = 0;
        std::uint64_t plate_color_calls = 0;
        std::uint64_t plate_color_other = 0;
        std::map<std::string, std::uint64_t> plate_color_counts;
        std::map<int, std::map<std::string, std::uint64_t>> plate_color_counts_by_track;
        std::uint64_t plate_ocr_calls = 0;
        std::uint64_t plate_ocr_nonempty = 0;
        std::uint64_t plate_ocr_accepted = 0;
        std::uint64_t plate_ocr_rejected = 0;
        std::map<std::string, std::uint64_t> plate_ocr_rejection_counts;
        std::map<std::string, std::uint64_t> plate_ocr_text_counts;
        std::map<std::string, std::uint64_t> plate_ocr_accepted_text_counts;
        std::map<int, std::map<std::string, std::uint64_t>>
            plate_ocr_accepted_text_counts_by_track;
        std::uint64_t plate_fusion_updates = 0;
        std::uint64_t plate_fusion_results_count = 0;
        std::uint64_t plate_fusion_stable_observations = 0;
        std::unordered_set<int> plate_fusion_stable_track_ids;
        std::map<int, std::string> plate_fusion_latest_text_by_track;
        std::map<int, std::string> plate_fusion_fused_text_by_track;
        const auto wall_start = std::chrono::steady_clock::now();
        const std::clock_t cpu_start = std::clock();

        vehicle_system::FramePacket packet;
        while (camera.wait_frame(packet)) {
            if (config.runtime.max_frames > 0 && processed_frames >= static_cast<std::uint64_t>(config.runtime.max_frames)) {
                break;
            }
            std::vector<Detection> detections = detector->detect(packet.frame);
            const DetectorTiming timing = detector->last_timing();
            inference_ms.push_back(timing.inference_ms);
            detector_total_ms.push_back(timing.total_ms());
            total_detections += detections.size();
            total_high_confidence_detections += static_cast<std::uint64_t>(std::count_if(
                detections.begin(), detections.end(), [&](const Detection& detection) {
                    return detection.confidence >= config.tracker.high_confidence;
                }));

            const auto tracker_start = std::chrono::steady_clock::now();
            std::vector<vehicle_system::TrackedObject> tracks = tracker.update(detections, packet.frame_id);
            tracker_ms.push_back(std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - tracker_start).count());
            tracked_observations += tracks.size();
            vehicle_fusion.prune(packet.frame_id);
            plate_fusion.prune(packet.frame_id);
            for (const vehicle_system::TrackedObject& track : tracks) {
                unique_track_ids.insert(track.track_id);
                ++track_observation_counts[track.track_id];
                if (track.confidence < config.tracker.high_confidence) {
                    ++tracked_low_confidence_observations;
                }
            }

            const auto crop_start = std::chrono::steady_clock::now();
            struct IndexedCrop {
                std::size_t track_index = 0;
                vehicle_system::VehicleCrop crop;
            };
            std::vector<IndexedCrop> crops;
            std::vector<std::optional<vehicle_system::VehicleFusionResult>> fused_colors(tracks.size());
            std::vector<std::optional<vehicle_system::PlateFusionResult>> fused_plates(tracks.size());
            struct IndexedPlateCrop {
                int track_id = -1;
                std::size_t plate_index = 0;
                vehicle_system::PlateCrop crop;
                vehicle_system::PlateQuality quality;
                std::optional<vehicle_system::RectifiedPlate> rectified;
                std::optional<vehicle_system::ColorResult> color;
                std::optional<vehicle_system::PlateOCRResult> ocr;
            };
            std::vector<IndexedPlateCrop> indexed_plate_crops;
            std::vector<GlobalPlateAnnotation> plate_annotations;
            for (std::size_t track_index = 0; track_index < tracks.size(); ++track_index) {
                const vehicle_system::TrackedObject& track = tracks[track_index];
                if (!is_vehicle(track.type)) {
                    continue;
                }
                ++vehicle_crop_attempts;
                Detection tracked_detection;
                tracked_detection.class_id = track.class_id;
                tracked_detection.confidence = track.confidence;
                tracked_detection.bbox = track.bbox;
                tracked_detection.type = track.type;
                auto crop = cropper.crop(packet.frame, tracked_detection);
                if (crop.has_value()) {
                    crops.push_back({track_index, std::move(*crop)});
                } else {
                    ++invalid_vehicle_crops;
                }
            }
            cropper_ms.push_back(std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - crop_start).count());
            vehicle_crops += crops.size();

            for (const IndexedCrop& indexed_crop : crops) {
                vehicle_system::ColorResult result = color_classifier->classify(indexed_crop.crop.roi);
                const vehicle_system::ClassifierTiming color_timing = color_classifier->last_timing();
                color_inference_ms.push_back(color_timing.inference_ms);
                color_total_ms.push_back(color_timing.total_ms());
                ++vehicle_color_calls;
                if (result.color == "other") {
                    ++vehicle_color_other;
                }
                const int track_id = tracks[indexed_crop.track_index].track_id;
                const auto fusion_start = std::chrono::steady_clock::now();
                std::optional<vehicle_system::VehicleFusionResult> fused =
                    vehicle_fusion.update_color(track_id, result, packet.frame_id);
                vehicle_fusion_update_ms.push_back(std::chrono::duration<double, std::milli>(
                    std::chrono::steady_clock::now() - fusion_start).count());
                ++vehicle_fusion_updates;
                if (fused.has_value()) {
                    ++vehicle_fusion_results;
                    if (fused->stable) {
                        ++vehicle_fusion_stable_observations;
                        vehicle_fusion_stable_track_ids.insert(track_id);
                    }
                    fused_colors[indexed_crop.track_index] = std::move(fused);
                }

                const std::vector<vehicle_system::PlateDetection> plates =
                    plate_detector->detect(indexed_crop.crop.roi);
                const vehicle_system::DetectorTiming plate_timing = plate_detector->last_timing();
                plate_inference_ms.push_back(plate_timing.inference_ms);
                plate_total_ms.push_back(plate_timing.total_ms());
                ++plate_detector_calls;
                plate_detections += plates.size();
                for (std::size_t plate_index = 0; plate_index < plates.size(); ++plate_index) {
                    const vehicle_system::PlateDetection& plate = plates[plate_index];
                    ++plate_detection_counts_by_track[track_id];
                    GlobalPlateAnnotation annotation;
                    annotation.track_id = track_id;
                    annotation.corners = plate.corners;
                    annotation.confidence = plate.confidence;
                    for (cv::Point2f& point : annotation.corners) {
                        point.x += static_cast<float>(indexed_crop.crop.source_bbox.x);
                        point.y += static_cast<float>(indexed_crop.crop.source_bbox.y);
                    }
                    ++plate_crop_attempts;
                    const auto plate_crop_start = std::chrono::steady_clock::now();
                    auto plate_crop = plate_cropper.crop(indexed_crop.crop.roi, plate);
                    plate_cropper_ms.push_back(std::chrono::duration<double, std::milli>(
                        std::chrono::steady_clock::now() - plate_crop_start).count());
                    if (plate_crop.has_value()) {
                        const auto quality_start = std::chrono::steady_clock::now();
                        const vehicle_system::PlateQuality quality =
                            plate_quality_evaluator.evaluate(plate_crop->roi);
                        plate_quality_evaluator_ms.push_back(std::chrono::duration<double, std::milli>(
                            std::chrono::steady_clock::now() - quality_start).count());
                        plate_quality_scores.push_back(quality.quality_score);
                        ++plate_quality_evaluations;
                        if (quality.acceptable) {
                            ++plate_quality_accepted;
                            ++plate_quality_accepted_by_track[track_id];
                        } else {
                            ++plate_quality_rejected;
                            ++plate_quality_rejection_counts[quality.rejection_reason];
                        }
                        std::optional<vehicle_system::RectifiedPlate> rectified;
                        std::optional<vehicle_system::ColorResult> plate_color;
                        std::optional<vehicle_system::PlateOCRResult> plate_ocr;
                        if (quality.acceptable) {
                            const auto rectifier_start = std::chrono::steady_clock::now();
                            rectified = plate_rectifier.rectify(*plate_crop);
                            plate_rectifier_ms.push_back(std::chrono::duration<double, std::milli>(
                                std::chrono::steady_clock::now() - rectifier_start).count());
                            ++plate_rectifier_calls;
                            if (rectified.has_value()) {
                                ++plate_rectifier_successes;
                                switch (rectified->method) {
                                    case vehicle_system::PlateRectificationMethod::Perspective:
                                        ++plate_rectifier_perspective;
                                        break;
                                    case vehicle_system::PlateRectificationMethod::Resize:
                                        ++plate_rectifier_resize;
                                        break;
                                    case vehicle_system::PlateRectificationMethod::ResizeFallback:
                                        ++plate_rectifier_resize_fallback;
                                        break;
                                }
                                plate_color = plate_color_classifier.classify(rectified->image);
                                plate_color_ms.push_back(
                                    plate_color_classifier.last_timing().total_ms());
                                ++plate_color_calls;
                                ++plate_color_counts[plate_color->color];
                                ++plate_color_counts_by_track[track_id][plate_color->color];
                                if (plate_color->color == "other") {
                                    ++plate_color_other;
                                }
                                annotation.color = plate_color->color;
                                annotation.color_confidence = plate_color->confidence;

                                plate_ocr = plate_recognizer.recognize(rectified->image);
                                const vehicle_system::PlateRecognizerTiming ocr_timing =
                                    plate_recognizer.last_timing();
                                plate_ocr_preprocess_ms.push_back(ocr_timing.preprocess_ms);
                                plate_ocr_inference_ms.push_back(ocr_timing.inference_ms);
                                plate_ocr_decode_ms.push_back(ocr_timing.decode_ms);
                                plate_ocr_total_ms.push_back(ocr_timing.total_ms());
                                ++plate_ocr_calls;
                                if (!plate_ocr->text.empty()) {
                                    ++plate_ocr_nonempty;
                                    ++plate_ocr_text_counts[plate_ocr->text];
                                }
                                if (plate_ocr->accepted) {
                                    ++plate_ocr_accepted;
                                    ++plate_ocr_accepted_text_counts[plate_ocr->text];
                                    ++plate_ocr_accepted_text_counts_by_track[track_id]
                                        [plate_ocr->text];
                                } else {
                                    ++plate_ocr_rejected;
                                    ++plate_ocr_rejection_counts[plate_ocr->rejection_reason];
                                }
                                vehicle_system::PlateFusionObservation fusion_observation;
                                fusion_observation.frame_id = packet.frame_id;
                                fusion_observation.quality = quality;
                                fusion_observation.ocr = *plate_ocr;
                                fusion_observation.color = *plate_color;
                                const auto plate_fusion_start =
                                    std::chrono::steady_clock::now();
                                const std::optional<vehicle_system::PlateFusionResult>
                                    current_fusion = plate_fusion.update(
                                        track_id, fusion_observation);
                                plate_fusion_update_ms.push_back(
                                    std::chrono::duration<double, std::milli>(
                                        std::chrono::steady_clock::now() -
                                        plate_fusion_start).count());
                                ++plate_fusion_updates;

                                const auto timestamp_ms =
                                    std::chrono::duration_cast<std::chrono::milliseconds>(
                                        packet.timestamp.time_since_epoch()).count();
                                if (ocr_results) {
                                    ocr_results << std::fixed << std::setprecision(6)
                                        << "{\"camera_id\":" << packet.camera_id
                                        << ",\"lane_id\":" << packet.lane_id
                                        << ",\"frame_id\":" << packet.frame_id
                                        << ",\"track_id\":" << track_id
                                        << ",\"plate_index\":" << plate_index
                                        << ",\"timestamp_ms\":" << timestamp_ms
                                        << ",\"text\":\"" << json_escape(plate_ocr->text)
                                        << "\",\"confidence\":" << plate_ocr->confidence
                                        << ",\"format_valid\":"
                                        << (plate_ocr->format_valid ? "true" : "false")
                                        << ",\"accepted\":"
                                        << (plate_ocr->accepted ? "true" : "false")
                                        << ",\"rejection_reason\":\""
                                        << json_escape(plate_ocr->rejection_reason)
                                        << "\",\"plate_color\":\""
                                        << json_escape(plate_color->color)
                                        << "\",\"plate_color_confidence\":"
                                        << plate_color->confidence
                                        << ",\"quality_score\":" << quality.quality_score
                                        << "}\n";
                                }
                                if (plate_fusion_results) {
                                    plate_fusion_results << std::fixed << std::setprecision(6)
                                        << "{\"camera_id\":" << packet.camera_id
                                        << ",\"lane_id\":" << packet.lane_id
                                        << ",\"frame_id\":" << packet.frame_id
                                        << ",\"track_id\":" << track_id
                                        << ",\"input_text\":\""
                                        << json_escape(plate_ocr->text)
                                        << "\",\"input_accepted\":"
                                        << (plate_ocr->accepted ? "true" : "false");
                                    if (current_fusion.has_value()) {
                                        plate_fusion_results
                                            << ",\"latest_text\":\""
                                            << json_escape(current_fusion->latest_ocr.text)
                                            << "\",\"fused_text\":\""
                                            << json_escape(current_fusion->fused_ocr.text)
                                            << "\",\"fused_confidence\":"
                                            << current_fusion->fused_ocr.confidence
                                            << ",\"text_sample_count\":"
                                            << current_fusion->text_sample_count
                                            << ",\"winner_count\":"
                                            << current_fusion->winner_count
                                            << ",\"text_vote_ratio\":"
                                            << current_fusion->text_vote_ratio
                                            << ",\"plate_color\":\""
                                            << json_escape(current_fusion->color.color)
                                            << "\",\"plate_color_confidence\":"
                                            << current_fusion->color.confidence
                                            << ",\"color_vote_ratio\":"
                                            << current_fusion->color_vote_ratio
                                            << ",\"stable\":"
                                            << (current_fusion->stable ? "true" : "false");
                                    } else {
                                        plate_fusion_results
                                            << ",\"latest_text\":\"\",\"fused_text\":\"\""
                                            << ",\"fused_confidence\":0.0"
                                            << ",\"text_sample_count\":0,\"winner_count\":0"
                                            << ",\"text_vote_ratio\":0.0,\"plate_color\":\"\""
                                            << ",\"plate_color_confidence\":0.0"
                                            << ",\"color_vote_ratio\":0.0,\"stable\":false";
                                    }
                                    plate_fusion_results << "}\n";
                                }
                                std::cout << "[OCR] frame=" << packet.frame_id
                                          << " track=" << track_id
                                          << " text=" << plate_ocr->text
                                          << " conf=" << std::fixed << std::setprecision(3)
                                          << plate_ocr->confidence
                                          << " accepted="
                                          << (plate_ocr->accepted ? "yes" : "no");
                                if (!plate_ocr->accepted) {
                                    std::cout << " rejection="
                                              << plate_ocr->rejection_reason;
                                }
                                std::cout << '\n';
                            } else {
                                ++plate_rectifier_failures;
                            }
                        }
                        annotation.quality_evaluated = true;
                        annotation.quality_score = quality.quality_score;
                        annotation.quality_acceptable = quality.acceptable;
                        indexed_plate_crops.push_back(
                            {track_id, plate_index, std::move(*plate_crop), quality,
                                std::move(rectified), std::move(plate_color),
                                std::move(plate_ocr)});
                    } else {
                        ++invalid_plate_crops;
                    }
                    plate_annotations.push_back(annotation);
                }
            }
            plate_crops += indexed_plate_crops.size();
            for (std::size_t track_index = 0; track_index < tracks.size(); ++track_index) {
                const int track_id = tracks[track_index].track_id;
                std::optional<vehicle_system::PlateFusionResult> result =
                    plate_fusion.result(track_id);
                if (!result.has_value()) {
                    continue;
                }
                ++plate_fusion_results_count;
                if (!result->latest_ocr.text.empty()) {
                    plate_fusion_latest_text_by_track[track_id] = result->latest_ocr.text;
                }
                if (!result->fused_ocr.text.empty()) {
                    plate_fusion_fused_text_by_track[track_id] = result->fused_ocr.text;
                }
                if (result->stable) {
                    ++plate_fusion_stable_observations;
                    plate_fusion_stable_track_ids.insert(track_id);
                }
                fused_plates[track_index] = std::move(result);
            }

            for (std::size_t index = 0; index < crops.size() &&
                saved_vehicle_rois < static_cast<std::uint64_t>(std::max(0, config.runtime.max_saved_vehicle_rois));
                ++index) {
                if (config.runtime.vehicle_roi_dir.empty()) {
                    break;
                }
                std::filesystem::create_directories(config.runtime.vehicle_roi_dir);
                std::ostringstream filename;
                filename << "camera_" << packet.camera_id
                         << "_frame_" << std::setw(6) << std::setfill('0') << packet.frame_id
                         << "_track_" << tracks[crops[index].track_index].track_id
                         << "_crop_" << index << ".jpg";
                const std::filesystem::path output_path = config.runtime.vehicle_roi_dir / filename.str();
                if (!cv::imwrite(output_path.u8string(), crops[index].crop.roi)) {
                    throw std::runtime_error("Cannot write vehicle ROI: " + output_path.u8string());
                }
                ++saved_vehicle_rois;
            }
            for (const IndexedPlateCrop& indexed_plate : indexed_plate_crops) {
                if (saved_plate_rois >= static_cast<std::uint64_t>(
                        std::max(0, config.runtime.max_saved_plate_rois)) ||
                    config.runtime.plate_roi_dir.empty()) {
                    break;
                }
                std::filesystem::create_directories(config.runtime.plate_roi_dir);
                std::ostringstream filename;
                filename << "camera_" << packet.camera_id
                         << "_frame_" << std::setw(6) << std::setfill('0') << packet.frame_id
                         << "_track_" << indexed_plate.track_id
                         << "_plate_" << indexed_plate.plate_index
                         << "_q_" << static_cast<int>(std::round(
                                indexed_plate.quality.quality_score * 1000.0F))
                         << (indexed_plate.quality.acceptable ? "_pass.jpg" : "_reject.jpg");
                const std::filesystem::path output_path =
                    config.runtime.plate_roi_dir / filename.str();
                if (!cv::imwrite(output_path.u8string(), indexed_plate.crop.roi)) {
                    throw std::runtime_error("Cannot write plate ROI: " + output_path.u8string());
                }
                ++saved_plate_rois;
            }
            for (const IndexedPlateCrop& indexed_plate : indexed_plate_crops) {
                if (saved_rectified_plates >= static_cast<std::uint64_t>(
                        std::max(0, config.runtime.max_saved_rectified_plates)) ||
                    config.runtime.rectified_plate_dir.empty()) {
                    break;
                }
                if (!indexed_plate.rectified.has_value()) {
                    continue;
                }
                std::filesystem::create_directories(config.runtime.rectified_plate_dir);
                std::ostringstream filename;
                filename << "camera_" << packet.camera_id
                         << "_frame_" << std::setw(6) << std::setfill('0') << packet.frame_id
                         << "_track_" << indexed_plate.track_id
                         << "_plate_" << indexed_plate.plate_index
                         << "_q_" << static_cast<int>(std::round(
                                indexed_plate.quality.quality_score * 1000.0F))
                         << '_' << rectification_method_name(indexed_plate.rectified->method);
                if (indexed_plate.color.has_value()) {
                    filename << "_color_" << indexed_plate.color->color
                             << '_' << static_cast<int>(std::round(
                                    indexed_plate.color->confidence * 1000.0F));
                }
                if (indexed_plate.ocr.has_value()) {
                    filename << (indexed_plate.ocr->accepted ? "_ocr_ok_" : "_ocr_reject_")
                             << static_cast<int>(std::round(
                                    indexed_plate.ocr->confidence * 1000.0F));
                }
                filename
                         << ".jpg";
                const std::filesystem::path output_path =
                    config.runtime.rectified_plate_dir / filename.str();
                if (!cv::imwrite(output_path.u8string(), indexed_plate.rectified->image)) {
                    throw std::runtime_error(
                        "Cannot write rectified plate: " + output_path.u8string());
                }
                ++saved_rectified_plates;
            }
            draw_tracks(packet.frame, tracks, fused_colors, fused_plates, text_renderer);
            draw_plates(packet.frame, plate_annotations);

            std::ostringstream status;
            status << "camera:" << packet.camera_id << " lane:" << packet.lane_id
                   << " frame:" << packet.frame_id << " det:" << detections.size()
                   << " tracks:" << tracks.size()
                   << " infer:" << std::fixed << std::setprecision(1) << timing.inference_ms << "ms";
            cv::putText(packet.frame, status.str(), cv::Point(20, 35), cv::FONT_HERSHEY_SIMPLEX,
                0.8, cv::Scalar(0, 255, 255), 2, cv::LINE_AA);

            if (!writer.isOpened() && !config.runtime.output_video.empty()) {
                ensure_parent(config.runtime.output_video);
                const double output_fps = camera.source_fps() > 0.0 ? camera.source_fps() : 24.0;
                writer.open(config.runtime.output_video.u8string(), cv::VideoWriter::fourcc('m', 'p', '4', 'v'),
                    output_fps, packet.frame.size());
                if (!writer.isOpened()) {
                    throw std::runtime_error("Cannot create output video: " + config.runtime.output_video.u8string());
                }
            }
            if (writer.isOpened()) {
                writer.write(packet.frame);
            }
            if (config.runtime.display) {
                cv::imshow("RK3588 Vehicle System - PC Stage 11", packet.frame);
                const int key = cv::waitKey(1);
                if (key == 27 || key == 'q' || key == 'Q') {
                    break;
                }
            }

            ++processed_frames;
            if (config.runtime.report_interval > 0 &&
                processed_frames % static_cast<std::uint64_t>(config.runtime.report_interval) == 0) {
                const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - wall_start).count();
                std::cout << "[PERF] frames=" << processed_frames
                          << " fps=" << std::fixed << std::setprecision(2) << (processed_frames / elapsed)
                          << " infer_ms=" << timing.inference_ms
                          << " detections=" << total_detections
                          << " tracks=" << tracked_observations
                          << " unique_ids=" << unique_track_ids.size()
                          << " crops=" << vehicle_crops
                          << " color_calls=" << vehicle_color_calls
                          << " fusion_stable=" << vehicle_fusion_stable_observations
                          << " plate_hits=" << plate_detections
                          << " quality_pass=" << plate_quality_accepted << '/'
                          << plate_quality_evaluations
                          << " rectified=" << plate_rectifier_successes << '/'
                          << plate_rectifier_calls
                          << " plate_color=" << plate_color_calls
                          << " ocr=" << plate_ocr_accepted << '/' << plate_ocr_calls
                          << " plate_fusion=" << plate_fusion_stable_track_ids.size()
                          << '/' << plate_fusion_updates
                          << " dropped=" << camera.dropped_frames() << '\n';
            }
        }

        camera.stop();
        writer.release();
        if (config.runtime.display) {
            cv::destroyAllWindows();
        }
        if (processed_frames == 0 && !camera.last_error().empty()) {
            throw std::runtime_error(camera.last_error());
        }

        const double wall_seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - wall_start).count();
        const double cpu_seconds = static_cast<double>(std::clock() - cpu_start) / CLOCKS_PER_SEC;
        write_summary(config, processed_frames, total_detections, total_high_confidence_detections,
            tracked_observations, tracked_low_confidence_observations,
            unique_track_ids.size(), track_observation_counts, camera.dropped_frames(),
            vehicle_crop_attempts, vehicle_crops, invalid_vehicle_crops, saved_vehicle_rois,
            vehicle_color_calls, vehicle_color_other,
            vehicle_fusion_updates, vehicle_fusion_results,
            vehicle_fusion_stable_observations, vehicle_fusion_stable_track_ids.size(),
            plate_detector_calls, plate_detections, plate_detection_counts_by_track,
            plate_crop_attempts, plate_crops,
            invalid_plate_crops, saved_plate_rois,
            plate_quality_evaluations, plate_quality_accepted, plate_quality_rejected,
            plate_quality_accepted_by_track, plate_quality_rejection_counts,
            plate_rectifier_calls, plate_rectifier_successes, plate_rectifier_failures,
            plate_rectifier_perspective, plate_rectifier_resize,
            plate_rectifier_resize_fallback, saved_rectified_plates,
            plate_color_calls, plate_color_other, plate_color_counts,
            plate_color_counts_by_track,
            plate_ocr_calls, plate_ocr_nonempty, plate_ocr_accepted,
            plate_ocr_rejected, plate_ocr_rejection_counts,
            plate_ocr_text_counts, plate_ocr_accepted_text_counts,
            plate_ocr_accepted_text_counts_by_track,
            plate_fusion_updates, plate_fusion_results_count,
            plate_fusion_stable_observations,
            plate_fusion_stable_track_ids.size(),
            plate_fusion_latest_text_by_track,
            plate_fusion_fused_text_by_track,
            wall_seconds, cpu_seconds,
            inference_ms, detector_total_ms, cropper_ms, tracker_ms,
            color_inference_ms, color_total_ms, vehicle_fusion_update_ms,
            plate_inference_ms, plate_total_ms, plate_cropper_ms,
            plate_quality_evaluator_ms, plate_quality_scores, plate_rectifier_ms,
            plate_color_ms, plate_ocr_preprocess_ms, plate_ocr_inference_ms,
            plate_ocr_decode_ms, plate_ocr_total_ms, plate_fusion_update_ms);
        std::cout << "Summary: " << config.runtime.summary_json.u8string() << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "ERROR: " << error.what() << '\n';
        return 1;
    }
}
