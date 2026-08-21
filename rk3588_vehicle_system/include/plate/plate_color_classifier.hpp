#pragma once

#include "common/types.hpp"

#include <opencv2/core.hpp>

namespace vehicle_system {

class IPlateColorClassifier {
public:
    virtual ColorResult classify(const cv::Mat& plate_roi) = 0;
    virtual ClassifierTiming last_timing() const = 0;
    virtual ~IPlateColorClassifier() = default;
};

}  // namespace vehicle_system
