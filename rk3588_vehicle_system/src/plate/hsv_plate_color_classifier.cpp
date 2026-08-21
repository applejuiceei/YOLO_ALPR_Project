#include "plate/hsv_plate_color_classifier.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <opencv2/imgproc.hpp>
#include <stdexcept>
#include <utility>

namespace vehicle_system {
namespace {

using Clock = std::chrono::steady_clock;

double elapsed_ms(Clock::time_point start, Clock::time_point end) {
    return std::chrono::duration<double, std::milli>(end - start).count();
}

bool in_byte_range(int value) {
    return value >= 0 && value <= 255;
}

bool valid_hue_range(int minimum, int maximum) {
    return minimum >= 0 && maximum <= 179 && minimum <= maximum;
}

bool overlaps(int first_min, int first_max, int second_min, int second_max) {
    return first_min <= second_max && second_min <= first_max;
}

}  // namespace

HsvPlateColorClassifier::HsvPlateColorClassifier(PlateColorConfig config)
    : config_(std::move(config)) {
    if (config_.roi_margin_x_ratio < 0.0F || config_.roi_margin_x_ratio >= 0.5F ||
        config_.roi_margin_y_ratio < 0.0F || config_.roi_margin_y_ratio >= 0.5F ||
        !in_byte_range(config_.min_saturation) ||
        !in_byte_range(config_.chromatic_min_value) ||
        !in_byte_range(config_.white_max_saturation) ||
        !in_byte_range(config_.white_min_value) ||
        !in_byte_range(config_.black_max_value) ||
        config_.white_max_saturation >= config_.min_saturation ||
        config_.black_max_value >= config_.chromatic_min_value ||
        !valid_hue_range(config_.yellow_hue_min, config_.yellow_hue_max) ||
        !valid_hue_range(config_.green_hue_min, config_.green_hue_max) ||
        !valid_hue_range(config_.blue_hue_min, config_.blue_hue_max) ||
        overlaps(config_.yellow_hue_min, config_.yellow_hue_max,
            config_.green_hue_min, config_.green_hue_max) ||
        overlaps(config_.yellow_hue_min, config_.yellow_hue_max,
            config_.blue_hue_min, config_.blue_hue_max) ||
        overlaps(config_.green_hue_min, config_.green_hue_max,
            config_.blue_hue_min, config_.blue_hue_max) ||
        config_.min_coverage < 0.0F || config_.min_coverage > 1.0F ||
        config_.min_dominance_margin < 0.0F || config_.min_dominance_margin > 1.0F) {
        throw std::invalid_argument("Invalid HsvPlateColorClassifier configuration");
    }
}

ColorResult HsvPlateColorClassifier::classify(const cv::Mat& plate_roi) {
    if (plate_roi.empty() || plate_roi.type() != CV_8UC3) {
        throw std::invalid_argument(
            "HsvPlateColorClassifier expects a non-empty CV_8UC3 plate ROI");
    }

    const auto preprocess_start = Clock::now();
    const int margin_x = std::min(
        static_cast<int>(std::floor(static_cast<float>(plate_roi.cols) *
            config_.roi_margin_x_ratio)),
        std::max(0, (plate_roi.cols - 1) / 2));
    const int margin_y = std::min(
        static_cast<int>(std::floor(static_cast<float>(plate_roi.rows) *
            config_.roi_margin_y_ratio)),
        std::max(0, (plate_roi.rows - 1) / 2));
    const cv::Rect interior(
        margin_x, margin_y, plate_roi.cols - margin_x * 2, plate_roi.rows - margin_y * 2);
    cv::Mat hsv;
    cv::cvtColor(plate_roi(interior), hsv, cv::COLOR_BGR2HSV);
    const auto preprocess_end = Clock::now();

    const auto postprocess_start = Clock::now();
    constexpr std::size_t kYellow = 0;
    constexpr std::size_t kGreen = 1;
    constexpr std::size_t kBlue = 2;
    constexpr std::size_t kWhite = 3;
    constexpr std::size_t kBlack = 4;
    constexpr std::array<const char*, 5> labels = {
        "yellow", "green", "blue", "white", "black"};
    std::array<std::uint64_t, labels.size()> counts{};

    for (int row = 0; row < hsv.rows; ++row) {
        const cv::Vec3b* pixels = hsv.ptr<cv::Vec3b>(row);
        for (int column = 0; column < hsv.cols; ++column) {
            const int hue = pixels[column][0];
            const int saturation = pixels[column][1];
            const int value = pixels[column][2];
            if (value <= config_.black_max_value) {
                ++counts[kBlack];
                continue;
            }
            if (saturation <= config_.white_max_saturation &&
                value >= config_.white_min_value) {
                ++counts[kWhite];
                continue;
            }
            if (saturation < config_.min_saturation ||
                value < config_.chromatic_min_value) {
                continue;
            }
            if (hue >= config_.yellow_hue_min && hue <= config_.yellow_hue_max) {
                ++counts[kYellow];
            } else if (hue >= config_.green_hue_min && hue <= config_.green_hue_max) {
                ++counts[kGreen];
            } else if (hue >= config_.blue_hue_min && hue <= config_.blue_hue_max) {
                ++counts[kBlue];
            }
        }
    }

    const float pixel_count = static_cast<float>(hsv.total());
    std::array<float, labels.size()> coverage{};
    for (std::size_t index = 0; index < coverage.size(); ++index) {
        coverage[index] = static_cast<float>(counts[index]) / pixel_count;
    }
    std::array<std::size_t, labels.size()> order = {0, 1, 2, 3, 4};
    std::sort(order.begin(), order.end(), [&](std::size_t left, std::size_t right) {
        if (coverage[left] == coverage[right]) {
            return left < right;
        }
        return coverage[left] > coverage[right];
    });
    const std::size_t best = order[0];
    const std::size_t second = order[1];
    const float best_coverage = coverage[best];
    const float dominance_margin = best_coverage - coverage[second];
    const bool accepted = best_coverage >= config_.min_coverage &&
        dominance_margin >= config_.min_dominance_margin;

    ColorResult result;
    result.model_color = best_coverage > 0.0F ? labels[best] : "other";
    result.color = accepted ? labels[best] : "other";
    result.confidence = accepted ? best_coverage : std::clamp(1.0F - best_coverage, 0.0F, 1.0F);
    result.primary_color = result.color;
    result.primary_confidence = result.confidence;
    if (coverage[second] > 0.0F) {
        result.secondary_color = labels[second];
        result.secondary_confidence = coverage[second];
    }
    const auto postprocess_end = Clock::now();

    timing_.preprocess_ms = elapsed_ms(preprocess_start, preprocess_end);
    timing_.inference_ms = 0.0;
    timing_.postprocess_ms = elapsed_ms(postprocess_start, postprocess_end);
    return result;
}

ClassifierTiming HsvPlateColorClassifier::last_timing() const {
    return timing_;
}

}  // namespace vehicle_system
