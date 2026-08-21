#include "common/config.hpp"
#include "plate/hsv_plate_color_classifier.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

void require(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

cv::Mat read_image(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("Cannot open image: " + path.u8string());
    }
    std::vector<unsigned char> bytes(
        (std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    return cv::imdecode(bytes, cv::IMREAD_COLOR);
}

void expect_color(
    vehicle_system::HsvPlateColorClassifier& classifier,
    const cv::Mat& image,
    const std::string& expected) {
    const vehicle_system::ColorResult result = classifier.classify(image);
    if (result.color != expected) {
        throw std::runtime_error(
            "Expected " + expected + ", got " + result.color +
            " (candidate=" + result.model_color + ")");
    }
    require(result.confidence >= 0.0F && result.confidence <= 1.0F,
        "confidence must be within [0, 1]");
}

int run_synthetic_tests() {
    vehicle_system::PlateColorConfig config;
    vehicle_system::HsvPlateColorClassifier classifier(config);

    expect_color(classifier, cv::Mat(96, 320, CV_8UC3, cv::Scalar(255, 0, 0)), "blue");
    expect_color(classifier, cv::Mat(96, 320, CV_8UC3, cv::Scalar(0, 255, 255)), "yellow");
    expect_color(classifier, cv::Mat(96, 320, CV_8UC3, cv::Scalar(0, 200, 0)), "green");
    expect_color(classifier, cv::Mat(96, 320, CV_8UC3, cv::Scalar(240, 240, 240)), "white");
    expect_color(classifier, cv::Mat(96, 320, CV_8UC3, cv::Scalar(20, 20, 20)), "black");
    expect_color(classifier, cv::Mat(96, 320, CV_8UC3, cv::Scalar(0, 0, 255)), "other");

    cv::Mat realistic_blue(96, 320, CV_8UC3, cv::Scalar(210, 80, 40));
    cv::putText(realistic_blue, "A12345", cv::Point(40, 68), cv::FONT_HERSHEY_SIMPLEX,
        1.5, cv::Scalar(245, 245, 245), 4, cv::LINE_AA);
    expect_color(classifier, realistic_blue, "blue");

    cv::Mat border_test(96, 320, CV_8UC3, cv::Scalar(0, 0, 255));
    cv::rectangle(border_test, cv::Rect(12, 6, 296, 84), cv::Scalar(255, 0, 0), cv::FILLED);
    expect_color(classifier, border_test, "blue");

    vehicle_system::PlateColorConfig ambiguous_config = config;
    ambiguous_config.min_dominance_margin = 0.10F;
    vehicle_system::HsvPlateColorClassifier ambiguous_classifier(ambiguous_config);
    cv::Mat ambiguous(96, 320, CV_8UC3, cv::Scalar(255, 0, 0));
    ambiguous(cv::Rect(160, 0, 160, 96)).setTo(cv::Scalar(0, 255, 255));
    expect_color(ambiguous_classifier, ambiguous, "other");

    bool rejected_empty = false;
    try {
        classifier.classify(cv::Mat());
    } catch (const std::invalid_argument&) {
        rejected_empty = true;
    }
    require(rejected_empty, "empty input must be rejected");

    bool rejected_type = false;
    try {
        classifier.classify(cv::Mat(96, 320, CV_8UC1, cv::Scalar(0)));
    } catch (const std::invalid_argument&) {
        rejected_type = true;
    }
    require(rejected_type, "non-BGR input must be rejected");

    bool rejected_overlap = false;
    try {
        vehicle_system::PlateColorConfig invalid = config;
        invalid.green_hue_max = invalid.blue_hue_min;
        vehicle_system::HsvPlateColorClassifier invalid_classifier(invalid);
    } catch (const std::invalid_argument&) {
        rejected_overlap = true;
    }
    require(rejected_overlap, "overlapping hue ranges must be rejected");

    constexpr int iterations = 1000;
    const auto start = std::chrono::steady_clock::now();
    for (int index = 0; index < iterations; ++index) {
        classifier.classify(realistic_blue);
    }
    const double elapsed_ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - start).count();
    std::cout << "Plate color tests passed; mean_ms=" << elapsed_ms / iterations << '\n';
    return 0;
}

int run_image_test(
    const std::filesystem::path& config_path,
    const std::filesystem::path& image_path,
    const std::string& expected) {
    const vehicle_system::AppConfig app_config = vehicle_system::load_config(config_path);
    vehicle_system::HsvPlateColorClassifier classifier(app_config.plate_color);
    const cv::Mat image = read_image(image_path);
    if (image.empty()) {
        throw std::runtime_error("Input image could not be decoded");
    }
    const vehicle_system::ColorResult result = classifier.classify(image);
    const vehicle_system::ClassifierTiming timing = classifier.last_timing();
    std::cout << "color=" << result.color
              << " candidate=" << result.model_color
              << " confidence=" << result.confidence
              << " secondary=" << result.secondary_color
              << " secondary_confidence=" << result.secondary_confidence
              << " total_ms=" << timing.total_ms() << '\n';
    if (!expected.empty() && result.color != expected) {
        throw std::runtime_error("Expected " + expected + ", got " + result.color);
    }
    return 0;
}

int dispatch(
    const std::filesystem::path& config_path,
    const std::filesystem::path& image_path,
    const std::string& expected,
    bool image_mode) {
    try {
        return image_mode ? run_image_test(config_path, image_path, expected) : run_synthetic_tests();
    } catch (const std::exception& error) {
        std::cerr << "Plate color test failed: " << error.what() << '\n';
        return 1;
    }
}

}  // namespace

#ifdef _WIN32
int wmain(int argc, wchar_t** argv) {
    if (argc == 1) {
        return dispatch({}, {}, {}, false);
    }
    if (argc != 3 && argc != 4) {
        std::cerr << "Usage: plate_color_classifier_test [CONFIG IMAGE [EXPECTED_COLOR]]\n";
        return 2;
    }
    return dispatch(std::filesystem::path(argv[1]), std::filesystem::path(argv[2]),
        argc == 4 ? std::filesystem::path(argv[3]).u8string() : std::string(), true);
}
#else
int main(int argc, char** argv) {
    if (argc == 1) {
        return dispatch({}, {}, {}, false);
    }
    if (argc != 3 && argc != 4) {
        std::cerr << "Usage: plate_color_classifier_test [CONFIG IMAGE [EXPECTED_COLOR]]\n";
        return 2;
    }
    return dispatch(std::filesystem::u8path(argv[1]), std::filesystem::u8path(argv[2]),
        argc == 4 ? argv[3] : std::string(), true);
}
#endif
