#include "cropper/vehicle_cropper.hpp"

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

vehicle_system::Detection detection(const cv::Rect& bbox) {
    vehicle_system::Detection value;
    value.bbox = bbox;
    value.type = vehicle_system::ObjectType::Car;
    return value;
}

}  // namespace

int main() {
    try {
        cv::Mat frame(100, 200, CV_8UC3, cv::Scalar(10, 20, 30));

        vehicle_system::VehicleCropperConfig default_config;
        default_config.min_width = 1;
        default_config.min_height = 1;
        vehicle_system::VehicleCropper shallow_cropper(default_config);
        const auto normal = shallow_cropper.crop(frame, detection({20, 30, 50, 40}));
        require(normal.has_value(), "normal crop was rejected");
        require(normal->source_bbox == cv::Rect(20, 30, 50, 40), "normal bbox changed");
        require(normal->roi.data == frame.ptr(30) + 20 * frame.elemSize(), "crop is not a shallow ROI");

        vehicle_system::VehicleCropperConfig expanded_config = default_config;
        expanded_config.expand_left = 0.10F;
        expanded_config.expand_right = 0.10F;
        expanded_config.expand_top = 0.25F;
        expanded_config.expand_bottom = 0.25F;
        vehicle_system::VehicleCropper expanded_cropper(expanded_config);
        const auto expanded = expanded_cropper.crop(frame, detection({20, 30, 50, 40}));
        require(expanded.has_value(), "expanded crop was rejected");
        require(expanded->source_bbox == cv::Rect(15, 20, 60, 60), "expanded bbox is incorrect");

        const auto clipped = shallow_cropper.crop(frame, detection({-10, -5, 30, 20}));
        require(clipped.has_value(), "clipped crop was rejected");
        require(clipped->source_bbox == cv::Rect(0, 0, 20, 15), "frame clipping is incorrect");

        vehicle_system::VehicleCropperConfig minimum_config = default_config;
        minimum_config.min_width = 32;
        minimum_config.min_height = 32;
        vehicle_system::VehicleCropper minimum_cropper(minimum_config);
        require(!minimum_cropper.crop(frame, detection({0, 0, 20, 20})).has_value(),
            "undersized crop was accepted");
        require(!minimum_cropper.crop(cv::Mat(), detection({0, 0, 50, 50})).has_value(),
            "empty frame was accepted");
        require(!minimum_cropper.crop(frame, detection({0, 0, 0, 50})).has_value(),
            "invalid bbox was accepted");
        require(!shallow_cropper.crop(frame, detection({std::numeric_limits<int>::max() - 5, 0, 20, 20})).has_value(),
            "overflow-prone bbox was accepted");

        vehicle_system::VehicleCropperConfig clone_config = default_config;
        clone_config.clone_output = true;
        vehicle_system::VehicleCropper clone_cropper(clone_config);
        const auto cloned = clone_cropper.crop(frame, detection({20, 30, 50, 40}));
        require(cloned.has_value(), "clone crop was rejected");
        require(cloned->roi.data != frame.ptr(30) + 20 * frame.elemSize(), "clone_output did not copy data");

        constexpr int iterations = 100000;
        std::uint64_t width_sum = 0;
        const auto start = std::chrono::steady_clock::now();
        for (int index = 0; index < iterations; ++index) {
            const auto crop = shallow_cropper.crop(frame, detection({20, 30, 50, 40}));
            width_sum += static_cast<std::uint64_t>(crop->roi.cols);
        }
        const double elapsed_us = std::chrono::duration<double, std::micro>(
            std::chrono::steady_clock::now() - start).count();
        require(width_sum == static_cast<std::uint64_t>(iterations) * 50U, "benchmark result mismatch");
        std::cout << "VehicleCropper tests passed; shallow_mean_us="
                  << elapsed_us / iterations << '\n';
        return EXIT_SUCCESS;
    } catch (const std::exception& error) {
        std::cerr << "VehicleCropper test failed: " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
