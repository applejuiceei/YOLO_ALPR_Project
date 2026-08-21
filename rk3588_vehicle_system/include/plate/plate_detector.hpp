#pragma once

#include "common/types.hpp"

#include <opencv2/core.hpp>
#include <vector>

namespace vehicle_system {

class IPlateDetector {
public:
    virtual std::vector<PlateDetection> detect(const cv::Mat& vehicle_roi) = 0;
    virtual DetectorTiming last_timing() const = 0;
    virtual ~IPlateDetector() = default;
};

}  // namespace vehicle_system
