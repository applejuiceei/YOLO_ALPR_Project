#pragma once

#include "common/types.hpp"

#include <opencv2/core.hpp>
#include <vector>

namespace vehicle_system {

class IVehicleDetector {
public:
    virtual std::vector<Detection> detect(const cv::Mat& frame) = 0;
    virtual DetectorTiming last_timing() const = 0;
    virtual ~IVehicleDetector() = default;
};

}  // namespace vehicle_system

