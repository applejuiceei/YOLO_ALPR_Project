#include "common/config.hpp"
#include "common/types.hpp"
#include "detector/yolo11_onnx_vehicle_detector.hpp"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <stdexcept>
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

void write_image(const std::filesystem::path& path, const cv::Mat& image) {
    std::filesystem::create_directories(path.parent_path());
    std::vector<unsigned char> bytes;
    if (!cv::imencode(path.extension().u8string(), image, bytes)) {
        throw std::runtime_error("Cannot encode output image");
    }
    std::ofstream output(path, std::ios::binary);
    output.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
}

}  // namespace

int run_test(
    const std::filesystem::path& config_path,
    const std::filesystem::path& image_path,
    const std::filesystem::path& output_path) {
    try {
        const vehicle_system::AppConfig config = vehicle_system::load_config(config_path);
        cv::Mat image = read_image(image_path);
        if (image.empty()) {
            throw std::runtime_error("Input image could not be decoded");
        }
        vehicle_system::Yolo11OnnxVehicleDetector detector(config.detector);
        const std::vector<vehicle_system::Detection> detections = detector.detect(image);
        const vehicle_system::DetectorTiming timing = detector.last_timing();
        for (const auto& detection : detections) {
            cv::rectangle(image, detection.bbox, cv::Scalar(0, 255, 0), 2);
            const std::string label = std::string(vehicle_system::object_type_name(detection.type)) + " " +
                cv::format("%.2f", detection.confidence);
            cv::putText(image, label, detection.bbox.tl() + cv::Point(0, -4),
                cv::FONT_HERSHEY_SIMPLEX, 0.6, cv::Scalar(0, 255, 0), 2);
            std::cout << label << " bbox=" << detection.bbox << '\n';
        }
        write_image(output_path, image);
        std::cout << "detections=" << detections.size()
                  << " preprocess_ms=" << timing.preprocess_ms
                  << " inference_ms=" << timing.inference_ms
                  << " postprocess_ms=" << timing.postprocess_ms << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "ERROR: " << error.what() << '\n';
        return 1;
    }
}

#ifdef _WIN32
int wmain(int argc, wchar_t** argv) {
    if (argc != 4) {
        std::cerr << "Usage: vehicle_detector_test CONFIG IMAGE OUTPUT\n";
        return 2;
    }
    return run_test(std::filesystem::path(argv[1]), std::filesystem::path(argv[2]), std::filesystem::path(argv[3]));
}
#else
int main(int argc, char** argv) {
    if (argc != 4) {
        std::cerr << "Usage: vehicle_detector_test CONFIG IMAGE OUTPUT\n";
        return 2;
    }
    return run_test(std::filesystem::u8path(argv[1]), std::filesystem::u8path(argv[2]), std::filesystem::u8path(argv[3]));
}
#endif
