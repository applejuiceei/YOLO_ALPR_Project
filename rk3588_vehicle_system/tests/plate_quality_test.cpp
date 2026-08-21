#include "plate/opencv_plate_quality_evaluator.hpp"

#include <cmath>
#include <cstdint>
#include <iostream>
#include <opencv2/core.hpp>
#include <stdexcept>
#include <string>

namespace {

void require(bool condition, const std::string& message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

cv::Mat checkerboard(int width, int height, std::uint8_t low, std::uint8_t high) {
    cv::Mat image(height, width, CV_8UC3);
    for (int row = 0; row < height; ++row) {
        for (int column = 0; column < width; ++column) {
            const std::uint8_t value = ((row + column) % 2 == 0) ? low : high;
            image.at<cv::Vec3b>(row, column) = cv::Vec3b(value, value, value);
        }
    }
    return image;
}

}  // namespace

int main() {
    try {
        vehicle_system::PlateQualityConfig config;
        vehicle_system::OpenCvPlateQualityEvaluator evaluator(config);

        bool invalid_image_threw = false;
        try {
            static_cast<void>(evaluator.evaluate(cv::Mat()));
        } catch (const std::invalid_argument&) {
            invalid_image_threw = true;
        }
        require(invalid_image_threw, "empty input must throw");

        invalid_image_threw = false;
        try {
            static_cast<void>(evaluator.evaluate(cv::Mat(20, 64, CV_8UC1, cv::Scalar(127))));
        } catch (const std::invalid_argument&) {
            invalid_image_threw = true;
        }
        require(invalid_image_threw, "non-CV_8UC3 input must throw");

        bool invalid_config_threw = false;
        try {
            vehicle_system::PlateQualityConfig invalid_config = config;
            invalid_config.min_width = 0;
            vehicle_system::OpenCvPlateQualityEvaluator invalid_evaluator(invalid_config);
            static_cast<void>(invalid_evaluator);
        } catch (const std::invalid_argument&) {
            invalid_config_threw = true;
        }
        require(invalid_config_threw, "invalid config must throw");

        const vehicle_system::PlateQuality tiny = evaluator.evaluate(checkerboard(20, 7, 0, 255));
        require(!tiny.acceptable && tiny.rejection_reason == "size",
            "tiny high-frequency ROI must be rejected by the size gate");
        require(tiny.blur_score > config.min_blur_score,
            "tiny test must prove that a large Laplacian score cannot bypass size gating");

        const vehicle_system::PlateQuality flat = evaluator.evaluate(
            cv::Mat(20, 64, CV_8UC3, cv::Scalar(127, 127, 127)));
        require(!flat.acceptable && flat.rejection_reason == "blur",
            "flat ROI must be rejected as blurred");

        const vehicle_system::PlateQuality bright = evaluator.evaluate(checkerboard(64, 20, 246, 255));
        require(!bright.acceptable && bright.rejection_reason == "brightness",
            "overexposed sharp ROI must be rejected by brightness");

        const vehicle_system::PlateQuality low_contrast = evaluator.evaluate(
            checkerboard(64, 20, 120, 128));
        require(!low_contrast.acceptable && low_contrast.rejection_reason == "contrast",
            "low-contrast sharp ROI must be rejected by contrast");

        const vehicle_system::PlateQuality good = evaluator.evaluate(checkerboard(64, 20, 35, 220));
        require(good.acceptable, "well-exposed sharp ROI must be accepted");
        require(good.quality_score >= 0.0F && good.quality_score <= 1.0F,
            "quality score must be normalized");
        require(good.size_score == 1.0F, "target-sized ROI must have full size score");

        vehicle_system::PlateQualityConfig strict_config = config;
        strict_config.min_quality_score = 0.99F;
        vehicle_system::OpenCvPlateQualityEvaluator strict_evaluator(strict_config);
        const vehicle_system::PlateQuality strict = strict_evaluator.evaluate(checkerboard(32, 10, 35, 220));
        require(!strict.acceptable && strict.rejection_reason == "quality_score",
            "overall quality threshold must be enforced after hard gates");

        std::cout << "PlateQualityEvaluator tests passed; good_score=" << good.quality_score
                  << " blur=" << good.blur_score
                  << " brightness=" << good.brightness
                  << " contrast=" << good.contrast << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "PlateQualityEvaluator test failed: " << error.what() << '\n';
        return 1;
    }
}
