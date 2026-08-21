#include "common/config.hpp"
#include "plate/hyperlpr3_onnx_plate_recognizer.hpp"

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
    std::vector<unsigned char> bytes(
        (std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    return cv::imdecode(bytes, cv::IMREAD_COLOR);
}

int run_test(
    const std::filesystem::path& config_path,
    const std::filesystem::path& image_path,
    const std::string& expected_text) {
    try {
        const vehicle_system::AppConfig config = vehicle_system::load_config(config_path);
        vehicle_system::HyperLpr3OnnxPlateRecognizer recognizer(config.plate_recognizer);
        const cv::Mat image = read_image(image_path);
        if (image.empty()) {
            throw std::runtime_error("Input image could not be decoded");
        }
        const vehicle_system::PlateOCRResult result = recognizer.recognize(image);
        const vehicle_system::PlateRecognizerTiming timing = recognizer.last_timing();
        std::cout << "text=" << result.text
                  << " confidence=" << result.confidence
                  << " format_valid=" << result.format_valid
                  << " accepted=" << result.accepted
                  << " rejection=" << result.rejection_reason
                  << " preprocess_ms=" << timing.preprocess_ms
                  << " inference_ms=" << timing.inference_ms
                  << " decode_ms=" << timing.decode_ms << '\n';
        if (!expected_text.empty() && result.text != expected_text) {
            throw std::runtime_error(
                "Expected text " + expected_text + ", got " + result.text);
        }
        if (!expected_text.empty() && (!result.format_valid || !result.accepted)) {
            throw std::runtime_error("Expected reference plate must pass format and confidence filters");
        }

        bool rejected_empty = false;
        try {
            recognizer.recognize(cv::Mat());
        } catch (const std::invalid_argument&) {
            rejected_empty = true;
        }
        if (!rejected_empty) {
            throw std::runtime_error("Recognizer must reject an empty image");
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Plate recognizer test failed: " << error.what() << '\n';
        return 1;
    }
}

}  // namespace

#ifdef _WIN32
int wmain(int argc, wchar_t** argv) {
    if (argc != 3 && argc != 4) {
        std::cerr << "Usage: plate_recognizer_test CONFIG IMAGE [EXPECTED_TEXT]\n";
        return 2;
    }
    return run_test(std::filesystem::path(argv[1]), std::filesystem::path(argv[2]),
        argc == 4 ? std::filesystem::path(argv[3]).u8string() : std::string());
}
#else
int main(int argc, char** argv) {
    if (argc != 3 && argc != 4) {
        std::cerr << "Usage: plate_recognizer_test CONFIG IMAGE [EXPECTED_TEXT]\n";
        return 2;
    }
    return run_test(std::filesystem::u8path(argv[1]), std::filesystem::u8path(argv[2]),
        argc == 4 ? argv[3] : std::string());
}
#endif
