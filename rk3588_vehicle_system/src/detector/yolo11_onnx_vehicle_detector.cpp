#include "detector/yolo11_onnx_vehicle_detector.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <numeric>
#include <onnxruntime_cxx_api.h>
#include <opencv2/dnn.hpp>
#include <opencv2/imgproc.hpp>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace vehicle_system {
namespace {

using Clock = std::chrono::steady_clock;

double elapsed_ms(Clock::time_point start, Clock::time_point end) {
    return std::chrono::duration<double, std::milli>(end - start).count();
}

struct LetterboxResult {
    cv::Mat image;
    float scale = 1.0F;
    int pad_x = 0;
    int pad_y = 0;
};

LetterboxResult letterbox(const cv::Mat& frame, int target_width, int target_height) {
    const float scale = std::min(
        static_cast<float>(target_width) / static_cast<float>(frame.cols),
        static_cast<float>(target_height) / static_cast<float>(frame.rows));
    const int resized_width = static_cast<int>(std::round(frame.cols * scale));
    const int resized_height = static_cast<int>(std::round(frame.rows * scale));
    const int pad_x = (target_width - resized_width) / 2;
    const int pad_y = (target_height - resized_height) / 2;

    cv::Mat resized;
    cv::resize(frame, resized, cv::Size(resized_width, resized_height), 0.0, 0.0, cv::INTER_LINEAR);
    cv::Mat padded(target_height, target_width, CV_8UC3, cv::Scalar(114, 114, 114));
    resized.copyTo(padded(cv::Rect(pad_x, pad_y, resized_width, resized_height)));
    return {std::move(padded), scale, pad_x, pad_y};
}

float dfl_expectation(const float* values, int length, std::size_t spatial_offset, std::size_t grid_size) {
    float maximum = values[spatial_offset];
    for (int index = 1; index < length; ++index) {
        maximum = std::max(maximum, values[static_cast<std::size_t>(index) * grid_size + spatial_offset]);
    }
    float denominator = 0.0F;
    float numerator = 0.0F;
    for (int index = 0; index < length; ++index) {
        const float probability = std::exp(values[static_cast<std::size_t>(index) * grid_size + spatial_offset] - maximum);
        denominator += probability;
        numerator += probability * static_cast<float>(index);
    }
    return denominator > 0.0F ? numerator / denominator : 0.0F;
}

bool is_supported_coco_class(int class_id) {
    return class_id == 0 || class_id == 1 || class_id == 2 || class_id == 3 || class_id == 5 || class_id == 7;
}

cv::Rect map_box(float x1, float y1, float x2, float y2, const LetterboxResult& letterbox_info, const cv::Size& original) {
    x1 = (x1 - static_cast<float>(letterbox_info.pad_x)) / letterbox_info.scale;
    y1 = (y1 - static_cast<float>(letterbox_info.pad_y)) / letterbox_info.scale;
    x2 = (x2 - static_cast<float>(letterbox_info.pad_x)) / letterbox_info.scale;
    y2 = (y2 - static_cast<float>(letterbox_info.pad_y)) / letterbox_info.scale;

    x1 = std::clamp(x1, 0.0F, static_cast<float>(original.width - 1));
    y1 = std::clamp(y1, 0.0F, static_cast<float>(original.height - 1));
    x2 = std::clamp(x2, 0.0F, static_cast<float>(original.width));
    y2 = std::clamp(y2, 0.0F, static_cast<float>(original.height));
    const int left = static_cast<int>(std::floor(x1));
    const int top = static_cast<int>(std::floor(y1));
    const int right = static_cast<int>(std::ceil(x2));
    const int bottom = static_cast<int>(std::ceil(y2));
    return cv::Rect(left, top, std::max(0, right - left), std::max(0, bottom - top));
}

}  // namespace

