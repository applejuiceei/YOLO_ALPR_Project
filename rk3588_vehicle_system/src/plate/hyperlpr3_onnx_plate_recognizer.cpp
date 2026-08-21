#include "plate/hyperlpr3_onnx_plate_recognizer.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <numeric>
#include <onnxruntime_cxx_api.h>
#include <opencv2/imgproc.hpp>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

namespace vehicle_system {
namespace {

using Clock = std::chrono::steady_clock;

double elapsed_ms(Clock::time_point start, Clock::time_point end) {
    return std::chrono::duration<double, std::milli>(end - start).count();
}

const std::vector<std::string>& hyperlpr3_tokens() {
    static const std::vector<std::string> tokens = {
        "blank", "'", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
        "A", "B", "C", "D", "E", "F", "G", "H", "J", "K", "L", "M", "N",
        "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
        "云", "京", "冀", "吉", "学", "宁", "川", "挂", "新", "晋", "桂", "民",
        "沪", "津", "浙", "渝", "港", "湘", "琼", "甘", "皖", "粤", "航", "苏",
        "蒙", "藏", "警", "豫", "贵", "赣", "辽", "鄂", "闽", "陕", "青", "鲁",
        "黑", "领", "使", "澳"};
    return tokens;
}

bool is_ascii_digit(const std::string& token) {
    return token.size() == 1 && token[0] >= '0' && token[0] <= '9';
}

bool is_ascii_upper(const std::string& token) {
    return token.size() == 1 && token[0] >= 'A' && token[0] <= 'Z';
}

bool is_standard_plate_format(const std::vector<std::string>& decoded_tokens) {
    static const std::unordered_set<std::string> provinces = {
        "京", "津", "沪", "渝", "冀", "豫", "云", "辽", "黑", "湘", "皖",
        "鲁", "新", "苏", "浙", "赣", "鄂", "桂", "甘", "晋", "蒙", "陕",
        "吉", "闽", "贵", "粤", "青", "藏", "川", "宁", "琼"};
    if (decoded_tokens.size() != 7 && decoded_tokens.size() != 8) {
        return false;
    }
    if (provinces.count(decoded_tokens[0]) == 0 || !is_ascii_upper(decoded_tokens[1])) {
        return false;
    }
    return std::all_of(decoded_tokens.begin() + 2, decoded_tokens.end(),
        [](const std::string& token) {
            return is_ascii_digit(token) || is_ascii_upper(token);
        });
}

}  // namespace

struct HyperLpr3OnnxPlateRecognizer::Impl {
    explicit Impl(const PlateRecognizerConfig& recognizer_config)
        : config(recognizer_config),
          env(ORT_LOGGING_LEVEL_ERROR, "hyperlpr3-recognition"),
          session_options(),
          session(nullptr) {
        if (!std::filesystem::exists(config.model_path)) {
            throw std::runtime_error(
                "HyperLPR3 recognition model does not exist: " + config.model_path.u8string());
        }
        if (config.input_width <= 0 || config.input_height <= 0 ||
            config.input_color_order != "bgr" ||
            config.min_confidence < 0.0F || config.min_confidence > 1.0F ||
            config.min_text_length <= 0 || config.max_text_length < config.min_text_length ||
            config.intra_op_threads <= 0 || config.warmup_runs < 0) {
            throw std::invalid_argument("Invalid HyperLPR3 recognizer configuration");
        }
        if (hyperlpr3_tokens().size() != 77U) {
            throw std::logic_error("HyperLPR3 token table must contain 77 entries including blank");
        }

        session_options.SetIntraOpNumThreads(config.intra_op_threads);
        session_options.SetInterOpNumThreads(1);
        session_options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
        session = Ort::Session(env, config.model_path.c_str(), session_options);
        if (session.GetInputCount() != 1 || session.GetOutputCount() != 1) {
            throw std::runtime_error("HyperLPR3 recognizer must have one runtime input and one output");
        }

        Ort::AllocatorWithDefaultOptions allocator;
        auto input_name_value = session.GetInputNameAllocated(0, allocator);
        auto output_name_value = session.GetOutputNameAllocated(0, allocator);
        input_name_storage = input_name_value.get();
        output_name_storage = output_name_value.get();
        input_name = input_name_storage.c_str();
        output_name = output_name_storage.c_str();

        const auto input_info = session.GetInputTypeInfo(0).GetTensorTypeAndShapeInfo();
        const auto input_shape = input_info.GetShape();
        if (input_info.GetElementType() != ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT ||
            input_shape.size() != 4 || input_shape[0] != 1 || input_shape[1] != 3 ||
            input_shape[2] != config.input_height || input_shape[3] != config.input_width) {
            throw std::runtime_error("HyperLPR3 input must be float32 [1,3,48,160]");
        }
        const auto output_info = session.GetOutputTypeInfo(0).GetTensorTypeAndShapeInfo();
        const auto output_shape = output_info.GetShape();
        if (output_info.GetElementType() != ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT ||
            output_shape.size() != 3 || output_shape[0] != 1 ||
            output_shape[1] <= 0 ||
            output_shape[2] < static_cast<std::int64_t>(hyperlpr3_tokens().size())) {
            throw std::runtime_error("Unexpected HyperLPR3 output protocol");
        }
        time_steps = static_cast<std::size_t>(output_shape[1]);
        class_count = static_cast<std::size_t>(output_shape[2]);

        std::vector<float> zeros(static_cast<std::size_t>(config.input_width) *
            static_cast<std::size_t>(config.input_height) * 3U, 0.0F);
        for (int run = 0; run < config.warmup_runs; ++run) {
            run_session(zeros);
        }
    }

