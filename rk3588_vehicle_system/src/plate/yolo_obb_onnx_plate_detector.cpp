#include "plate/yolo_obb_onnx_plate_detector.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <limits>
#include <numeric>
#include <onnxruntime_cxx_api.h>
#include <opencv2/dnn.hpp>
#include <opencv2/imgproc.hpp>
#include <stdexcept>
#include <string>
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

struct ObbCandidate {
    float center_x = 0.0F;
    float center_y = 0.0F;
    float width = 0.0F;
    float height = 0.0F;
    float confidence = 0.0F;
    float angle_radians = 0.0F;
};

struct Covariance {
    double a = 0.0;
    double b = 0.0;
    double c = 0.0;
};

LetterboxResult letterbox(const cv::Mat& image, int target_width, int target_height) {
    const float scale = std::min(
        static_cast<float>(target_width) / static_cast<float>(image.cols),
        static_cast<float>(target_height) / static_cast<float>(image.rows));
    const int resized_width = static_cast<int>(std::round(image.cols * scale));
    const int resized_height = static_cast<int>(std::round(image.rows * scale));
    const int pad_x = (target_width - resized_width) / 2;
    const int pad_y = (target_height - resized_height) / 2;

    cv::Mat resized;
    cv::resize(image, resized, cv::Size(resized_width, resized_height), 0.0, 0.0, cv::INTER_LINEAR);
    cv::Mat padded(target_height, target_width, CV_8UC3, cv::Scalar(114, 114, 114));
    resized.copyTo(padded(cv::Rect(pad_x, pad_y, resized_width, resized_height)));
    return {std::move(padded), scale, pad_x, pad_y};
}

Covariance covariance(const ObbCandidate& box) {
    const double width_variance = static_cast<double>(box.width) * box.width / 12.0;
    const double height_variance = static_cast<double>(box.height) * box.height / 12.0;
    const double cosine = std::cos(static_cast<double>(box.angle_radians));
    const double sine = std::sin(static_cast<double>(box.angle_radians));
    const double cosine_squared = cosine * cosine;
    const double sine_squared = sine * sine;
    return {
        width_variance * cosine_squared + height_variance * sine_squared,
        width_variance * sine_squared + height_variance * cosine_squared,
        (width_variance - height_variance) * cosine * sine};
}

double probabilistic_iou(const ObbCandidate& left, const ObbCandidate& right) {
    constexpr double epsilon = 1.0e-7;
    const Covariance left_covariance = covariance(left);
    const Covariance right_covariance = covariance(right);
    const double combined_a = left_covariance.a + right_covariance.a;
    const double combined_b = left_covariance.b + right_covariance.b;
    const double combined_c = left_covariance.c + right_covariance.c;
    const double determinant = combined_a * combined_b - combined_c * combined_c;
    const double delta_x = static_cast<double>(left.center_x) - right.center_x;
    const double delta_y = static_cast<double>(left.center_y) - right.center_y;

    const double term1 = 0.25 *
        (combined_a * delta_y * delta_y + combined_b * delta_x * delta_x) /
        (determinant + epsilon);
    const double term2 = 0.5 * combined_c *
        (static_cast<double>(right.center_x) - left.center_x) *
        (static_cast<double>(left.center_y) - right.center_y) /
        (determinant + epsilon);
    const double left_determinant = std::max(
        0.0, left_covariance.a * left_covariance.b - left_covariance.c * left_covariance.c);
    const double right_determinant = std::max(
        0.0, right_covariance.a * right_covariance.b - right_covariance.c * right_covariance.c);
    const double denominator = 4.0 * std::sqrt(left_determinant * right_determinant) + epsilon;
    const double term3 = 0.5 * std::log(std::max(epsilon, determinant / denominator + epsilon));
    const double bhattacharyya_distance = std::clamp(term1 + term2 + term3, epsilon, 100.0);
    const double hellinger_distance = std::sqrt(
        std::max(0.0, 1.0 - std::exp(-bhattacharyya_distance) + epsilon));
    return std::clamp(1.0 - hellinger_distance, 0.0, 1.0);
}

