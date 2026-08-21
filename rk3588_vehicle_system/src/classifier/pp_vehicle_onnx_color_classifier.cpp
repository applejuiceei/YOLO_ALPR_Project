#include "classifier/pp_vehicle_onnx_color_classifier.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <onnxruntime_cxx_api.h>
#include <opencv2/imgproc.hpp>
#include <stdexcept>
#include <string>
#include <vector>

namespace vehicle_system {
namespace {

using Clock = std::chrono::steady_clock;

double elapsed_ms(Clock::time_point start, Clock::time_point end) {
    return std::chrono::duration<double, std::milli>(end - start).count();
}

constexpr std::array<const char*, 10> kModelColors = {
    "yellow", "orange", "green", "gray", "red",
    "blue", "white", "golden", "brown", "black"};

constexpr std::array<const char*, 10> kCanonicalColors = {
    "yellow", "other", "green", "gray", "red",
    "blue", "white", "other", "brown", "black"};

}  // namespace

struct PpVehicleOnnxColorClassifier::Impl {
    explicit Impl(const VehicleColorConfig& classifier_config)
        : config(classifier_config),
          env(ORT_LOGGING_LEVEL_WARNING, "pp-vehicle-color"),
          session_options(),
          session(nullptr) {
        if (!std::filesystem::exists(config.model_path)) {
            throw std::runtime_error("PP-Vehicle color model does not exist: " + config.model_path.u8string());
        }
        if (config.input_width <= 0 || config.input_height <= 0) {
            throw std::invalid_argument("Vehicle color input dimensions must be positive");
        }
        if (config.confidence < 0.0F || config.confidence > 1.0F) {
            throw std::invalid_argument("Vehicle color confidence must be within [0, 1]");
        }

        session_options.SetIntraOpNumThreads(std::max(1, config.intra_op_threads));
        session_options.SetInterOpNumThreads(1);
        session_options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
        session = Ort::Session(env, config.model_path.c_str(), session_options);

        if (session.GetInputCount() != 1 || session.GetOutputCount() != 1) {
            throw std::runtime_error("PP-Vehicle color model must have one input and one output");
        }
        Ort::AllocatorWithDefaultOptions allocator;
        auto input_name_value = session.GetInputNameAllocated(0, allocator);
        auto output_name_value = session.GetOutputNameAllocated(0, allocator);
        input_name_storage = input_name_value.get();
        output_name_storage = output_name_value.get();
        input_name = input_name_storage.c_str();
        output_name = output_name_storage.c_str();

        const auto input_shape = session.GetInputTypeInfo(0).GetTensorTypeAndShapeInfo().GetShape();
        if (input_shape.size() != 4 || input_shape[1] != 3 ||
            input_shape[2] != config.input_height || input_shape[3] != config.input_width) {
            throw std::runtime_error("PP-Vehicle color input shape does not match config");
        }
        const auto output_shape = session.GetOutputTypeInfo(0).GetTensorTypeAndShapeInfo().GetShape();
        if (output_shape.size() != 2 || output_shape[1] != 19) {
            throw std::runtime_error("PP-Vehicle color output must contain 19 probabilities");
        }
    }

    VehicleColorConfig config;
    Ort::Env env;
    Ort::SessionOptions session_options;
    Ort::Session session;
    std::string input_name_storage;
    std::string output_name_storage;
    const char* input_name = nullptr;
    const char* output_name = nullptr;
    ClassifierTiming timing;
};

PpVehicleOnnxColorClassifier::PpVehicleOnnxColorClassifier(const VehicleColorConfig& config)
    : impl_(std::make_unique<Impl>(config)) {}

PpVehicleOnnxColorClassifier::~PpVehicleOnnxColorClassifier() = default;

ColorResult PpVehicleOnnxColorClassifier::classify(const cv::Mat& vehicle_roi) {
    if (vehicle_roi.empty() || vehicle_roi.type() != CV_8UC3) {
        throw std::invalid_argument("PpVehicleOnnxColorClassifier expects a non-empty CV_8UC3 ROI");
    }

    const auto preprocess_start = Clock::now();
    cv::Mat resized;
    cv::resize(vehicle_roi, resized,
        cv::Size(impl_->config.input_width, impl_->config.input_height), 0.0, 0.0, cv::INTER_LINEAR);

    const std::size_t plane = static_cast<std::size_t>(impl_->config.input_width) *
        static_cast<std::size_t>(impl_->config.input_height);
    std::vector<float> input(plane * 3U);
    constexpr std::array<float, 3> mean = {0.485F, 0.456F, 0.406F};
    constexpr std::array<float, 3> stddev = {0.229F, 0.224F, 0.225F};
    for (int y = 0; y < resized.rows; ++y) {
        const cv::Vec3b* row = resized.ptr<cv::Vec3b>(y);
        for (int x = 0; x < resized.cols; ++x) {
            const std::size_t offset = static_cast<std::size_t>(y) *
                static_cast<std::size_t>(resized.cols) + static_cast<std::size_t>(x);
            input[offset] = (static_cast<float>(row[x][2]) / 255.0F - mean[0]) / stddev[0];
            input[plane + offset] = (static_cast<float>(row[x][1]) / 255.0F - mean[1]) / stddev[1];
            input[plane * 2U + offset] = (static_cast<float>(row[x][0]) / 255.0F - mean[2]) / stddev[2];
        }
    }
    const std::array<std::int64_t, 4> input_shape = {
        1, 3, impl_->config.input_height, impl_->config.input_width};
    Ort::MemoryInfo memory_info = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    Ort::Value input_tensor = Ort::Value::CreateTensor<float>(
        memory_info, input.data(), input.size(), input_shape.data(), input_shape.size());
    const auto preprocess_end = Clock::now();

    const auto inference_start = Clock::now();
    auto outputs = impl_->session.Run(
        Ort::RunOptions{nullptr}, &impl_->input_name, &input_tensor, 1, &impl_->output_name, 1);
    const auto inference_end = Clock::now();

    const auto postprocess_start = Clock::now();
    const auto output_shape = outputs[0].GetTensorTypeAndShapeInfo().GetShape();
    if (output_shape.size() != 2 || output_shape[0] != 1 || output_shape[1] != 19) {
        throw std::runtime_error("Unexpected PP-Vehicle color output shape");
    }
    const float* probabilities = outputs[0].GetTensorData<float>();
    int best_index = 0;
    for (int index = 0; index < 10; ++index) {
        if (!std::isfinite(probabilities[index])) {
            throw std::runtime_error("PP-Vehicle color output contains a non-finite value");
        }
        if (probabilities[index] > probabilities[best_index]) {
            best_index = index;
        }
    }

    ColorResult result;
    result.model_color = kModelColors[static_cast<std::size_t>(best_index)];
    result.confidence = probabilities[best_index];
    result.color = result.confidence >= impl_->config.confidence
        ? kCanonicalColors[static_cast<std::size_t>(best_index)]
        : "other";
    result.primary_color = result.color;
    result.primary_confidence = result.confidence;
    const auto postprocess_end = Clock::now();

    impl_->timing.preprocess_ms = elapsed_ms(preprocess_start, preprocess_end);
    impl_->timing.inference_ms = elapsed_ms(inference_start, inference_end);
    impl_->timing.postprocess_ms = elapsed_ms(postprocess_start, postprocess_end);
    return result;
}

ClassifierTiming PpVehicleOnnxColorClassifier::last_timing() const {
    return impl_->timing;
}

}  // namespace vehicle_system
