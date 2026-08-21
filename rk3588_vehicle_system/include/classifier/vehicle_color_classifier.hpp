#pragma once

#include "common/types.hpp"

#include <opencv2/core.hpp>

namespace vehicle_system {

class IVehicleColorClassifier {
public:
    virtual ColorResult classify(const cv::Mat& vehicle_roi) = 0;
    virtual ClassifierTiming last_timing() const = 0;
    virtual ~IVehicleColorClassifier() = default;
};

}  // namespace vehicle_system
