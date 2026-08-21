#include "cropper/vehicle_cropper.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <utility>

namespace vehicle_system {
namespace {

double expansion_pixels(double length, float ratio) {
    constexpr double floating_point_tolerance = 1.0e-6;
    return std::ceil(length * static_cast<double>(ratio) - floating_point_tolerance);
}

}  // namespace

VehicleCropper::VehicleCropper(VehicleCropperConfig config) : config_(config) {
    if (!std::isfinite(config_.expand_left) || !std::isfinite(config_.expand_right) ||
        !std::isfinite(config_.expand_top) || !std::isfinite(config_.expand_bottom) ||
        config_.expand_left < 0.0F || config_.expand_right < 0.0F ||
        config_.expand_top < 0.0F || config_.expand_bottom < 0.0F) {
        throw std::invalid_argument("VehicleCropper expansion ratios must be non-negative");
    }
    if (config_.min_width <= 0 || config_.min_height <= 0) {
        throw std::invalid_argument("VehicleCropper minimum dimensions must be positive");
    }
}

std::optional<VehicleCrop> VehicleCropper::crop(
    const cv::Mat& frame,
    const Detection& detection) const {
    if (frame.empty() || detection.bbox.width <= 0 || detection.bbox.height <= 0) {
        return std::nullopt;
    }

    const double width = static_cast<double>(detection.bbox.width);
    const double height = static_cast<double>(detection.bbox.height);
    const double left = static_cast<double>(detection.bbox.x) - expansion_pixels(width, config_.expand_left);
    const double top = static_cast<double>(detection.bbox.y) - expansion_pixels(height, config_.expand_top);
    const double right = static_cast<double>(detection.bbox.x) + width +
        expansion_pixels(width, config_.expand_right);
    const double bottom = static_cast<double>(detection.bbox.y) + height +
        expansion_pixels(height, config_.expand_bottom);

    const int clipped_left = static_cast<int>(std::clamp(left, 0.0, static_cast<double>(frame.cols)));
    const int clipped_top = static_cast<int>(std::clamp(top, 0.0, static_cast<double>(frame.rows)));
    const int clipped_right = static_cast<int>(std::clamp(right, 0.0, static_cast<double>(frame.cols)));
    const int clipped_bottom = static_cast<int>(std::clamp(bottom, 0.0, static_cast<double>(frame.rows)));
    const cv::Rect clipped(
        clipped_left,
        clipped_top,
        std::max(0, clipped_right - clipped_left),
        std::max(0, clipped_bottom - clipped_top));

    if (clipped.width < config_.min_width || clipped.height < config_.min_height) {
        return std::nullopt;
    }

    cv::Mat roi = frame(clipped);
    if (config_.clone_output) {
        roi = roi.clone();
    }
    return VehicleCrop{clipped, std::move(roi)};
}

}  // namespace vehicle_system
