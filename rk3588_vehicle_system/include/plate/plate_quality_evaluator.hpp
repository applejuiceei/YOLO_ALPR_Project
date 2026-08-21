#pragma once

#include "common/types.hpp"

#include <opencv2/core.hpp>

namespace vehicle_system {

class IPlateQualityEvaluator {
public:
    virtual PlateQuality evaluate(const cv::Mat& plate_roi) const = 0;
    virtual ~IPlateQualityEvaluator() = default;
};

}  // namespace vehicle_system