struct Yolo11OnnxVehicleDetector::Impl {
    explicit Impl(const DetectorConfig& detector_config)
        : config(detector_config),
          env(ORT_LOGGING_LEVEL_WARNING, "vehicle-yolo11"),
          session_options(),
          session(nullptr) {
        if (!std::filesystem::exists(config.model_path)) {
            throw std::runtime_error("YOLO11 model does not exist: " + config.model_path.u8string());
        }
        session_options.SetIntraOpNumThreads(std::max(1, config.intra_op_threads));
        session_options.SetInterOpNumThreads(1);
        session_options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
        session = Ort::Session(env, config.model_path.c_str(), session_options);

        Ort::AllocatorWithDefaultOptions allocator;
        const std::size_t input_count = session.GetInputCount();
        const std::size_t output_count = session.GetOutputCount();
        if (input_count != 1 || output_count != 9) {
            throw std::runtime_error("Rockchip YOLO11 model must have 1 input and 9 outputs");
        }
        for (std::size_t index = 0; index < input_count; ++index) {
            auto name = session.GetInputNameAllocated(index, allocator);
            input_names_storage.emplace_back(name.get());
        }
        for (std::size_t index = 0; index < output_count; ++index) {
            auto name = session.GetOutputNameAllocated(index, allocator);
            output_names_storage.emplace_back(name.get());
        }
        for (const std::string& name : input_names_storage) {
            input_names.push_back(name.c_str());
        }
        for (const std::string& name : output_names_storage) {
            output_names.push_back(name.c_str());
        }

        const std::vector<std::int64_t> input_shape = session.GetInputTypeInfo(0).GetTensorTypeAndShapeInfo().GetShape();
        if (input_shape.size() != 4 || input_shape[0] != 1 || input_shape[1] != 3 ||
            input_shape[2] != config.input_height || input_shape[3] != config.input_width) {
            throw std::runtime_error("YOLO11 input shape does not match config");
        }
    }

    DetectorConfig config;
    Ort::Env env;
    Ort::SessionOptions session_options;
    Ort::Session session;
    std::vector<std::string> input_names_storage;
    std::vector<std::string> output_names_storage;
    std::vector<const char*> input_names;
    std::vector<const char*> output_names;
    DetectorTiming timing;
};

Yolo11OnnxVehicleDetector::Yolo11OnnxVehicleDetector(const DetectorConfig& config)
    : impl_(std::make_unique<Impl>(config)) {}

Yolo11OnnxVehicleDetector::~Yolo11OnnxVehicleDetector() = default;

