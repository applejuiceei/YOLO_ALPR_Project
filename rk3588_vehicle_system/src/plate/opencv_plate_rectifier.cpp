#include "plate/opencv_plate_rectifier.hpp"

#include <algorithm>
#include <cmath>
#include <opencv2/imgproc.hpp>
#include <stdexcept>
#include <utility>
#include <vector>

namespace vehicle_system {
namespace {

float distance(const cv::Point2f& first, const cv::Point2f& second) {
    const cv::Point2f delta = first - second;
    return std::sqrt(delta.dot(delta));
}

float mean_y(const cv::Point2f& first, const cv::Point2f& second) {
    return (first.y + second.y) * 0.5F;
}

std::pair<cv::Point2f, cv::Point2f> left_to_right(
    cv::Point2f first,
    cv::Point2f second) {
    if (first.x > second.x || (first.x == second.x && first.y > second.y)) {
        std::swap(first, second);
    }
    return {first, second};
}

}  // namespace

OpenCvPlateRectifier::OpenCvPlateRectifier(PlateRectifierConfig config)
    : config_(std::move(config)) {
    const bool scalar_values_valid = std::isfinite(config_.min_edge_length) &&
        std::isfinite(config_.min_quadrilateral_area) &&
        std::isfinite(config_.corner_tolerance) &&
        std::isfinite(config_.max_abs_rotation_degrees);
    if ((config_.mode != "resize" && config_.mode != "perspective") ||
        config_.output_width < 2 || config_.output_height < 2 ||
        !scalar_values_valid || config_.min_edge_length <= 0.0F ||
        config_.min_quadrilateral_area <= 0.0F || config_.corner_tolerance < 0.0F ||
        config_.max_abs_rotation_degrees <= 0.0F ||
        config_.max_abs_rotation_degrees > 90.0F) {
        throw std::invalid_argument("Invalid OpenCvPlateRectifier configuration");
    }
}

std::optional<RectifiedPlate> OpenCvPlateRectifier::resize_only(
    const PlateCrop& plate_crop,
    PlateRectificationMethod method) const {
    if (plate_crop.roi.empty() || plate_crop.roi.type() != CV_8UC3) {
        return std::nullopt;
    }
    RectifiedPlate result;
    cv::resize(plate_crop.roi, result.image,
        cv::Size(config_.output_width, config_.output_height), 0.0, 0.0, cv::INTER_LINEAR);
    result.method = method;
    return result;
}

std::optional<std::array<cv::Point2f, 4>> OpenCvPlateRectifier::order_corners(
    const PlateCrop& plate_crop) const {
    if (plate_crop.roi.empty()) {
        return std::nullopt;
    }

    std::vector<cv::Point2f> points;
    points.reserve(plate_crop.corners.size());
    for (const cv::Point2f& input_point : plate_crop.corners) {
        if (!std::isfinite(input_point.x) || !std::isfinite(input_point.y) ||
            input_point.x < -config_.corner_tolerance ||
            input_point.y < -config_.corner_tolerance ||
            input_point.x > static_cast<float>(plate_crop.roi.cols) + config_.corner_tolerance ||
            input_point.y > static_cast<float>(plate_crop.roi.rows) + config_.corner_tolerance) {
            return std::nullopt;
        }
        points.emplace_back(
            std::clamp(input_point.x, 0.0F, static_cast<float>(plate_crop.roi.cols)),
            std::clamp(input_point.y, 0.0F, static_cast<float>(plate_crop.roi.rows)));
    }

    std::vector<cv::Point2f> hull;
    cv::convexHull(points, hull, false, true);
    if (hull.size() != 4U ||
        std::abs(cv::contourArea(hull)) < static_cast<double>(config_.min_quadrilateral_area)) {
        return std::nullopt;
    }

    cv::Point2f center(0.0F, 0.0F);
    for (const cv::Point2f& point : hull) {
        center += point;
    }
    center *= 0.25F;
    std::sort(hull.begin(), hull.end(), [&](const cv::Point2f& left, const cv::Point2f& right) {
        return std::atan2(left.y - center.y, left.x - center.x) <
            std::atan2(right.y - center.y, right.x - center.x);
    });

    std::array<float, 4> edge_lengths{};
    for (std::size_t index = 0; index < hull.size(); ++index) {
        edge_lengths[index] = distance(hull[index], hull[(index + 1U) % hull.size()]);
        if (edge_lengths[index] < config_.min_edge_length) {
            return std::nullopt;
        }
    }
    const float even_pair_length = edge_lengths[0] + edge_lengths[2];
    const float odd_pair_length = edge_lengths[1] + edge_lengths[3];
    const std::size_t first_edge_start = even_pair_length >= odd_pair_length ? 0U : 1U;
    const std::size_t second_edge_start = (first_edge_start + 2U) % 4U;
    const auto first_edge = std::make_pair(
        hull[first_edge_start], hull[(first_edge_start + 1U) % 4U]);
    const auto second_edge = std::make_pair(
        hull[second_edge_start], hull[(second_edge_start + 1U) % 4U]);

    const bool first_is_top = mean_y(first_edge.first, first_edge.second) <=
        mean_y(second_edge.first, second_edge.second);
    const auto top = left_to_right(
        first_is_top ? first_edge.first : second_edge.first,
        first_is_top ? first_edge.second : second_edge.second);
    const auto bottom = left_to_right(
        first_is_top ? second_edge.first : first_edge.first,
        first_is_top ? second_edge.second : first_edge.second);
    const float angle_degrees = static_cast<float>(
        std::atan2(top.second.y - top.first.y, top.second.x - top.first.x) *
        180.0 / CV_PI);
    if (std::abs(angle_degrees) > config_.max_abs_rotation_degrees) {
        return std::nullopt;
    }

    return std::array<cv::Point2f, 4>{
        top.first, top.second, bottom.second, bottom.first};
}

std::optional<RectifiedPlate> OpenCvPlateRectifier::rectify(
    const PlateCrop& plate_crop) const {
    if (plate_crop.roi.empty() || plate_crop.roi.type() != CV_8UC3) {
        return std::nullopt;
    }
    if (config_.mode == "resize") {
        return resize_only(plate_crop, PlateRectificationMethod::Resize);
    }

    const auto ordered = order_corners(plate_crop);
    if (!ordered.has_value()) {
        return config_.fallback_to_resize ?
            resize_only(plate_crop, PlateRectificationMethod::ResizeFallback) : std::nullopt;
    }

    const std::array<cv::Point2f, 4> destination = {
        cv::Point2f(0.0F, 0.0F),
        cv::Point2f(static_cast<float>(config_.output_width - 1), 0.0F),
        cv::Point2f(static_cast<float>(config_.output_width - 1),
            static_cast<float>(config_.output_height - 1)),
        cv::Point2f(0.0F, static_cast<float>(config_.output_height - 1))};
    const cv::Mat transform = cv::getPerspectiveTransform(*ordered, destination);
    if (!cv::checkRange(transform)) {
        return config_.fallback_to_resize ?
            resize_only(plate_crop, PlateRectificationMethod::ResizeFallback) : std::nullopt;
    }

    RectifiedPlate result;
    cv::warpPerspective(plate_crop.roi, result.image, transform,
        cv::Size(config_.output_width, config_.output_height),
        cv::INTER_LINEAR, cv::BORDER_REPLICATE);
    if (result.image.empty()) {
        return config_.fallback_to_resize ?
            resize_only(plate_crop, PlateRectificationMethod::ResizeFallback) : std::nullopt;
    }
    result.ordered_source_corners = *ordered;
    result.method = PlateRectificationMethod::Perspective;
    return result;
}

}  // namespace vehicle_system
