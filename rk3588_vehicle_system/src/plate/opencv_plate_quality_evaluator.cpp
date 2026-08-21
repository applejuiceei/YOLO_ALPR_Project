#include "plate/opencv_plate_quality_evaluator.hpp"

#include <algorithm>
#include <cmath>
#include <opencv2/imgproc.hpp>
#include <stdexcept>
#include <utility>

namespace vehicle_system {

OpenCvPlateQualityEvaluator::OpenCvPlateQualityEvaluator(PlateQualityConfig config)
    : config_(std::move(config)) {
    const bool dimensions_valid = config_.min_width > 0 && config_.min_height > 0 &&
        config_.target_width >= config_.min_width && config_.target_height >= config_.min_height;
    const bool thresholds_finite = std::isfinite(config_.min_blur_score) &&
        std::isfinite(config_.min_brightness) && std::isfinite(config_.max_brightness) &&
        std::isfinite(config_.target_brightness) && std::isfinite(config_.min_contrast) &&
        std::isfinite(config_.sharpness_reference) && std::isfinite(config_.contrast_reference) &&
        std::isfinite(config_.min_quality_score);
    if (!dimensions_valid || !thresholds_finite || config_.min_blur_score < 0.0F ||
        config_.min_brightness < 0.0F || config_.max_brightness > 255.0F ||
        config_.min_brightness >= config_.max_brightness ||
        config_.target_brightness < config_.min_brightness ||
        config_.target_brightness > config_.max_brightness ||
        config_.min_contrast < 0.0F || config_.sharpness_reference <= 0.0F ||
        config_.contrast_reference <= 0.0F || config_.min_quality_score < 0.0F ||
        config_.min_quality_score > 1.0F) {
        throw std::invalid_argument("Invalid PlateQualityEvaluator thresholds");
    }
    if (!std::isfinite(config_.size_weight) || !std::isfinite(config_.sharpness_weight) ||
        !std::isfinite(config_.exposure_weight) || !std::isfinite(config_.contrast_weight) ||
        config_.size_weight < 0.0F || config_.sharpness_weight < 0.0F ||
        config_.exposure_weight < 0.0F || config_.contrast_weight < 0.0F) {
        throw std::invalid_argument("PlateQualityEvaluator weights must be finite and non-negative");
    }
    weight_sum_ = config_.size_weight + config_.sharpness_weight +
        config_.exposure_weight + config_.contrast_weight;
    if (weight_sum_ <= 0.0F) {
        throw std::invalid_argument("PlateQualityEvaluator weight sum must be positive");
    }
}

PlateQuality OpenCvPlateQualityEvaluator::evaluate(const cv::Mat& plate_roi) const {
    if (plate_roi.empty() || plate_roi.type() != CV_8UC3) {
        throw std::invalid_argument(
            "OpenCvPlateQualityEvaluator expects a non-empty CV_8UC3 plate ROI");
    }

    cv::Mat gray;
    cv::cvtColor(plate_roi, gray, cv::COLOR_BGR2GRAY);
    cv::Mat laplacian;
    cv::Laplacian(gray, laplacian, CV_64F);
    cv::Scalar mean;
    cv::Scalar standard_deviation;
    cv::meanStdDev(gray, mean, standard_deviation);
    cv::Scalar laplacian_mean;
    cv::Scalar laplacian_standard_deviation;
    cv::meanStdDev(laplacian, laplacian_mean, laplacian_standard_deviation);

    PlateQuality result;
    result.blur_score = static_cast<float>(
        laplacian_standard_deviation[0] * laplacian_standard_deviation[0]);
    result.brightness = static_cast<float>(mean[0]);
    result.contrast = static_cast<float>(standard_deviation[0]);
    result.size_score = std::clamp(std::min(
        static_cast<float>(plate_roi.cols) / static_cast<float>(config_.target_width),
        static_cast<float>(plate_roi.rows) / static_cast<float>(config_.target_height)), 0.0F, 1.0F);
    result.sharpness_score = std::clamp(static_cast<float>(
        std::log1p(static_cast<double>(result.blur_score)) /
        std::log1p(static_cast<double>(config_.sharpness_reference))), 0.0F, 1.0F);
    const float brightness_distance = std::abs(result.brightness - config_.target_brightness);
    const float brightness_range = std::max(
        config_.target_brightness, 255.0F - config_.target_brightness);
    result.exposure_score = std::clamp(
        1.0F - brightness_distance / brightness_range, 0.0F, 1.0F);
    result.contrast_score = std::clamp(
        result.contrast / config_.contrast_reference, 0.0F, 1.0F);
    result.quality_score = std::clamp((
        config_.size_weight * result.size_score +
        config_.sharpness_weight * result.sharpness_score +
        config_.exposure_weight * result.exposure_score +
        config_.contrast_weight * result.contrast_score) / weight_sum_, 0.0F, 1.0F);

    if (plate_roi.cols < config_.min_width || plate_roi.rows < config_.min_height) {
        result.rejection_reason = "size";
    } else if (result.blur_score < config_.min_blur_score) {
        result.rejection_reason = "blur";
    } else if (result.brightness < config_.min_brightness ||
        result.brightness > config_.max_brightness) {
        result.rejection_reason = "brightness";
    } else if (result.contrast < config_.min_contrast) {
        result.rejection_reason = "contrast";
    } else if (result.quality_score < config_.min_quality_score) {
        result.rejection_reason = "quality_score";
    } else {
        result.acceptable = true;
    }
    return result;
}

}  // namespace vehicle_system
