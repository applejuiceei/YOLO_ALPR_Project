#include "classifier/pp_vehicle_onnx_color_classifier.hpp"
#include "common/config.hpp"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <opencv2/imgcodecs.hpp>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

cv::Mat read_image(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("Cannot open image: " + path.u8string());
    }
    std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    return cv::imdecode(bytes, cv::IMREAD_COLOR);
}

int run_test(
    const std::filesystem::path& config_path,
    const std::filesystem::path& image_path,
    const std::string& expected_color) {
    try {
        const auto config = vehicle_system::load_config(config_path);
        cv::Mat image = read_image(image_path);
        if (image.empty()) {
            throw std::runtime_error("Input image could not be decoded");
        }
        vehicle_system::PpVehicleOnnxColorClassifier classifier(config.vehicle_color);
        const auto result = classifier.classify(image);
        const auto timing = classifier.last_timing();
        std::cout << "color=" << result.color
                  << " model_color=" << result.model_color
                  << " confidence=" << result.confidence
                  << " preprocess_ms=" << timing.preprocess_ms
                  << " inference_ms=" << timing.inference_ms
                  << " postprocess_ms=" << timing.postprocess_ms << '\n';
        if (!expected_color.empty() && result.color != expected_color) {
            throw std::runtime_error("Expected color " + expected_color + ", got " + result.color);
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "ERROR: " << error.what() << '\n';
        return 1;
    }
}

}  // namespace

#ifdef _WIN32
int wmain(int argc, wchar_t** argv) {
    if (argc != 3 && argc != 4) {
        std::cerr << "Usage: vehicle_color_classifier_test CONFIG IMAGE [EXPECTED_COLOR]\n";
        return 2;
    }
    return run_test(
        std::filesystem::path(argv[1]),
        std::filesystem::path(argv[2]),
        argc == 4 ? std::filesystem::path(argv[3]).u8string() : std::string());
}
#else
int main(int argc, char** argv) {
    if (argc != 3 && argc != 4) {
        std::cerr << "Usage: vehicle_color_classifier_test CONFIG IMAGE [EXPECTED_COLOR]\n";
        return 2;
    }
    return run_test(
        std::filesystem::u8path(argv[1]),
        std::filesystem::u8path(argv[2]),
        argc == 4 ? argv[3] : std::string());
}
#endif
