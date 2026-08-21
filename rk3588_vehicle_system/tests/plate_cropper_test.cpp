#include "plate/plate_cropper.hpp"

#include <chrono>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <opencv2/core.hpp>
#include <stdexcept>

namespace {

void require(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

vehicle_system::PlateDetection detection(const cv::Rect& bbox) {
    vehicle_system::PlateDetection value;
    value.bbox = bbox;
    value.corners = {
        cv::Point2f(static_cast<float>(bbox.x), static_cast<float>(bbox.y)),
        cv::Point2f(static_cast<float>(bbox.x + bbox.width), static_cast<float>(bbox.y)),
        cv::Point2f(static_cast<float>(bbox.x + bbox.width), static_cast<float>(bbox.y + bbox.height)),
        cv::Point2f(static_cast<float>(bbox.x), static_cast<float>(bbox.y + bbox.height))};
    value.confidence = 0.9F;
    return value;
}

}  // namespace

int main() {
    try {
        cv::Mat vehicle_roi(100, 200, CV_8UC3, cv::Scalar(10, 20, 30));

        vehicle_system::PlateCropperConfig default_config;
        default_config.min_width = 1;
        default_config.min_height = 1;
        vehicle_system::PlateCropper shallow_cropper(default_config);
        const auto normal = shallow_cropper.crop(vehicle_roi, detection({20, 30, 80, 20}));
        require(normal.has_value(), "normal plate crop was rejected");
        require(normal->source_bbox == cv::Rect(20, 30, 80, 20), "normal plate bbox changed");
        require(normal->roi.data == vehicle_roi.ptr(30) + 20 * vehicle_roi.elemSize(),
            "plate crop is not a shallow ROI");
        require(normal->corners[0] == cv::Point2f(0.0F, 0.0F) &&
            normal->corners[2] == cv::Point2f(80.0F, 20.0F),
            "plate corners were not translated into crop coordinates");

        vehicle_system::PlateCropperConfig expanded_config = default_config;
        expanded_config.expand_left = 0.10F;
        expanded_config.expand_right = 0.10F;
        expanded_config.expand_top = 0.25F;
        expanded_config.expand_bottom = 0.25F;
        vehicle_system::PlateCropper expanded_cropper(expanded_config);
        const auto expanded = expanded_cropper.crop(vehicle_roi, detection({20, 30, 80, 20}));
        require(expanded.has_value(), "expanded plate crop was rejected");
        require(expanded->source_bbox == cv::Rect(12, 25, 96, 30),
            "expanded plate bbox is incorrect");
        require(expanded->corners[0] == cv::Point2f(8.0F, 5.0F),
            "expanded plate corner translation is incorrect");

        const auto clipped = shallow_cropper.crop(vehicle_roi, detection({-10, -5, 30, 20}));
        require(clipped.has_value(), "clipped plate crop was rejected");
        require(clipped->source_bbox == cv::Rect(0, 0, 20, 15),
            "plate frame clipping is incorrect");

        vehicle_system::PlateCropperConfig minimum_config = default_config;
        minimum_config.min_width = 32;
        minimum_config.min_height = 12;
        vehicle_system::PlateCropper minimum_cropper(minimum_config);
        require(!minimum_cropper.crop(vehicle_roi, detection({0, 0, 20, 10})).has_value(),
            "undersized plate crop was accepted");
        require(!minimum_cropper.crop(cv::Mat(), detection({0, 0, 50, 20})).has_value(),
            "empty vehicle ROI was accepted");
        require(!minimum_cropper.crop(vehicle_roi, detection({0, 0, 0, 20})).has_value(),
            "invalid plate bbox was accepted");
        require(!shallow_cropper.crop(
            vehicle_roi,
            detection({std::numeric_limits<int>::max() - 5, 0, 20, 20})).has_value(),
            "overflow-prone plate bbox was accepted");

        vehicle_system::PlateCropperConfig clone_config = default_config;
        clone_config.clone_output = true;
        vehicle_system::PlateCropper clone_cropper(clone_config);
        const auto cloned = clone_cropper.crop(vehicle_roi, detection({20, 30, 80, 20}));
        require(cloned.has_value(), "cloned plate crop was rejected");
        require(cloned->roi.data != vehicle_roi.ptr(30) + 20 * vehicle_roi.elemSize(),
            "PlateCropper clone_output did not copy data");

        constexpr int iterations = 100000;
        std::uint64_t width_sum = 0;
        const auto start = std::chrono::steady_clock::now();
        for (int index = 0; index < iterations; ++index) {
            const auto crop = shallow_cropper.crop(vehicle_roi, detection({20, 30, 80, 20}));
            width_sum += static_cast<std::uint64_t>(crop->roi.cols);
        }
        const double elapsed_us = std::chrono::duration<double, std::micro>(
            std::chrono::steady_clock::now() - start).count();
        require(width_sum == static_cast<std::uint64_t>(iterations) * 80U,
            "plate cropper benchmark result mismatch");
        std::cout << "PlateCropper tests passed; shallow_mean_us="
                  << elapsed_us / iterations << '\n';
        return EXIT_SUCCESS;
    } catch (const std::exception& error) {
        std::cerr << "PlateCropper test failed: " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