std::vector<Detection> Yolo11OnnxVehicleDetector::detect(const cv::Mat& frame) {
    if (frame.empty() || frame.type() != CV_8UC3) {
        throw std::invalid_argument("Yolo11OnnxVehicleDetector expects a non-empty CV_8UC3 frame");
    }

    const auto preprocess_start = Clock::now();
    LetterboxResult letterbox_info = letterbox(frame, impl_->config.input_width, impl_->config.input_height);
    cv::Mat blob = cv::dnn::blobFromImage(
        letterbox_info.image, 1.0 / 255.0, cv::Size(), cv::Scalar(), true, false, CV_32F);
    const std::array<std::int64_t, 4> input_shape = {
        1, 3, impl_->config.input_height, impl_->config.input_width};
    Ort::MemoryInfo memory_info = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    Ort::Value input_tensor = Ort::Value::CreateTensor<float>(
        memory_info, blob.ptr<float>(), blob.total(), input_shape.data(), input_shape.size());
    const auto preprocess_end = Clock::now();

    const auto inference_start = Clock::now();
    std::vector<Ort::Value> outputs = impl_->session.Run(
        Ort::RunOptions{nullptr}, impl_->input_names.data(), &input_tensor, 1,
        impl_->output_names.data(), impl_->output_names.size());
    const auto inference_end = Clock::now();

    const auto postprocess_start = Clock::now();
    std::vector<Detection> candidates;
    for (int branch = 0; branch < 3; ++branch) {
        Ort::Value& box_output = outputs[static_cast<std::size_t>(branch) * 3];
        Ort::Value& score_output = outputs[static_cast<std::size_t>(branch) * 3 + 1];
        Ort::Value& score_sum_output = outputs[static_cast<std::size_t>(branch) * 3 + 2];
        const std::vector<std::int64_t> box_shape = box_output.GetTensorTypeAndShapeInfo().GetShape();
        const std::vector<std::int64_t> score_shape = score_output.GetTensorTypeAndShapeInfo().GetShape();
        if (box_shape.size() != 4 || score_shape.size() != 4 || box_shape[1] != 64 || score_shape[1] != 80) {
            throw std::runtime_error("Unexpected Rockchip YOLO11 output layout");
        }
        const int grid_height = static_cast<int>(box_shape[2]);
        const int grid_width = static_cast<int>(box_shape[3]);
        const int stride = impl_->config.input_height / grid_height;
        const std::size_t grid_size = static_cast<std::size_t>(grid_height) * static_cast<std::size_t>(grid_width);
        const float* box_data = box_output.GetTensorData<float>();
        const float* score_data = score_output.GetTensorData<float>();
        const float* score_sum_data = score_sum_output.GetTensorData<float>();

        for (int row = 0; row < grid_height; ++row) {
            for (int column = 0; column < grid_width; ++column) {
                const std::size_t offset = static_cast<std::size_t>(row) * grid_width + column;
                if (score_sum_data[offset] < impl_->config.confidence) {
                    continue;
                }

                int best_class = -1;
                float best_score = impl_->config.confidence;
                for (int class_id = 0; class_id < 80; ++class_id) {
                    if (!is_supported_coco_class(class_id)) {
                        continue;
                    }
                    const float score = score_data[static_cast<std::size_t>(class_id) * grid_size + offset];
                    if (score > best_score) {
                        best_score = score;
                        best_class = class_id;
                    }
                }
                if (best_class < 0) {
                    continue;
                }

                std::array<float, 4> distances{};
                for (int side = 0; side < 4; ++side) {
                    distances[side] = dfl_expectation(
                        box_data + static_cast<std::size_t>(side) * 16 * grid_size, 16, offset, grid_size);
                }
                const float center_x = static_cast<float>(column) + 0.5F;
                const float center_y = static_cast<float>(row) + 0.5F;
                const float x1 = (center_x - distances[0]) * stride;
                const float y1 = (center_y - distances[1]) * stride;
                const float x2 = (center_x + distances[2]) * stride;
                const float y2 = (center_y + distances[3]) * stride;
                cv::Rect box = map_box(x1, y1, x2, y2, letterbox_info, frame.size());
                if (box.width <= 1 || box.height <= 1) {
                    continue;
                }
                candidates.push_back({best_class, best_score, box, object_type_from_coco(best_class)});
            }
        }
    }

    std::vector<Detection> detections;
    std::unordered_map<int, std::vector<std::size_t>> grouped_indices;
    for (std::size_t index = 0; index < candidates.size(); ++index) {
        grouped_indices[candidates[index].class_id].push_back(index);
    }
    for (const auto& entry : grouped_indices) {
        std::vector<cv::Rect> boxes;
        std::vector<float> scores;
        boxes.reserve(entry.second.size());
        scores.reserve(entry.second.size());
        for (std::size_t candidate_index : entry.second) {
            boxes.push_back(candidates[candidate_index].bbox);
            scores.push_back(candidates[candidate_index].confidence);
        }
        std::vector<int> selected;
        cv::dnn::NMSBoxes(boxes, scores, impl_->config.confidence, impl_->config.nms, selected);
        for (int local_index : selected) {
            detections.push_back(candidates[entry.second[static_cast<std::size_t>(local_index)]]);
        }
    }
    std::sort(detections.begin(), detections.end(), [](const Detection& left, const Detection& right) {
        return left.confidence > right.confidence;
    });
    const auto postprocess_end = Clock::now();

    impl_->timing.preprocess_ms = elapsed_ms(preprocess_start, preprocess_end);
    impl_->timing.inference_ms = elapsed_ms(inference_start, inference_end);
    impl_->timing.postprocess_ms = elapsed_ms(postprocess_start, postprocess_end);
    return detections;
}

DetectorTiming Yolo11OnnxVehicleDetector::last_timing() const {
    return impl_->timing;
}

}  // namespace vehicle_system