std::array<cv::Point2f, 4> map_corners(
    const ObbCandidate& box,
    const LetterboxResult& letterbox_info,
    const cv::Size& original_size) {
    const float cosine = std::cos(box.angle_radians);
    const float sine = std::sin(box.angle_radians);
    const cv::Point2f center(box.center_x, box.center_y);
    const cv::Point2f vector_width(box.width * 0.5F * cosine, box.width * 0.5F * sine);
    const cv::Point2f vector_height(-box.height * 0.5F * sine, box.height * 0.5F * cosine);
    std::array<cv::Point2f, 4> corners = {
        center + vector_width + vector_height,
        center + vector_width - vector_height,
        center - vector_width - vector_height,
        center - vector_width + vector_height};
    for (cv::Point2f& point : corners) {
        point.x = (point.x - static_cast<float>(letterbox_info.pad_x)) / letterbox_info.scale;
        point.y = (point.y - static_cast<float>(letterbox_info.pad_y)) / letterbox_info.scale;
        point.x = std::clamp(point.x, 0.0F, static_cast<float>(original_size.width));
        point.y = std::clamp(point.y, 0.0F, static_cast<float>(original_size.height));
    }
    return corners;
}

cv::Rect bounding_box(const std::array<cv::Point2f, 4>& corners, const cv::Size& bounds) {
    float left = corners[0].x;
    float right = corners[0].x;
    float top = corners[0].y;
    float bottom = corners[0].y;
    for (const cv::Point2f& point : corners) {
        left = std::min(left, point.x);
        right = std::max(right, point.x);
        top = std::min(top, point.y);
        bottom = std::max(bottom, point.y);
    }
    const int x1 = std::clamp(static_cast<int>(std::floor(left)), 0, bounds.width);
    const int y1 = std::clamp(static_cast<int>(std::floor(top)), 0, bounds.height);
    const int x2 = std::clamp(static_cast<int>(std::ceil(right)), 0, bounds.width);
    const int y2 = std::clamp(static_cast<int>(std::ceil(bottom)), 0, bounds.height);
    return {x1, y1, std::max(0, x2 - x1), std::max(0, y2 - y1)};
}

}  // namespace

struct YoloObbOnnxPlateDetector::Impl {
    explicit Impl(const PlateDetectorConfig& detector_config)
        : config(detector_config),
          env(ORT_LOGGING_LEVEL_WARNING, "plate-yolo-obb"),
          session_options(),
          session(nullptr) {
        if (!std::filesystem::exists(config.model_path)) {
            throw std::runtime_error("Plate OBB model does not exist: " + config.model_path.u8string());
        }
        if (config.input_width <= 0 || config.input_height <= 0 ||
            config.confidence < 0.0F || config.confidence > 1.0F ||
            config.nms < 0.0F || config.nms > 1.0F || config.max_detections <= 0) {
            throw std::invalid_argument("Invalid PlateDetector configuration");
        }

        session_options.SetIntraOpNumThreads(std::max(1, config.intra_op_threads));
        session_options.SetInterOpNumThreads(1);
        session_options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
        session = Ort::Session(env, config.model_path.c_str(), session_options);

        Ort::AllocatorWithDefaultOptions allocator;
        if (session.GetInputCount() != 1 || session.GetOutputCount() != 1) {
            throw std::runtime_error("Plate OBB ONNX model must have 1 input and 1 output");
        }
        auto input_name = session.GetInputNameAllocated(0, allocator);
        auto output_name = session.GetOutputNameAllocated(0, allocator);
        input_name_storage = input_name.get();
        output_name_storage = output_name.get();
        input_name_ptr = input_name_storage.c_str();
        output_name_ptr = output_name_storage.c_str();

        const std::vector<std::int64_t> input_shape =
            session.GetInputTypeInfo(0).GetTensorTypeAndShapeInfo().GetShape();
        if (input_shape != std::vector<std::int64_t>{
                1, 3, config.input_height, config.input_width}) {
            throw std::runtime_error("Plate OBB input shape does not match config");
        }
        const std::vector<std::int64_t> output_shape =
            session.GetOutputTypeInfo(0).GetTensorTypeAndShapeInfo().GetShape();
        if (output_shape.size() != 3 || output_shape[0] != 1 ||
            (output_shape[1] != 6 && output_shape[2] != 6)) {
            throw std::runtime_error("Plate OBB output must have shape [1,6,N] or [1,N,6]");
        }
        channels_first = output_shape[1] == 6;
        candidate_count = static_cast<std::size_t>(
            channels_first ? output_shape[2] : output_shape[1]);
    }

