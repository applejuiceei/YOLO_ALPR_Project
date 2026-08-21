#include "camera/camera_manager.hpp"
#include "classifier/pp_vehicle_onnx_color_classifier.hpp"
#include "common/config.hpp"
#include "common/types.hpp"
#include "cropper/vehicle_cropper.hpp"
#include "detector/yolo11_onnx_vehicle_detector.hpp"
#include "fusion/confidence_weighted_vehicle_fusion.hpp"
#include "tracker/byte_tracker.hpp"

#include <algorithm>
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
    const std::vector<std::optional<vehicle_system::VehicleFusionResult>>& fused_colors) {
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
        int baseline = 0;
        const cv::Size text_size = cv::getTextSize(label.str(), cv::FONT_HERSHEY_SIMPLEX, 0.6, 2, &baseline);
        const int text_left = std::clamp(display_bbox.x, 0, std::max(0, frame.cols - text_size.width - 8));
        const int text_top = std::max(0, display_bbox.y - text_size.height - baseline - 4);
        cv::rectangle(frame,
            cv::Rect(text_left, text_top, text_size.width + 8, text_size.height + baseline + 4),
            color, cv::FILLED);
        cv::putText(frame, label.str(), cv::Point(text_left + 4, text_top + text_size.height + 1),
            cv::FONT_HERSHEY_SIMPLEX, 0.6, cv::Scalar(20, 20, 20), 2, cv::LINE_AA);
    }
}

bool is_vehicle(vehicle_system::ObjectType type) {
    return type == vehicle_system::ObjectType::Car ||
        type == vehicle_system::ObjectType::Bus ||
        type == vehicle_system::ObjectType::Truck ||
        type == vehicle_system::ObjectType::NonMotor;
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
    double wall_seconds,
    double cpu_seconds,
    const std::vector<double>& inference_ms,
    const std::vector<double>& total_ms,
    const std::vector<double>& cropper_ms,
    const std::vector<double>& tracker_ms,
    const std::vector<double>& color_inference_ms,
    const std::vector<double>& color_total_ms,
    const std::vector<double>& vehicle_fusion_update_ms) {
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
        << percentile(vehicle_fusion_update_ms, 0.95) << "\n"
        << "}\n";
}

}  // namespace

int main(int argc, char** argv) {
    try {
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

        std::cout << "Model: " << config.detector.model_path.u8string() << '\n';
        std::cout << "Vehicle color model: " << config.vehicle_color.model_path.u8string() << '\n';
        std::cout << "Camera source: " << config.camera.source << '\n';
        std::cout << "Backend: ONNX Runtime CPU (NPU not used on PC)\n";

        auto detector = std::make_unique<vehicle_system::Yolo11OnnxVehicleDetector>(config.detector);
        auto color_classifier = std::make_unique<vehicle_system::PpVehicleOnnxColorClassifier>(config.vehicle_color);
        vehicle_system::ByteTracker tracker(config.tracker);
        vehicle_system::ConfidenceWeightedVehicleFusion vehicle_fusion(config.vehicle_fusion);
        vehicle_system::VehicleCropper cropper(config.cropper);
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
            draw_tracks(packet.frame, tracks, fused_colors);

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
                cv::imshow("RK3588 Vehicle System - PC Stage 1", packet.frame);
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
            wall_seconds, cpu_seconds,
            inference_ms, detector_total_ms, cropper_ms, tracker_ms,
            color_inference_ms, color_total_ms, vehicle_fusion_update_ms);
        std::cout << "Summary: " << config.runtime.summary_json.u8string() << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "ERROR: " << error.what() << '\n';
        return 1;
    }
}