    std::vector<Ort::Value> run_session(std::vector<float>& input) {
        const std::array<std::int64_t, 4> input_shape = {
            1, 3, config.input_height, config.input_width};
        Ort::MemoryInfo memory_info =
            Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
        Ort::Value tensor = Ort::Value::CreateTensor<float>(memory_info,
            input.data(), input.size(), input_shape.data(), input_shape.size());
        return session.Run(Ort::RunOptions{nullptr}, &input_name, &tensor, 1, &output_name, 1);
    }

    PlateRecognizerConfig config;
    Ort::Env env;
    Ort::SessionOptions session_options;
    Ort::Session session;
    std::string input_name_storage;
    std::string output_name_storage;
    const char* input_name = nullptr;
    const char* output_name = nullptr;
    std::size_t time_steps = 0;
    std::size_t class_count = 0;
    PlateRecognizerTiming timing;
};

HyperLpr3OnnxPlateRecognizer::HyperLpr3OnnxPlateRecognizer(
    const PlateRecognizerConfig& config)
    : impl_(std::make_unique<Impl>(config)) {}

HyperLpr3OnnxPlateRecognizer::~HyperLpr3OnnxPlateRecognizer() = default;

PlateOCRResult HyperLpr3OnnxPlateRecognizer::recognize(const cv::Mat& plate_roi) {
    if (plate_roi.empty() || plate_roi.type() != CV_8UC3) {
        throw std::invalid_argument(
            "HyperLpr3OnnxPlateRecognizer expects a non-empty CV_8UC3 plate ROI");
    }

    const auto preprocess_start = Clock::now();
    const float ratio = static_cast<float>(plate_roi.cols) /
        static_cast<float>(plate_roi.rows);
    const int resized_width = std::clamp(
        static_cast<int>(std::ceil(static_cast<float>(impl_->config.input_height) * ratio)),
        impl_->config.input_height, impl_->config.input_width);
    cv::Mat resized;
    cv::resize(plate_roi, resized,
        cv::Size(resized_width, impl_->config.input_height), 0.0, 0.0, cv::INTER_LINEAR);

    const std::size_t plane = static_cast<std::size_t>(impl_->config.input_width) *
        static_cast<std::size_t>(impl_->config.input_height);
    std::vector<float> input(plane * 3U, 0.0F);
    for (int row = 0; row < resized.rows; ++row) {
        const cv::Vec3b* pixels = resized.ptr<cv::Vec3b>(row);
        for (int column = 0; column < resized.cols; ++column) {
            const std::size_t offset = static_cast<std::size_t>(row) *
                static_cast<std::size_t>(impl_->config.input_width) +
                static_cast<std::size_t>(column);
            for (std::size_t channel = 0; channel < 3U; ++channel) {
                input[channel * plane + offset] =
                    (static_cast<float>(pixels[column][static_cast<int>(channel)]) - 127.5F) /
                    127.5F;
            }
        }
    }
    const auto preprocess_end = Clock::now();

    const auto inference_start = Clock::now();
    std::vector<Ort::Value> outputs = impl_->run_session(input);
    const auto inference_end = Clock::now();

    const auto decode_start = Clock::now();
    const auto output_shape = outputs[0].GetTensorTypeAndShapeInfo().GetShape();
    if (output_shape.size() != 3 || output_shape[0] != 1 ||
        static_cast<std::size_t>(output_shape[1]) != impl_->time_steps ||
        static_cast<std::size_t>(output_shape[2]) != impl_->class_count) {
        throw std::runtime_error("HyperLPR3 output shape changed during inference");
    }
    const float* probabilities = outputs[0].GetTensorData<float>();
    const auto& tokens = hyperlpr3_tokens();
    std::vector<std::string> decoded_tokens;
    std::vector<float> decoded_confidences;
    std::size_t previous_index = impl_->class_count;
    bool unknown_token = false;
    for (std::size_t step = 0; step < impl_->time_steps; ++step) {
        const float* row = probabilities + step * impl_->class_count;
        std::size_t best_index = 0;
        float best_probability = row[0];
        if (!std::isfinite(best_probability)) {
            throw std::runtime_error("HyperLPR3 output contains a non-finite value");
        }
        for (std::size_t index = 1; index < impl_->class_count; ++index) {
            if (!std::isfinite(row[index])) {
                throw std::runtime_error("HyperLPR3 output contains a non-finite value");
            }
            if (row[index] > best_probability) {
                best_probability = row[index];
                best_index = index;
            }
        }
        const bool duplicate = step > 0 && best_index == previous_index;
        previous_index = best_index;
        if (best_index == 0 || duplicate) {
            continue;
        }
        if (best_index >= tokens.size()) {
            unknown_token = true;
            continue;
        }
        decoded_tokens.push_back(tokens[best_index]);
        decoded_confidences.push_back(best_probability);
    }

    PlateOCRResult result;
    result.text = std::accumulate(decoded_tokens.begin(), decoded_tokens.end(), std::string());
    if (!decoded_confidences.empty()) {
        result.confidence = std::accumulate(
            decoded_confidences.begin(), decoded_confidences.end(), 0.0F) /
            static_cast<float>(decoded_confidences.size());
    }
    const bool length_valid =
        static_cast<int>(decoded_tokens.size()) >= impl_->config.min_text_length &&
        static_cast<int>(decoded_tokens.size()) <= impl_->config.max_text_length;
    result.format_valid = length_valid &&
        (!impl_->config.require_standard_format || is_standard_plate_format(decoded_tokens));
    if (result.text.empty()) {
        result.rejection_reason = "empty";
    } else if (unknown_token) {
        result.rejection_reason = "unknown_token";
    } else if (!result.format_valid) {
        result.rejection_reason = "format";
    } else if (result.confidence < impl_->config.min_confidence) {
        result.rejection_reason = "confidence";
    } else {
        result.accepted = true;
    }
    const auto decode_end = Clock::now();

    impl_->timing.preprocess_ms = elapsed_ms(preprocess_start, preprocess_end);
    impl_->timing.inference_ms = elapsed_ms(inference_start, inference_end);
    impl_->timing.decode_ms = elapsed_ms(decode_start, decode_end);
    return result;
}

PlateRecognizerTiming HyperLpr3OnnxPlateRecognizer::last_timing() const {
    return impl_->timing;
}

}  // namespace vehicle_system
