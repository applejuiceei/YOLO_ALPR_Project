#include "plate/opencv_plate_rectifier.hpp"

#include <chrono>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <opencv2/imgproc.hpp>
#include <stdexcept>
#include <string>

namespace {

void require(bool condition, const std::string& message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

vehicle_system::PlateCrop make_crop(
    cv::Mat image,
    const std::array<cv::Point2f, 4>& corners) {
    return vehicle_system::PlateCrop{
        cv::Rect(0, 0, image.cols, image.rows), corners, std::move(image)};
}

cv::Mat reference_plate() {
    cv::Mat image(48, 160, CV_8UC3, cv::Scalar(210, 90, 20));
    cv::rectangle(image, cv::Rect(0, 0, 160, 48), cv::Scalar(255, 255, 255), 2);
    cv::rectangle(image, cv::Rect(8, 8, 28, 32), cv::Scalar(20, 220, 20), cv::FILLED);
    cv::rectangle(image, cv::Rect(124, 8, 28, 32), cv::Scalar(20, 20, 230), cv::FILLED);
    cv::putText(image, "A12345", cv::Point(40, 34), cv::FONT_HERSHEY_SIMPLEX,
        0.75, cv::Scalar(255, 255, 255), 2, cv::LINE_AA);
    return image;
}

}  // namespace

int main() {
    try {
        vehicle_system::PlateRectifierConfig config;
        vehicle_system::OpenCvPlateRectifier rectifier(config);

        bool invalid_config_threw = false;
        try {
            vehicle_system::PlateRectifierConfig invalid = config;
            invalid.mode = "unknown";
            vehicle_system::OpenCvPlateRectifier invalid_rectifier(invalid);
            static_cast<void>(invalid_rectifier);
        } catch (const std::invalid_argument&) {
            invalid_config_threw = true;
        }
        require(invalid_config_threw, "invalid mode must throw");
        invalid_config_threw = false;
        try {
            vehicle_system::PlateRectifierConfig invalid = config;
            invalid.output_width = 1;
            vehicle_system::OpenCvPlateRectifier invalid_rectifier(invalid);
            static_cast<void>(invalid_rectifier);
        } catch (const std::invalid_argument&) {
            invalid_config_threw = true;
        }
        require(invalid_config_threw, "degenerate output size must throw");
        require(!rectifier.rectify(vehicle_system::PlateCrop{}).has_value(),
            "empty plate crop must be rejected");

        const cv::Mat source = reference_plate();
        const std::array<cv::Point2f, 4> rectangle = {
            cv::Point2f(0.0F, 0.0F), cv::Point2f(160.0F, 0.0F),
            cv::Point2f(160.0F, 48.0F), cv::Point2f(0.0F, 48.0F)};
        vehicle_system::PlateRectifierConfig resize_config = config;
        resize_config.mode = "resize";
        vehicle_system::OpenCvPlateRectifier resize_rectifier(resize_config);
        const auto resized = resize_rectifier.rectify(make_crop(source.clone(), rectangle));
        require(resized.has_value(), "resize baseline failed");
        require(resized->image.size() == cv::Size(320, 96), "resize output size is wrong");
        require(resized->method == vehicle_system::PlateRectificationMethod::Resize,
            "resize method was not reported");

        const std::array<cv::Point2f, 4> source_corners = {
            cv::Point2f(0.0F, 0.0F), cv::Point2f(159.0F, 0.0F),
            cv::Point2f(159.0F, 47.0F), cv::Point2f(0.0F, 47.0F)};
        const std::array<cv::Point2f, 4> projected_corners = {
            cv::Point2f(28.0F, 24.0F), cv::Point2f(214.0F, 14.0F),
            cv::Point2f(198.0F, 101.0F), cv::Point2f(43.0F, 108.0F)};
        cv::Mat canvas(124, 244, CV_8UC3, cv::Scalar(0, 0, 0));
        const cv::Mat projection = cv::getPerspectiveTransform(
            source_corners.data(), projected_corners.data());
        cv::warpPerspective(source, canvas, projection, canvas.size(),
            cv::INTER_LINEAR, cv::BORDER_CONSTANT);
        const std::array<cv::Point2f, 4> shuffled = {
            projected_corners[2], projected_corners[0],
            projected_corners[3], projected_corners[1]};
        const auto perspective = rectifier.rectify(make_crop(canvas, shuffled));
        require(perspective.has_value(), "valid perspective crop failed");
        require(perspective->method == vehicle_system::PlateRectificationMethod::Perspective,
            "perspective method was not reported");
        require(perspective->image.size() == cv::Size(320, 96),
            "perspective output size is wrong");
        cv::Mat expected;
        cv::resize(source, expected, cv::Size(320, 96), 0.0, 0.0, cv::INTER_LINEAR);
        cv::Mat difference;
        cv::absdiff(expected, perspective->image, difference);
        const cv::Scalar mean_difference = cv::mean(difference);
        const double mean_absolute_error =
            (mean_difference[0] + mean_difference[1] + mean_difference[2]) / 3.0;
        require(mean_absolute_error < 18.0,
            "perspective output differs excessively from the reference plate");

        const std::array<cv::Point2f, 4> degenerate = {
            cv::Point2f(5.0F, 5.0F), cv::Point2f(5.0F, 5.0F),
            cv::Point2f(20.0F, 10.0F), cv::Point2f(30.0F, 15.0F)};
        const auto fallback = rectifier.rectify(make_crop(source.clone(), degenerate));
        require(fallback.has_value() &&
            fallback->method == vehicle_system::PlateRectificationMethod::ResizeFallback,
            "invalid geometry must use configured resize fallback");

        vehicle_system::PlateRectifierConfig strict_config = config;
        strict_config.fallback_to_resize = false;
        vehicle_system::OpenCvPlateRectifier strict_rectifier(strict_config);
        require(!strict_rectifier.rectify(make_crop(source.clone(), degenerate)).has_value(),
            "invalid geometry must fail when fallback is disabled");
        std::array<cv::Point2f, 4> non_finite = rectangle;
        non_finite[0].x = std::numeric_limits<float>::quiet_NaN();
        require(!strict_rectifier.rectify(make_crop(source.clone(), non_finite)).has_value(),
            "non-finite corner must be rejected");

        constexpr int iterations = 1000;
        double pixel_sum = 0.0;
        const auto benchmark_start = std::chrono::steady_clock::now();
        for (int iteration = 0; iteration < iterations; ++iteration) {
            const auto output = rectifier.rectify(make_crop(source, rectangle));
            require(output.has_value(), "benchmark rectification failed");
            pixel_sum += output->image.at<cv::Vec3b>(48, 160)[0];
        }
        const double elapsed_ms = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - benchmark_start).count();
        require(pixel_sum > 0.0, "benchmark output was not consumed");
        std::cout << "PlateRectifier tests passed; perspective_mae=" << mean_absolute_error
                  << " mean_ms=" << elapsed_ms / iterations << '\n';
        return EXIT_SUCCESS;
    } catch (const std::exception& error) {
        std::cerr << "PlateRectifier test failed: " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
