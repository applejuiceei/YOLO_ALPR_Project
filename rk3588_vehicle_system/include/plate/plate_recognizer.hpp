#pragma once

#include "common/types.hpp"

#include <opencv2/core.hpp>

namespace vehicle_system {

class IPlateRecognizer {
public:
    virtual PlateOCRResult recognize(const cv::Mat& plate_roi) = 0;
    virtual PlateRecognizerTiming last_timing() const = 0;
    virtual ~IPlateRecognizer() = default;
};

}  // namespace vehicle_system
