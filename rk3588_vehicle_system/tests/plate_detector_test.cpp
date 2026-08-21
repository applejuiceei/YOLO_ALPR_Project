#include "common/config.hpp"
#include "plate/plate_cropper.hpp"
#include "plate/yolo_obb_onnx_plate_detector.hpp"

#include <array>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <sstream>
#include <stdexcept>
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

void write_image(const std::filesystem::path& path, const cv::Mat& image) {
    std::filesystem::create_directories(path.parent_path());
    std::vector<unsigned char> bytes;
    if (!cv::imencode(path.extension().u8string(), image, bytes)) {
        throw std::runtime_error("Cannot encode output image");
    }
    std::ofstream output(path, std::ios::binary);
    output.write(reinterpret_cast<const char*>(bytes.data()),
        static_cast<std::streamsize>(bytes.size()));
}

int run_test(
    const std::filesystem::path& config_path,
    const std::filesystem::path& vehicle_roi_path,
    const std::filesystem::path& output_dir) {
    try {
        const vehicle_system::AppConfig config = vehicle_system::load_config(config_path);
        cv::Mat vehicle_roi = read_image(vehicle_roi_path);
        if (vehicle_roi.empty()) {
            throw std::runtime_error("Vehicle ROI could not be decoded");
        }

        vehicle_system::YoloObbOnnxPlateDetector detector(config.plate_detector);
        vehicle_system::PlateCropper cropper(config.plate_cropper);
        const std::vector<vehicle_system::PlateDetection> detections = detector.detect(vehicle_roi);
        const vehicle_system::DetectorTiming timing = detector.last_timing();
        std::filesystem::create_directories(output_dir);

        for (std::size_t index = 0; index < detections.size(); ++index) {
            const vehicle_system::PlateDetection& detection = detections[index];
            for (std::size_t corner = 0; corner < detection.corners.size(); ++corner) {
                cv::line(vehicle_roi, detection.corners[corner],
                    detection.corners[(corner + 1) % detection.corners.size()],
                    cv::Scalar(0, 255, 0), 2, cv::LINE_AA);
            }
            std::ostringstream label;
            label << "plate " << std::fixed << std::setprecision(2) << detection.confidence;
            cv::putText(vehicle_roi, label.str(), detection.bbox.tl() + cv::Point(0, -4),
                cv::FONT_HERSHEY_SIMPLEX, 0.6, cv::Scalar(0, 255, 0), 2, cv::LINE_AA);

            const auto crop = cropper.crop(read_image(vehicle_roi_path), detection);
            if (crop.has_value()) {
                std::ostringstream filename;
                filename << "plate_" << index << ".jpg";
                write_image(output_dir / filename.str(), crop->roi);
            }
            std::cout << label.str() << " bbox=" << detection.bbox
                      << " angle_rad=" << detection.angle_radians << '\n';
        }
        write_image(output_dir / "annotated.jpg", vehicle_roi);
        std::cout << "detections=" << detections.size()
                  << " preprocess_ms=" << timing.preprocess_ms
                  << " inference_ms=" << timing.inference_ms
                  << " postprocess_ms=" << timing.postprocess_ms << '\n';
        return detections.empty() ? 3 : 0;
    } catch (const std::exception& error) {
        std::cerr << "ERROR: " << error.what() << '\n';
        return 1;
    }
}

}  // namespace

#ifdef _WIN32
int wmain(int argc, wchar_t** argv) {
    if (argc != 4) {
        std::cerr << "Usage: plate_detector_test CONFIG VEHICLE_ROI OUTPUT_DIR\n";
        return 2;
    }
    return run_test(
        std::filesystem::path(argv[1]),
        std::filesystem::path(argv[2]),
        std::filesystem::path(argv[3]));
}
#else
int main(int argc, char** argv) {
    if (argc != 4) {
        std::cerr << "Usage: plate_detector_test CONFIG VEHICLE_ROI OUTPUT_DIR\n";
        return 2;
    }
    return run_test(
        std::filesystem::u8path(argv[1]),
        std::filesystem::u8path(argv[2]),
        std::filesystem::u8path(argv[3]));
}
#endif