    PlateDetectorConfig config;
    Ort::Env env;
    Ort::SessionOptions session_options;
    Ort::Session session;
    std::string input_name_storage;
    std::string output_name_storage;
    const char* input_name_ptr = nullptr;
    const char* output_name_ptr = nullptr;
    bool channels_first = true;
    std::size_t candidate_count = 0;
    DetectorTiming timing;
};

YoloObbOnnxPlateDetector::YoloObbOnnxPlateDetector(const PlateDetectorConfig& config)
    : impl_(std::make_unique<Impl>(config)) {}

YoloObbOnnxPlateDetector::~YoloObbOnnxPlateDetector() = default;

std::vector<PlateDetection> YoloObbOnnxPlateDetector::detect(const cv::Mat& vehicle_roi) {
    if (vehicle_roi.empty() || vehicle_roi.type() != CV_8UC3) {
        throw std::invalid_argument(
            "YoloObbOnnxPlateDetector expects a non-empty CV_8UC3 vehicle ROI");
    }

    const auto preprocess_start = Clock::now();
    LetterboxResult letterbox_info = letterbox(
        vehicle_roi, impl_->config.input_width, impl_->config.input_height);
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
        Ort::RunOptions{nullptr}, &impl_->input_name_ptr, &input_tensor, 1,
        &impl_->output_name_ptr, 1);
    const auto inference_end = Clock::now();

    const auto postprocess_start = Clock::now();
    const float* output = outputs[0].GetTensorData<float>();
    const auto value_at = [&](std::size_t channel, std::size_t candidate) {
        return impl_->channels_first
            ? output[channel * impl_->candidate_count + candidate]
            : output[candidate * 6U + channel];
    };

    std::vector<ObbCandidate> candidates;
    candidates.reserve(32);
    for (std::size_t index = 0; index < impl_->candidate_count; ++index) {
        const float confidence = value_at(4, index);
        if (!std::isfinite(confidence) || confidence < impl_->config.confidence) {
            continue;
        }
        ObbCandidate candidate;
        candidate.center_x = value_at(0, index);
        candidate.center_y = value_at(1, index);
        candidate.width = value_at(2, index);
        candidate.height = value_at(3, index);
        candidate.confidence = confidence;
        candidate.angle_radians = value_at(5, index);
        if (!std::isfinite(candidate.center_x) || !std::isfinite(candidate.center_y) ||
            !std::isfinite(candidate.width) || !std::isfinite(candidate.height) ||
            !std::isfinite(candidate.angle_radians) ||
            candidate.width <= 1.0F || candidate.height <= 1.0F) {
            continue;
        }
        candidates.push_back(candidate);
    }
    std::sort(candidates.begin(), candidates.end(), [](const ObbCandidate& left, const ObbCandidate& right) {
        return left.confidence > right.confidence;
    });

    std::vector<ObbCandidate> selected;
    selected.reserve(static_cast<std::size_t>(impl_->config.max_detections));
    for (const ObbCandidate& candidate : candidates) {
        const bool suppressed = std::any_of(selected.begin(), selected.end(), [&](const ObbCandidate& kept) {
            return probabilistic_iou(candidate, kept) > impl_->config.nms;
        });
        if (suppressed) {
            continue;
        }
        selected.push_back(candidate);
        if (selected.size() >= static_cast<std::size_t>(impl_->config.max_detections)) {
            break;
        }
    }

    std::vector<PlateDetection> detections;
    detections.reserve(selected.size());
    for (const ObbCandidate& selected_box : selected) {
        const std::array<cv::Point2f, 4> corners = map_corners(
            selected_box, letterbox_info, vehicle_roi.size());
        const cv::Rect box = bounding_box(corners, vehicle_roi.size());
        if (box.width <= 1 || box.height <= 1) {
            continue;
        }
        detections.push_back({box, corners, selected_box.confidence, selected_box.angle_radians});
    }
    const auto postprocess_end = Clock::now();

    impl_->timing.preprocess_ms = elapsed_ms(preprocess_start, preprocess_end);
    impl_->timing.inference_ms = elapsed_ms(inference_start, inference_end);
    impl_->timing.postprocess_ms = elapsed_ms(postprocess_start, postprocess_end);
    return detections;
}

DetectorTiming YoloObbOnnxPlateDetector::last_timing() const {
    return impl_->timing;
}

}  // namespace vehicle_system
