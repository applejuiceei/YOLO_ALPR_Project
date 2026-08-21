#include "common/config.hpp"
#include "common/types.hpp"
#include "cropper/vehicle_cropper.hpp"
#include "detector/yolo11_onnx_vehicle_detector.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/videoio.hpp>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

bool is_vehicle(vehicle_system::ObjectType type) {
    return type == vehicle_system::ObjectType::Car ||
        type == vehicle_system::ObjectType::Bus ||
        type == vehicle_system::ObjectType::Truck ||
        type == vehicle_system::ObjectType::NonMotor;
}

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
    if (!cv::imencode(".jpg", image, bytes)) {
        throw std::runtime_error("Cannot encode ROI");
    }
    std::ofstream output(path, std::ios::binary);
    if (!output) {
        throw std::runtime_error("Cannot create ROI: " + path.u8string());
    }
    output.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
}

struct TestStats {
    std::uint64_t frames = 0;
    std::uint64_t detections = 0;
    std::uint64_t attempts = 0;
    std::uint64_t crops = 0;
    std::uint64_t rejected = 0;
    std::uint64_t saved = 0;
    double cropper_us = 0.0;
};

void process_frame(
    const cv::Mat& frame,
    std::uint64_t frame_id,
    std::uint64_t max_saves,
    const std::filesystem::path& output_dir,
    vehicle_system::Yolo11OnnxVehicleDetector& detector,
    const vehicle_system::VehicleCropper& cropper,
    TestStats& stats) {
    const auto detections = detector.detect(frame);
    stats.detections += detections.size();
    for (std::size_t index = 0; index < detections.size(); ++index) {
        if (!is_vehicle(detections[index].type)) {
            continue;
        }
        ++stats.attempts;
        const auto start = std::chrono::steady_clock::now();
        auto crop = cropper.crop(frame, detections[index]);
        stats.cropper_us += std::chrono::duration<double, std::micro>(
            std::chrono::steady_clock::now() - start).count();
        if (!crop.has_value()) {
            ++stats.rejected;
            continue;
        }
        ++stats.crops;
        if (stats.saved < max_saves) {
            std::ostringstream name;
            name << "frame_" << std::setw(6) << std::setfill('0') << frame_id
                 << "_crop_" << index << ".jpg";
            write_image(output_dir / name.str(), crop->roi);
            ++stats.saved;
        }
    }
    ++stats.frames;
}

int run_test(
    const std::filesystem::path& config_path,
    const std::string& mode,
    const std::filesystem::path& input_path,
    const std::filesystem::path& output_dir,
    int max_frames,
    std::uint64_t max_saves) {
    try {
        const auto config = vehicle_system::load_config(config_path);
        vehicle_system::Yolo11OnnxVehicleDetector detector(config.detector);
        vehicle_system::VehicleCropper cropper(config.cropper);
        TestStats stats;

        if (mode == "--image") {
            cv::Mat image = read_image(input_path);
            if (image.empty()) {
                throw std::runtime_error("Input image could not be decoded");
            }
            process_frame(image, 0, max_saves, output_dir, detector, cropper, stats);
        } else if (mode == "--video") {
            cv::VideoCapture capture(input_path.u8string());
            if (!capture.isOpened()) {
                throw std::runtime_error("Cannot open video: " + input_path.u8string());
            }
            cv::Mat frame;
            while ((max_frames <= 0 || stats.frames < static_cast<std::uint64_t>(max_frames)) && capture.read(frame)) {
                process_frame(frame, stats.frames, max_saves, output_dir, detector, cropper, stats);
            }
        } else {
            throw std::runtime_error("Mode must be --image or --video");
        }

        if (stats.frames == 0) {
            throw std::runtime_error("No input frames were processed");
        }
        if (stats.crops == 0) {
            throw std::runtime_error("No vehicle ROI was produced");
        }
        std::cout << "frames=" << stats.frames
                  << " detections=" << stats.detections
                  << " vehicle_attempts=" << stats.attempts
                  << " crops=" << stats.crops
                  << " rejected=" << stats.rejected
                  << " saved=" << stats.saved
                  << " cropper_mean_us=" << (stats.attempts == 0 ? 0.0 : stats.cropper_us / stats.attempts)
                  << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "ERROR: " << error.what() << '\n';
        return 1;
    }
}

}  // namespace

#ifdef _WIN32
int wmain(int argc, wchar_t** argv) {
    if (argc != 7) {
        std::cerr << "Usage: vehicle_cropper_pipeline_test CONFIG (--image|--video) INPUT OUTPUT_DIR MAX_FRAMES MAX_SAVES\n";
        return 2;
    }
    return run_test(
        std::filesystem::path(argv[1]),
        std::filesystem::path(argv[2]).u8string(),
        std::filesystem::path(argv[3]),
        std::filesystem::path(argv[4]),
        std::stoi(argv[5]),
        static_cast<std::uint64_t>(std::stoull(argv[6])));
}
#else
int main(int argc, char** argv) {
    if (argc != 7) {
        std::cerr << "Usage: vehicle_cropper_pipeline_test CONFIG (--image|--video) INPUT OUTPUT_DIR MAX_FRAMES MAX_SAVES\n";
        return 2;
    }
    return run_test(
        std::filesystem::u8path(argv[1]),
        argv[2],
        std::filesystem::u8path(argv[3]),
        std::filesystem::u8path(argv[4]),
        std::stoi(argv[5]),
        static_cast<std::uint64_t>(std::stoull(argv[6])));
}
#endif
